const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const VG = require('./core.js');
const { createServer } = require('./server.js');

test('1. Invoice Status Model — all 10 required statuses exist and are seeded', () => {
  const expectedStatuses = [
    'received',
    'pending_verification',
    'under_review',
    'flagged',
    'rejected',
    'verified_approved',
    'ready_to_pay',
    'scheduled',
    'paid',
    'on_hold'
  ];
  assert.deepEqual(VG.ALL_STATUS_KEYS, expectedStatuses);

  const state = VG.createInitialState();
  const presentStatuses = new Set(state.invoices.map((i) => i.status));
  for (const st of expectedStatuses) {
    assert.equal(presentStatuses.has(st), true, `Missing seeded invoice for status: ${st}`);
  }
});

test('2. Main Overview KPIs — status totals, ready-to-pay buckets, oldest pending, overdue, and multi-currency', () => {
  const state = VG.createInitialState();
  const kpis = VG.computeKPIs(state, '2026-10-10T12:00:00Z');

  assert.equal(kpis.totalInvoices, 10);
  for (const key of VG.ALL_STATUS_KEYS) {
    assert.equal(kpis.byStatus[key].count, 1, `Expected count 1 for ${key}`);
    assert.ok(kpis.byStatus[key].totalAmount > 0, `Expected positive amount for ${key}`);
  }

  // Pending verification queue (received + pending_verification + under_review = 3)
  assert.equal(kpis.pendingVerification.count, 3);
  assert.ok(kpis.pendingVerification.oldestInvoice);
  assert.equal(kpis.pendingVerification.oldestInvoice.id, 'INV-1002');
  assert.ok(kpis.pendingVerification.oldestInvoice.ageHours >= 120);

  // Flagged & Scam prevented
  assert.equal(kpis.flagged.count, 1);
  assert.equal(kpis.flagged.amountAtRisk, 9850);
  assert.equal(kpis.flagged.rejectedCount, 1);
  assert.equal(kpis.flagged.confirmedScamAmount, 49500);
  assert.equal(kpis.flagged.moneySaved, 59350);

  // Overdue (INV-1010 due 2026-10-01 is on_hold & unpaid; INV-1005 is rejected so excluded)
  assert.equal(kpis.overdue.count, 1);
  assert.equal(kpis.overdue.invoices[0].id, 'INV-1010');

  // Currency conversion check (EUR -> USD)
  state.settings.baseCurrency = 'USD';
  const kpisUsd = VG.computeKPIs(state, '2026-10-10T12:00:00Z');
  assert.equal(kpisUsd.baseCurrency, 'USD');
  assert.ok(kpisUsd.flagged.amountAtRisk > kpis.flagged.amountAtRisk);
});

test('3. Invoice List, Search, Filtering, Sorting & CSV Export (including edge cases)', () => {
  const state = VG.createInitialState();

  // Search by PO number
  const byPo = VG.queryInvoices(state, { search: 'PO-2026-412' });
  assert.equal(byPo.length, 1);
  assert.equal(byPo[0].id, 'INV-1003');

  // Filter by risk level high
  const highRisk = VG.queryInvoices(state, { riskLevel: 'high' });
  assert.ok(highRisk.length >= 2);
  assert.ok(highRisk.every((i) => i.riskLevel === 'high'));

  // Filter by amount range
  const midRange = VG.queryInvoices(state, { amountMin: 5000, amountMax: 10000 });
  assert.ok(midRange.length > 0);
  assert.ok(midRange.every((i) => i.amount >= 5000 && i.amount <= 10000));

  // Sort by amount descending
  const sortedDesc = VG.queryInvoices(state, { sortBy: 'amount', sortDir: 'desc' });
  assert.ok(sortedDesc[0].amount >= sortedDesc[sortedDesc.length - 1].amount);

  // CSV export escaping with commas and quotes
  const csv = VG.exportInvoicesCSV([
    {
      id: 'INV-CSV',
      invoiceNumber: 'INV-"QUOTE",1',
      supplierName: 'Acme, Inc.',
      amount: 100,
      currency: 'EUR',
      issueDate: '2026-10-01',
      dueDate: '2026-10-10',
      status: 'received',
      riskLevel: 'low',
      riskScore: 0
    }
  ]);
  assert.ok(csv.includes('"INV-""QUOTE"",1"'));
  assert.ok(csv.includes('"Acme, Inc."'));
});

test('4. Audit and Fraud Checks — all 9 checks detect fraud and edge cases', () => {
  const state = VG.createInitialState();

  // Flagged invoice INV-1004 has lookalike domain, IBAN mismatch, PO mismatch, just-under-10k amount, and PDF tampering
  const flaggedInv = state.invoices.find((i) => i.id === 'INV-1004');
  const res = VG.runAuditChecks(flaggedInv, state);
  assert.equal(res.checklist.length, 9);
  assert.equal(res.riskLevel, 'high');
  assert.ok(res.riskScore >= 65);

  const failedIds = res.checklist.filter((c) => c.status === 'failed').map((c) => c.id);
  assert.ok(failedIds.includes('bank_details'));
  assert.ok(failedIds.includes('three_way_match'));
  assert.ok(failedIds.includes('amount_checks'));
  assert.ok(failedIds.includes('document_checks'));
  assert.ok(failedIds.includes('email_sender'));

  // Duplicate detection test
  const dupCandidate = {
    ...state.invoices[0],
    id: 'INV-DUP-TEST'
  };
  const dupRes = VG.runAuditChecks(dupCandidate, state);
  const dupCheck = dupRes.checklist.find((c) => c.id === 'duplicate_detection');
  assert.equal(dupCheck.status, 'failed');

  // Zero / negative amount edge case
  const zeroInv = {
    ...state.invoices[0],
    id: 'INV-ZERO',
    invoiceNumber: 'UNIQUE-ZERO-1',
    amount: 0
  };
  const zeroRes = VG.runAuditChecks(zeroInv, state);
  assert.equal(zeroRes.checklist.find((c) => c.id === 'amount_checks').status, 'failed');
});

test('5 & 6. Workflow Actions, RBAC, Phone Callback Verification, and Multi-Level Approvals', () => {
  const state = VG.createInitialState();
  const viewer = state.users.find((u) => u.role === 'viewer');
  const auditor = state.users.find((u) => u.role === 'auditor');
  const approver1 = state.users.find((u) => u.id === 'USR-APPROVER-1');
  const approver2 = state.users.find((u) => u.id === 'USR-APPROVER-2');

  // Viewer cannot approve or flag
  assert.throws(
    () => VG.performWorkflowAction(state, 'INV-1001', 'approve', {}, viewer),
    /Permission denied/
  );

  // Auditor cannot approve
  assert.throws(
    () => VG.performWorkflowAction(state, 'INV-1001', 'approve', {}, auditor),
    /Permission denied/
  );

  // Phone callback verification clears recent bank change failure on INV-1010
  const inv1010 = state.invoices.find((i) => i.id === 'INV-1010');
  assert.equal(inv1010.checklist.find((c) => c.id === 'bank_details').status, 'failed');
  VG.performWorkflowAction(
    state,
    'INV-1010',
    'verify_callback',
    { note: 'Called CFO at +33 1 40 50 60 70' },
    auditor
  );
  assert.equal(inv1010.callbackVerified, true);
  assert.equal(inv1010.checklist.find((c) => c.id === 'bank_details').status, 'passed');

  // Multi-level approval on INV-1003 (€24,500 > €10,000 Level 1 threshold -> requires 2 approvals)
  const inv1003 = state.invoices.find((i) => i.id === 'INV-1003');
  assert.equal(inv1003.requiredApprovalLevels, 2);

  // First approval by Claire Dubois -> stays under_review (1/2)
  VG.performWorkflowAction(state, 'INV-1003', 'approve', { note: 'L1 ok' }, approver1);
  assert.equal(inv1003.status, 'under_review');
  assert.equal(inv1003.approvals.length, 1);

  // Same user cannot approve twice
  assert.throws(
    () => VG.performWorkflowAction(state, 'INV-1003', 'approve', { note: 'L2 self' }, approver1),
    /already recorded an approval/
  );

  // Second approval by Henri Vance (CFO) -> transitions to verified_approved
  VG.performWorkflowAction(state, 'INV-1003', 'approve', { note: 'L2 CFO ok' }, approver2);
  assert.equal(inv1003.status, 'verified_approved');
  assert.equal(inv1003.approvals.length, 2);

  // Comments & @mentions parsing
  VG.performWorkflowAction(
    state,
    'INV-1003',
    'comment',
    { text: 'Cleared with @henri.vance and @security_team' },
    auditor
  );
  const lastComment = inv1003.comments[inv1003.comments.length - 1];
  assert.deepEqual(lastComment.mentions, ['henri.vance', 'security_team']);
});

test('7 & 10. Payment Blocking Rules, Segregation of Duties (SoD), Partial Payments, Credit Notes & SEPA XML', () => {
  const state = VG.createInitialState();
  const approver1 = state.users.find((u) => u.id === 'USR-APPROVER-1');
  const payer = state.users.find((u) => u.id === 'USR-PAYER-1');
  const admin = state.users.find((u) => u.id === 'USR-ADMIN-1');

  // 1. Cannot pay flagged, unverified, or rejected invoices
  for (const blockedId of ['INV-1001', 'INV-1002', 'INV-1003', 'INV-1004', 'INV-1005', 'INV-1010']) {
    const inv = state.invoices.find((i) => i.id === blockedId);
    const check = VG.canPayInvoice(state, inv, payer);
    assert.equal(check.allowed, false, `Expected ${blockedId} (${inv.status}) to be blocked from payment`);
  }

  // 2. Segregation of Duties: INV-1007 was approved by USR-APPROVER-1 (Claire Dubois).
  // Even if Claire is given admin/payer rights or tries to pay, SoD blocks her!
  const inv1007 = state.invoices.find((i) => i.id === 'INV-1007');
  const sodCheckSameUser = VG.canPayInvoice(state, inv1007, { ...approver1, role: 'admin' });
  assert.equal(sodCheckSameUser.allowed, false);
  assert.match(sodCheckSameUser.reason, /Segregation of Duties violation/);

  // 3. Distinct Payer (Thomas Bernard) CAN pay INV-1007
  const sodCheckPayer = VG.canPayInvoice(state, inv1007, payer);
  assert.equal(sodCheckPayer.allowed, true);

  // 4. Early payment discount scheduling on INV-1006 (2% discount if scheduled <= 2026-10-15)
  const schedRes = VG.scheduleInvoicePayment(
    state,
    'INV-1006',
    { useEarlyDiscount: true },
    payer
  );
  assert.equal(schedRes.discountInfo.eligible, true);
  assert.equal(schedRes.discountInfo.discountAmount, 184); // 2% of 9200
  assert.equal(VG.getRemainingAmount(schedRes.invoice), 9016);

  // 5. Credit note + Partial payment + Full payment lifecycle on INV-1007 (€7,650)
  VG.recordPaymentOrCredit(state, 'INV-1007', { type: 'credit_note', amount: 650, reference: 'CN-390' }, payer);
  assert.equal(VG.getRemainingAmount(inv1007), 7000);
  assert.notEqual(inv1007.status, 'paid');

  VG.recordPaymentOrCredit(state, 'INV-1007', { amount: 3000, reference: 'PART-1' }, payer);
  assert.equal(VG.getRemainingAmount(inv1007), 4000);
  assert.notEqual(inv1007.status, 'paid');

  VG.recordPaymentOrCredit(state, 'INV-1007', { amount: 4000, reference: 'FINAL-1', reconciled: true }, payer);
  assert.equal(VG.getRemainingAmount(inv1007), 0);
  assert.equal(inv1007.status, 'paid');
  assert.equal(inv1007.reconciled, true);

  // 6. SEPA XML batch creation for remaining payable invoices (INV-1006, INV-1008)
  const batch = VG.createPaymentBatch(state, ['INV-1006', 'INV-1008'], { executionDate: '2026-10-10' }, payer);
  assert.equal(batch.invoiceCount, 2);
  assert.ok(batch.sepaXml.includes('urn:iso:std:iso:20022:tech:xsd:pain.001.001.03'));
  assert.ok(batch.sepaXml.includes('CS-2026-085'));
  assert.ok(batch.sepaXml.includes('LUM-8790'));

  // 7. Blacklisting a supplier immediately blocks payment even on a previously approved invoice
  VG.setSupplierStatus(state, 'SUP-01', 'blacklisted', admin, 'Emergency sanction');
  const inv1006 = state.invoices.find((i) => i.id === 'INV-1006');
  const blockedByBlacklist = VG.canPayInvoice(state, inv1006, payer);
  assert.equal(blockedByBlacklist.allowed, false);
  assert.match(blockedByBlacklist.reason, /blacklisted/);
});

test('8, 9, 11, 12, 13. Alerts, Audit Chain Integrity, OCR Ingestion & REST API Server', async () => {
  const state = VG.createInitialState();

  // Alerts check
  const alerts = VG.computeAlerts(state, '2026-10-10T12:00:00Z');
  const alertTypes = new Set(alerts.map((a) => a.type));
  assert.ok(alertTypes.has('high_risk'));
  assert.ok(alertTypes.has('sla_breach'));
  assert.ok(alertTypes.has('overdue'));
  assert.ok(alertTypes.has('bank_change'));

  // OCR Ingestion of spoofed scam invoice -> auto-flagged
  const scamInv = VG.ingestInvoice(
    state,
    {
      rawOcrText: `Invoice Number: CS-2026-777\nSupplier: CloudScale Infrastructure GmbH\nVAT: DE812345678\nIBAN: DE00999988887777666600\nTotal: 9900.00\nCurrency: EUR\nEmail: urgent@c1oudscale.de`
    },
    'email_inbox'
  );
  assert.equal(scamInv.status, 'flagged');
  assert.equal(scamInv.riskLevel, 'high');

  // Cryptographic Audit Log Integrity check
  const integrity = VG.verifyAuditLogIntegrity(state.auditLog);
  assert.equal(integrity.valid, true);
  assert.ok(integrity.count >= 2);

  // Verify HTTP server & REST API endpoints via handleRequest
  const { handleRequest } = createServer(state);
  async function callApi(method, url, body) {
    let statusCode = 200;
    let headers = {};
    let rawBody = '';
    const req = { method, url, headers: { host: 'localhost' }, body };
    const res = {
      writeHead(code, hdrs) {
        statusCode = code;
        headers = hdrs || {};
      },
      end(chunk) {
        if (chunk) rawBody += Buffer.isBuffer(chunk) ? chunk.toString('utf8') : String(chunk);
      }
    };
    await handleRequest(req, res);
    return {
      status: statusCode,
      headers,
      text: rawBody,
      json: () => JSON.parse(rawBody)
    };
  }

  const kpiRes = await callApi('GET', '/api/kpis');
  assert.equal(kpiRes.status, 200);
  assert.equal(kpiRes.json().totalInvoices, 11);

  const listRes = await callApi('GET', '/api/invoices?status=flagged');
  assert.equal(listRes.status, 200);
  assert.equal(listRes.json().length, 2);

  const ingestRes = await callApi('POST', '/api/invoices/ingest', {
    invoiceNumber: 'API-2026-01',
    supplierId: 'SUP-01',
    supplierName: 'CloudScale Infrastructure GmbH',
    vatNumber: 'DE812345678',
    iban: 'DE89370400440532013000',
    amount: 3200,
    currency: 'EUR',
    poNumber: 'PO-API-01',
    poAmount: 3200,
    grnStatus: 'matched',
    senderEmail: 'billing@cloudscale.de'
  });
  assert.equal(ingestRes.status, 201);
  assert.equal(ingestRes.json().invoiceNumber, 'API-2026-01');

  const htmlRes = await callApi('GET', '/');
  assert.equal(htmlRes.status, 200);
  assert.ok(htmlRes.text.includes('Vaultgard — Invoice Audit'));

  // Path traversal protection check
  const traversalRes = await callApi('GET', '/../../etc/passwd');
  assert.equal(traversalRes.status, 404);
});

let domHarness = null;
function getDomHarness() {
  if (domHarness) return domHarness;

  const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
  const appJs = fs.readFileSync(path.join(__dirname, 'app.js'), 'utf8');

  const htmlIds = new Set(Array.from(html.matchAll(/\bid="([^"]+)"/g), (m) => m[1]));
  const dynamicIds = new Set([
    'btn-detail-attach',
    'input-detail-comment',
    'btn-detail-comment',
    'input-wf-note',
    'input-vat-lookup',
    'btn-vat-lookup',
    'vat-lookup-result',
    'set-t1',
    'set-t2',
    'set-sla',
    'set-high-risk',
    'set-sod',
    'set-gdpr',
    'btn-save-settings'
  ]);

  const elements = new Map();
  function makeEl(id = '') {
    const listeners = {};
    const classes = new Set();
    const el = {
      id,
      value: '',
      checked: false,
      open: false,
      _html: '',
      _childMap: new Map(),
      textContent: '',
      className: '',
      parentNode: {},
      attributes: { 'data-theme': 'dark' },
      classList: {
        add(...cs) {
          cs.forEach((c) => {
            if (c) classes.add(c);
          });
          el.className = Array.from(classes).join(' ');
        },
        remove(...cs) {
          cs.forEach((c) => classes.delete(c));
          el.className = Array.from(classes).join(' ');
        },
        toggle(c, force) {
          const next = force !== undefined ? !!force : !classes.has(c);
          if (next) classes.add(c);
          else classes.delete(c);
          el.className = Array.from(classes).join(' ');
          return next;
        },
        contains(c) {
          return classes.has(c) || el.className.split(/\s+/).includes(c);
        }
      },
      get innerHTML() {
        return this._html;
      },
      set innerHTML(val) {
        this._html = String(val);
        this._childMap.clear();
        for (const m of this._html.matchAll(/\bid="([^"]+)"/g)) {
          if (!elements.has(m[1])) elements.set(m[1], makeEl(m[1]));
        }
      },
      addEventListener(evt, fn) {
        listeners[evt] = listeners[evt] || [];
        listeners[evt].push(fn);
      },
      trigger(evt, eventObj = {}) {
        for (const fn of listeners[evt] || []) {
          fn({ target: el, preventDefault() {}, stopPropagation() {}, ...eventObj });
        }
      },
      click() {
        this.trigger('click');
      },
      getAttribute(k) {
        return this.attributes[k] !== undefined ? this.attributes[k] : '';
      },
      setAttribute(k, v) {
        this.attributes[k] = String(v);
      },
      querySelectorAll(sel) {
        const trimmed = sel.trim();
        if (this._childMap.has(trimmed)) return this._childMap.get(trimmed);
        const results = [];
        if (trimmed === '[data-inspect-id]') {
          for (const m of this._html.matchAll(/data-inspect-id="([^"]+)"/g)) {
            const btn = makeEl();
            btn.setAttribute('data-inspect-id', m[1]);
            results.push(btn);
          }
        } else if (trimmed === '[data-close]') {
          for (const m of this._html.matchAll(/data-close="([^"]+)"/g)) {
            const btn = makeEl();
            btn.setAttribute('data-close', m[1]);
            results.push(btn);
          }
        }
        this._childMap.set(trimmed, results);
        return results;
      },
      showModal() {
        this.open = true;
      },
      close() {
        this.open = false;
      },
      appendChild() {},
      remove() {}
    };
    return el;
  }

  for (const id of [...htmlIds, ...dynamicIds]) {
    const el = makeEl(id);
    const tagRegex = new RegExp(`<[a-z0-9-]+\\s+[^>]*\\bid=["\']${id}["\'][^>]*>`, 'i');
    const tagMatch = html.match(tagRegex);
    if (tagMatch) {
      const tagStr = tagMatch[0];
      const classMatch = tagStr.match(/\bclass=["\']([^"\']+)["\']/);
      if (classMatch) {
        el.className = classMatch[1];
        classMatch[1].split(/\s+/).forEach((c) => {
          if (c) el.classList.add(c);
        });
      }
      for (const attrMatch of tagStr.matchAll(/\b([a-z0-9-]+)=["\']([^"\']*)["\']/gi)) {
        const [_, k, v] = attrMatch;
        if (k !== 'id' && k !== 'class') el.setAttribute(k, v);
      }
    }
    elements.set(id, el);
  }

  // Pre-parse nav tabs from index.html so document.querySelectorAll('.nav-tab') works
  const navButtons = [];
  for (const m of html.matchAll(/<button[^>]*class=["\'][^"\']*nav-tab[^"\']*["\'][^>]*>/g)) {
    const btnStr = m[0];
    const dataTabMatch = btnStr.match(/data-tab=["\']([^"\']+)["\']/);
    const tabName = dataTabMatch ? dataTabMatch[1] : '';
    const btnEl = makeEl(`nav-tab-${tabName}`);
    btnEl.className = 'nav-tab' + (btnStr.includes('active') ? ' active' : '');
    btnEl.classList.add('nav-tab');
    if (btnStr.includes('active')) btnEl.classList.add('active');
    btnEl.setAttribute('data-tab', tabName);
    btnEl.setAttribute('role', 'tab');
    btnEl.setAttribute('aria-selected', btnStr.includes('aria-selected="true"') ? 'true' : 'false');
    navButtons.push(btnEl);
  }

  // Define innerHTML accessor on sankey-container to read from sankey-diagram-wrapper if empty
  const sankeyContainerEl = elements.get('sankey-container');
  if (sankeyContainerEl) {
    Object.defineProperty(sankeyContainerEl, 'innerHTML', {
      get() {
        return this._html || elements.get('sankey-diagram-wrapper')?.innerHTML || '';
      },
      set(val) {
        this._html = String(val);
      }
    });
  }

  const memStore = new Map();
  globalThis.window = globalThis;
  globalThis.vgStorage = {
    getItem(k) {
      return memStore.get(k) || null;
    },
    setItem(k, v) {
      memStore.set(k, String(v));
    }
  };
  globalThis.Vaultgard = VG;
  globalThis.document = {
    documentElement: makeEl('html'),
    body: makeEl('body'),
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, makeEl(id));
      return elements.get(id);
    },
    querySelectorAll(sel) {
      const trimmed = sel.trim();
      if (trimmed === '.nav-tab') return navButtons;
      if (trimmed.startsWith('.')) {
        const c = trimmed.slice(1);
        const results = [];
        for (const el of elements.values()) {
          if (el.classList.contains(c)) results.push(el);
        }
        return results;
      }
      return [];
    },
    createElement(tag) {
      return makeEl(tag);
    }
  };

  require('./app.js');

  domHarness = { elements, memStore, html, appJs, htmlIds, dynamicIds, navButtons };
  return domHarness;
}

test('14. Frontend DOM & Controller Integrity — every getElementById in app.js exists in index.html', () => {
  const { elements, memStore, html, appJs, htmlIds, dynamicIds } = getDomHarness();

  const referencedIds = Array.from(
    appJs.matchAll(/getElementById\(['"]([^'"]+)['"]\)/g),
    (m) => m[1]
  );

  assert.ok(referencedIds.length >= 30);
  for (const id of referencedIds) {
    assert.ok(
      htmlIds.has(id) || dynamicIds.has(id),
      `app.js references getElementById("${id}") which is missing from index.html and dynamic templates`
    );
  }

  // 1. Check #kpi-top-cards renders at most 4 KPI cards ("Ready to Pay")
  const topCardsEl = elements.get('kpi-top-cards');
  assert.ok(topCardsEl, '#kpi-top-cards element must exist');
  const topCardsHtml = topCardsEl.innerHTML;
  const cardCount = (topCardsHtml.match(/class=["']card(?:\s|["'])/g) || []).length;
  assert.ok(cardCount <= 4, `Top KPI cards count (${cardCount}) must be <= 4`);
  assert.ok(cardCount >= 1, 'Top KPI cards must render');
  assert.ok(topCardsHtml.includes('Ready to Pay'), 'Top KPI cards must include Ready to Pay');

  // 10-status cards grid is rendered inside collapsible details
  assert.ok(elements.get('kpi-status-grid').innerHTML.includes('Received / New'));

  // 2. Check #invoices-tbody and #payable-tbody render valid table rows matching 7 and 6 column formats
  const invTbody = elements.get('invoices-tbody').innerHTML;
  assert.ok(invTbody.includes('CS-2026-091'), 'Invoices table must contain seeded invoice CS-2026-091');
  const invRows = invTbody.match(/<tr\b[^>]*>[\s\S]*?<\/tr>/g) || [];
  assert.ok(invRows.length > 0, 'Invoices table must contain rendered rows');
  for (const row of invRows) {
    const tdCount = (row.match(/<td\b/g) || []).length;
    assert.equal(tdCount, 7, `Invoices table row must have 7 columns, got ${tdCount}`);
  }

  const payTbody = elements.get('payable-tbody').innerHTML;
  assert.ok(payTbody.includes('NCS-2026-390'), 'Payable table must contain seeded invoice NCS-2026-390');
  const payRows = payTbody.match(/<tr\b[^>]*>[\s\S]*?<\/tr>/g) || [];
  assert.ok(payRows.length > 0, 'Payable table must contain rendered rows');
  for (const row of payRows) {
    const tdCount = (row.match(/<td\b/g) || []).length;
    assert.equal(tdCount, 6, `Payable table row must have 6 columns, got ${tdCount}`);
  }

  // 3. Check #sankey-container renders valid SVG diagram
  const sankeyContainer = elements.get('sankey-container');
  const sankeyWrapper = elements.get('sankey-diagram-wrapper');
  const sankeyHtml = sankeyContainer.innerHTML || sankeyWrapper.innerHTML;
  assert.ok(sankeyHtml.includes('<svg'), '#sankey-container must render valid SVG diagram');
  assert.ok(
    sankeyHtml.includes('<path') || sankeyHtml.includes('class="sankey-link"'),
    'Sankey diagram must render path links'
  );
  assert.ok(!sankeyHtml.includes('NaN'), 'Sankey SVG must not contain NaN');

  // 4. Check on-demand dialogs #dialog-alerts, #dialog-suppliers, #dialog-governance can be opened and contain their respective elements
  const dlgAlerts = elements.get('dialog-alerts');
  const dlgSuppliers = elements.get('dialog-suppliers');
  const dlgGov = elements.get('dialog-governance');

  dlgAlerts.showModal();
  assert.equal(dlgAlerts.open, true, 'dialog-alerts must open');
  assert.ok(elements.get('alerts-list').innerHTML.includes('SLA Breach'), 'dialog-alerts must contain alerts-list with SLA Breach');
  dlgAlerts.close();
  assert.equal(dlgAlerts.open, false, 'dialog-alerts must close');

  dlgSuppliers.showModal();
  assert.equal(dlgSuppliers.open, true, 'dialog-suppliers must open');
  assert.ok(elements.get('suppliers-grid').innerHTML.includes('CloudScale Infrastructure GmbH'), 'dialog-suppliers must contain suppliers-grid');
  dlgSuppliers.close();
  assert.equal(dlgSuppliers.open, false, 'dialog-suppliers must close');

  dlgGov.showModal();
  assert.equal(dlgGov.open, true, 'dialog-governance must open');
  assert.ok(elements.get('audit-log-tbody').innerHTML.includes('SYSTEM_INIT'), 'dialog-governance must contain audit-log-tbody with SYSTEM_INIT');
  assert.ok(elements.get('analytics-summary').innerHTML.includes('Verification Turnaround Time by Supplier'), 'dialog-governance must contain turnaround summary');
  assert.ok(elements.get('analytics-summary').innerHTML.includes('Top Suppliers by Volume'), 'dialog-governance must contain top suppliers');
  dlgGov.close();
  assert.equal(dlgGov.open, false, 'dialog-governance must close');

  // Verify Saved View persistence
  elements.get('btn-save-view').click();
  assert.ok(memStore.get('vaultgard_saved_views').includes('Custom View #6'));

  // Verify theme switch & sidebar toggle
  elements.get('btn-theme-toggle').click();
  elements.get('btn-toggle-sidebar').click();
});

test('15. Regression Suite — OCR multiline & thousand-separator parsing, Analytics currency consistency, Discount/CreditNote math, RBAC scope, and Batch deduplication', async () => {
  // 1. OCR multiline scam preset (IBAN before Total, empty PO before Issue Date, thousand separators)
  const scamPreset = `Invoice Number: CS-2026-999
Supplier: CloudScale Infrastructure GmbH
VAT: DE812345678
IBAN: DE99000099998888777766
Total: 12,450.50
Currency: EUR
PO: 
Issue Date: 2026-10-10
Due Date: 2026-10-12
Email: urgent@c1oudscale.de`;
  const parsed = VG.parseOcrText(scamPreset);
  assert.equal(parsed.iban, 'DE99000099998888777766');
  assert.equal(parsed.poNumber, '');
  assert.equal(parsed.amount, 12450.5);
  assert.equal(parsed.issueDate, '2026-10-10');
  assert.equal(parsed.dueDate, '2026-10-12');

  // Also test Due Date without Issue Date does not corrupt Issue Date
  const dueOnly = VG.parseOcrText('Invoice: INV-900\nDue Date: 2026-11-30\nTotal: 1.250,75');
  assert.equal(dueOnly.dueDate, '2026-11-30');
  assert.equal(dueOnly.issueDate, '2026-10-10');
  assert.equal(dueOnly.amount, 1250.75);

  // 2. Seeded RECEIVED invoice (INV-1001) starts with 'pending' checklist items until run_checks
  const state = VG.createInitialState();
  const inv1001 = state.invoices.find((i) => i.id === 'INV-1001');
  assert.equal(inv1001.status, 'received');
  assert.equal(inv1001.checklist.length, 9);
  assert.ok(inv1001.checklist.every((c) => c.status === 'pending'));

  // 3. Analytics currency conversion consistency (no double EUR->USD conversion) & supplier turnaround
  state.settings.baseCurrency = 'USD';
  const kpisUsd = VG.computeKPIs(state);
  const anUsd = VG.computeAnalytics(state);
  assert.equal(anUsd.moneySaved, kpisUsd.flagged.moneySaved);
  assert.equal(anUsd.moneySavedEur, 59350);
  assert.ok(Array.isArray(anUsd.turnaroundBySupplier) && anUsd.turnaroundBySupplier.length >= 5);
  state.settings.baseCurrency = 'EUR';

  // 4. Early discount idempotency & forecast no double-counting
  const payer = state.users.find((u) => u.id === 'USR-PAYER-1');
  const forecastBefore = VG.computeCashFlowForecast(state);
  assert.equal(forecastBefore.potentialEarlyDiscountSavings, 298.75); // 184 on INV-1006 + 114.75 on INV-1007

  VG.scheduleInvoicePayment(state, 'INV-1006', { useEarlyDiscount: true }, payer);
  const inv1006 = state.invoices.find((i) => i.id === 'INV-1006');
  assert.equal(inv1006.appliedDiscountAmount, 184);
  assert.equal(VG.getRemainingAmount(inv1006), 9016);

  // Calling computeEarlyDiscount again still reports 184 on net face value (not 2% of 9016 = 180.32)
  const reDisc = VG.computeEarlyDiscount(inv1006, '2026-10-10');
  assert.equal(reDisc.discountAmount, 184);
  assert.equal(reDisc.alreadyApplied, true);

  // Forecast potentialEarlyDiscountSavings only counts uncaptured discount (114.75 on INV-1007)
  const forecastAfter = VG.computeCashFlowForecast(state);
  assert.equal(forecastAfter.potentialEarlyDiscountSavings, 114.75);

  // 5. Credit note blocked on rejected (confirmed scam) and flagged invoices
  assert.throws(
    () => VG.recordPaymentOrCredit(state, 'INV-1005', { type: 'credit_note', amount: 1000 }, payer),
    /Cannot apply credit note/
  );
  assert.throws(
    () => VG.recordPaymentOrCredit(state, 'INV-1004', { type: 'credit_note', amount: 1000 }, payer),
    /Cannot apply credit note/
  );

  // 6. RBAC: Approver with low maxApprovalAmount can still REJECT a high-amount scam invoice,
  //    and department-scoped actors cannot modify or pay out-of-scope invoices
  const lowLimitApprover = {
    id: 'USR-APP-LOW',
    name: 'Junior Approver',
    role: 'approver',
    departments: ['Logistics'],
    entities: ['Vaultgard EU'],
    maxApprovalAmount: 5000
  };
  // Can reject €9,850 flagged invoice in Logistics even though 9850 > maxApprovalAmount (5000)
  VG.performWorkflowAction(state, 'INV-1004', 'reject', { reason: 'Confirmed lookalike domain scam' }, lowLimitApprover);
  assert.equal(state.invoices.find((i) => i.id === 'INV-1004').status, 'rejected');

  // Cannot act on Finance department invoice (out of department scope)
  assert.throws(
    () => VG.performWorkflowAction(state, 'INV-1005', 'hold', { reason: 'Out of dept' }, lowLimitApprover),
    /Actor department scope/
  );

  // Scoped payer cannot pay Engineering invoice if restricted to Operations
  const opsOnlyPayer = { ...payer, departments: ['Operations'] };
  assert.equal(VG.canPayInvoice(state, inv1006, opsOnlyPayer).allowed, false);

  // 7. SEPA batch deduplication, blocking re-batching, and batch reconciliation
  const batch = VG.createPaymentBatch(
    state,
    ['INV-1006', 'INV-1006', 'INV-1007'],
    { executionDate: '2026-10-10' },
    payer
  );
  assert.equal(batch.invoiceCount, 2);
  assert.equal(VG.canPayInvoice(state, inv1006, payer, { forBatch: true }).allowed, false);
  assert.match(VG.canPayInvoice(state, inv1006, payer, { forBatch: true }).reason, /already assigned to SEPA batch/);
  assert.throws(
    () => VG.createPaymentBatch(state, ['INV-1006'], { executionDate: '2026-10-10' }, payer),
    /already assigned to SEPA batch/
  );

  VG.reconcilePaymentBatch(state, batch.id, payer);
  assert.equal(batch.status, 'reconciled');
  assert.equal(inv1006.status, 'paid');
  assert.equal(inv1006.reconciled, true);

  // 8. Static server blocks dot-files
  const { handleRequest } = createServer(state);
  let dotStatus = 200;
  await handleRequest(
    { method: 'GET', url: '/.git/HEAD', headers: { host: 'localhost' } },
    {
      writeHead(code) {
        dotStatus = code;
      },
      end() {}
    }
  );
  assert.equal(dotStatus, 404);
});

test('16. Suite A: Primary Navigation Structure — at most 3 top-level tabs (Overview, Invoices, Payments) & workspace layout', () => {
  const { html, navButtons, elements } = getDomHarness();

  // 1. Static check of index.html navigation: primary navigation contains at most 3 top-level tabs
  const navMatch = html.match(/<nav class="nav-tabs"[^>]*>([\s\S]*?)<\/nav>/);
  assert.ok(navMatch, '<nav class="nav-tabs"> must exist in index.html');

  const navTabs = Array.from(navMatch[1].matchAll(/data-tab="([^"]+)"/g), (m) => m[1]);
  assert.equal(navTabs.length, 3, `Primary navigation must contain at most 3 top-level tabs, got ${navTabs.length}`);
  assert.deepEqual([...navTabs].sort(), ['invoices', 'overview', 'payments']);

  // 2. Obsolete primary tabs (alerts, suppliers, governance) do NOT exist in the primary navigation tablist
  assert.equal(navTabs.includes('alerts'), false, 'alerts must not be a primary navigation tab');
  assert.equal(navTabs.includes('suppliers'), false, 'suppliers must not be a primary navigation tab');
  assert.equal(navTabs.includes('governance'), false, 'governance must not be a primary navigation tab');

  // 3. Panel containers #panel-overview, #panel-invoices, #panel-payments exist in <main>
  const mainMatch = html.match(/<main\b[^>]*>([\s\S]*?)<\/main>/);
  assert.ok(mainMatch, '<main> container must exist in index.html');
  assert.ok(mainMatch[1].includes('id="panel-overview"'), '#panel-overview must exist in <main>');
  assert.ok(mainMatch[1].includes('id="panel-invoices"'), '#panel-invoices must exist in <main>');
  assert.ok(mainMatch[1].includes('id="panel-payments"'), '#panel-payments must exist in <main>');

  // 4. Controller interaction: In DOM harness, clicking each nav-tab toggles active class and panels
  const overviewBtn = navButtons.find((b) => b.getAttribute('data-tab') === 'overview');
  const invoicesBtn = navButtons.find((b) => b.getAttribute('data-tab') === 'invoices');
  const paymentsBtn = navButtons.find((b) => b.getAttribute('data-tab') === 'payments');
  assert.ok(overviewBtn && invoicesBtn && paymentsBtn, 'All 3 nav buttons must be found in harness');

  invoicesBtn.click();
  assert.equal(invoicesBtn.classList.contains('active'), true, 'Invoices tab button must be active');
  assert.equal(invoicesBtn.getAttribute('aria-selected'), 'true');
  assert.equal(elements.get('panel-invoices').classList.contains('active'), true, 'panel-invoices must be active');
  assert.equal(overviewBtn.classList.contains('active'), false);
  assert.equal(elements.get('panel-overview').classList.contains('active'), false);

  paymentsBtn.click();
  assert.equal(paymentsBtn.classList.contains('active'), true, 'Payments tab button must be active');
  assert.equal(paymentsBtn.getAttribute('aria-selected'), 'true');
  assert.equal(elements.get('panel-payments').classList.contains('active'), true, 'panel-payments must be active');
  assert.equal(invoicesBtn.classList.contains('active'), false);

  overviewBtn.click();
  assert.equal(overviewBtn.classList.contains('active'), true, 'Overview tab button must be active');
  assert.equal(overviewBtn.getAttribute('aria-selected'), 'true');
  assert.equal(elements.get('panel-overview').classList.contains('active'), true, 'panel-overview must be active');
});

test('17. Suite B: Overview KPI Summary & Anti-Clutter — at most 4 KPI summary cards & 10-status grid inside collapsible details', () => {
  const { html, elements } = getDomHarness();
  const state = VG.createInitialState();
  const kpis = VG.computeKPIs(state, '2026-10-10T12:00:00Z');

  // 1. #kpi-top-cards contains at most 4 KPI summary cards
  const topCardsEl = elements.get('kpi-top-cards');
  assert.ok(topCardsEl, '#kpi-top-cards element must exist');
  const topCardsHtml = topCardsEl.innerHTML;
  const cardCount = (topCardsHtml.match(/class=["']card(?:\s|["'])/g) || []).length;
  assert.ok(cardCount <= 4, `Top KPI summary cards count (${cardCount}) must be <= 4`);
  assert.ok(cardCount >= 3, `Top KPI cards should display core metrics (found ${cardCount})`);
  assert.ok(topCardsHtml.includes('Ready to Pay'), 'KPI card for Ready to Pay must be present');
  assert.ok(topCardsHtml.includes('In Audit Queue'), 'KPI card for In Audit Queue must be present');
  assert.ok(topCardsHtml.includes('Fraud Prevented'), 'KPI card for Fraud Prevented must be present');

  // 2. 10-status cards grid is NOT cluttering the primary Overview surface (inside <details> collapsible)
  const detailsBlocks = html.match(/<details\b[^>]*>([\s\S]*?)<\/details>/g) || [];
  const statusGridInsideDetails = detailsBlocks.some((block) => block.includes('id="kpi-status-grid"'));
  assert.ok(statusGridInsideDetails, '10-status cards grid must be housed inside a <details> collapsible element');

  // 3. Monetary formatting and currency resilience
  const formattedEur = VG.formatMoney(kpis.readyToPay.thisMonth, 'EUR');
  assert.ok(formattedEur.includes('€') || formattedEur.includes('EUR'), 'KPI amounts must include EUR currency symbol');

  state.settings.baseCurrency = 'USD';
  const kpisUsd = VG.computeKPIs(state, '2026-10-10T12:00:00Z');
  assert.equal(kpisUsd.baseCurrency, 'USD');
  const formattedUsd = VG.formatMoney(kpisUsd.readyToPay.thisMonth, 'USD');
  assert.ok(formattedUsd.includes('$') || formattedUsd.includes('USD'), 'KPI amounts must include USD currency symbol');
  state.settings.baseCurrency = 'EUR';

  // 4. Edge cases: Empty invoices array
  const emptyState = { ...state, invoices: [] };
  const emptyKpis = VG.computeKPIs(emptyState, '2026-10-10T12:00:00Z');
  assert.equal(emptyKpis.totalInvoices, 0);
  const emptySum = Object.values(emptyKpis.byStatus).reduce((acc, s) => acc + s.totalAmount, 0);
  assert.equal(emptySum, 0);
  assert.equal(emptyKpis.readyToPay.count, 0);
  assert.equal(emptyKpis.flagged.count, 0);
});

test('18. Suite C: Main Tables Simplification & Modal Details — <= 7 columns in Invoices, <= 6 in Payments, and on-demand modal details', () => {
  const { html, elements } = getDomHarness();

  // 1. Invoices Table <thead> has at most 7 <th> columns
  const invTheadMatch = html.match(/<table[^>]*id="invoices-table"[^>]*>[\s\S]*?<thead>([\s\S]*?)<\/thead>/);
  assert.ok(invTheadMatch, '#invoices-table <thead> must exist');
  const invThs = (invTheadMatch[1].match(/<th\b/g) || []).length;
  assert.ok(invThs <= 7, `Invoices table headers count (${invThs}) must be <= 7`);
  assert.equal(invThs, 7, 'Invoices table headers must be exactly 7 columns');

  // 2. Payments Table <thead> has at most 6 <th> columns
  const payTheadMatch = html.match(/<table[^>]*id="payments-table"[^>]*>[\s\S]*?<thead>([\s\S]*?)<\/thead>/);
  assert.ok(payTheadMatch, '#payments-table <thead> must exist');
  const payThs = (payTheadMatch[1].match(/<th\b/g) || []).length;
  assert.ok(payThs <= 6, `Payments table headers count (${payThs}) must be <= 6`);
  assert.equal(payThs, 6, 'Payments table headers must be exactly 6 columns');

  // 3. Table rows rendered in tbody match header counts
  const invTbody = elements.get('invoices-tbody');
  assert.ok(invTbody, '#invoices-tbody must exist');
  const invRows = invTbody.innerHTML.match(/<tr\b[^>]*>[\s\S]*?<\/tr>/g) || [];
  assert.ok(invRows.length > 0, 'Invoices table must have rendered rows');
  for (const row of invRows) {
    const tdCount = (row.match(/<td\b/g) || []).length;
    assert.equal(tdCount, 7, `Every row in #invoices-tbody must have exactly 7 <td> cells, got ${tdCount}`);
  }

  const payTbody = elements.get('payable-tbody');
  assert.ok(payTbody, '#payable-tbody must exist');
  const payRows = payTbody.innerHTML.match(/<tr\b[^>]*>[\s\S]*?<\/tr>/g) || [];
  assert.ok(payRows.length > 0, 'Payments table must have rendered rows');
  for (const row of payRows) {
    const tdCount = (row.match(/<td\b/g) || []).length;
    assert.equal(tdCount, 6, `Every row in #payable-tbody must have exactly 6 <td> cells, got ${tdCount}`);
  }

  // 4. #dialog-invoice-detail exists and renders 9-point checklist and actions on demand
  assert.ok(html.includes('id="dialog-invoice-detail"'), '#dialog-invoice-detail must exist in index.html');
  assert.ok(html.includes('id="detail-dialog-body"'), '#detail-dialog-body must exist in index.html');

  // Inspect invoice INV-1004 via Inspect button click in table row
  const inspectBtns = invTbody.querySelectorAll('[data-inspect-id]');
  assert.ok(inspectBtns.length > 0, 'Inspect buttons must exist in invoices table rows');
  const btn4 = inspectBtns.find((b) => b.getAttribute('data-inspect-id') === 'INV-1004');
  assert.ok(btn4, 'Inspect button for INV-1004 must exist');

  btn4.click();
  const detailDlg = elements.get('dialog-invoice-detail');
  assert.equal(detailDlg.open, true, '#dialog-invoice-detail must open on inspect click');

  const detailBodyHtml = elements.get('detail-dialog-body').innerHTML;
  assert.ok(detailBodyHtml.includes('9-Point Fraud'), 'Detail modal must render 9-Point Fraud checklist header');
  assert.ok(detailBodyHtml.includes('bank_details'), 'Detail modal must render bank_details check');
  assert.ok(detailBodyHtml.includes('three_way_match'), 'Detail modal must render three_way_match check');
  assert.ok(detailBodyHtml.includes('amount_checks'), 'Detail modal must render amount_checks check');
  assert.ok(detailBodyHtml.includes('data-wf="run_checks"'), 'Detail modal must render run_checks action button');

  // Close the detail modal
  elements.get('btn-close-detail').click();
  assert.equal(detailDlg.open, false, '#dialog-invoice-detail must close on close button click');
});

test('19. Suite D: Interactive Dual-Mode Sankey Diagram & Flow Conservation — Lifecycle flow, Supplier flow, edge cases, and SVG rendering', () => {
  const { elements } = getDomHarness();
  const state = VG.createInitialState();

  // Mode 1: Lifecycle Flow
  const life = VG.computeSankeyData(state, { mode: 'lifecycle', metric: 'amount' });
  assert.equal(life.mode, 'lifecycle');
  assert.ok(life.total > 0, 'Total lifecycle volume must be positive');
  assert.equal(life.stages.length, 3);

  // Conservation of flow: input volume equals output volume at every stage transition (± 0.01)
  for (let s = 0; s < 3; s++) {
    const stageSum = Number(life.nodes.filter((n) => n.stage === s).reduce((acc, n) => acc + n.value, 0).toFixed(2));
    assert.ok(
      Math.abs(stageSum - life.total) < 0.02,
      `Stage ${s} total (${stageSum}) must equal total volume (${life.total})`
    );
  }

  // Link stage transition conservation
  const s01Links = life.links.filter((l) => l.source === 'ingested');
  const s01Sum = Number(s01Links.reduce((acc, l) => acc + l.value, 0).toFixed(2));
  assert.ok(Math.abs(s01Sum - life.total) < 0.02, `Links 0->1 sum (${s01Sum}) must equal total (${life.total})`);

  const s12Sum = Number(
    life.links
      .filter((l) => l.source === 'in_audit' || l.source === 'flagged_fraud')
      .reduce((acc, l) => acc + l.value, 0)
      .toFixed(2)
  );
  assert.ok(Math.abs(s12Sum - life.total) < 0.02, `Links 1->2 sum (${s12Sum}) must equal total (${life.total})`);

  // Node conservation for intermediate stage 1 nodes: sum(in) == sum(out) == node.value
  for (const midId of ['in_audit', 'flagged_fraud']) {
    const node = life.nodes.find((n) => n.id === midId);
    if (!node || node.value === 0) continue;
    const inFlow = Number(life.links.filter((l) => l.target === midId).reduce((acc, l) => acc + l.value, 0).toFixed(2));
    const outFlow = Number(life.links.filter((l) => l.source === midId).reduce((acc, l) => acc + l.value, 0).toFixed(2));
    assert.ok(Math.abs(inFlow - node.value) < 0.02, `Node ${midId} inFlow (${inFlow}) must match node value (${node.value})`);
    assert.ok(Math.abs(outFlow - node.value) < 0.02, `Node ${midId} outFlow (${outFlow}) must match node value (${node.value})`);
  }

  // Mode 2: Supplier Financial Flow
  const sup = VG.computeSankeyData(state, { mode: 'supplier', metric: 'amount' });
  assert.equal(sup.mode, 'supplier');
  assert.ok(sup.total > 0, 'Total supplier volume must be positive');
  assert.ok(Math.abs(sup.total - life.total) < 0.02, 'Total volume must match across flow modes');

  // Conservation of flow: Total supplier volume == Total audit outcome == Total payment destination
  for (let s = 0; s < 3; s++) {
    const stageSum = Number(sup.nodes.filter((n) => n.stage === s).reduce((acc, n) => acc + n.value, 0).toFixed(2));
    assert.ok(
      Math.abs(stageSum - sup.total) < 0.02,
      `Supplier stage ${s} sum (${stageSum}) must equal total (${sup.total})`
    );
  }

  // Supplier node conservation: each supplier's outgoing links match supplier total
  const supNodes = sup.nodes.filter((n) => n.stage === 0 && n.value > 0);
  for (const sn of supNodes) {
    const outSum = Number(sup.links.filter((l) => l.source === sn.id).reduce((acc, l) => acc + l.value, 0).toFixed(2));
    assert.ok(Math.abs(outSum - sn.value) < 0.02, `Supplier ${sn.id} out links (${outSum}) must equal value (${sn.value})`);
  }

  // Intermediate audit outcome nodes conservation in supplier mode
  for (const midId of ['audit_approved', 'audit_review', 'audit_flagged']) {
    const node = sup.nodes.find((n) => n.id === midId);
    if (!node || node.value === 0) continue;
    const inFlow = Number(sup.links.filter((l) => l.target === midId).reduce((acc, l) => acc + l.value, 0).toFixed(2));
    const outFlow = Number(sup.links.filter((l) => l.source === midId).reduce((acc, l) => acc + l.value, 0).toFixed(2));
    assert.ok(Math.abs(inFlow - node.value) < 0.02, `Audit node ${midId} inFlow (${inFlow}) must equal node value (${node.value})`);
    assert.ok(Math.abs(outFlow - node.value) < 0.02, `Audit node ${midId} outFlow (${outFlow}) must equal node value (${node.value})`);
  }

  // Edge Cases:
  // 1. Empty invoices array
  const emptyLife = VG.computeSankeyData({ invoices: [] }, { mode: 'lifecycle' });
  assert.equal(emptyLife.total, 0);
  assert.equal(emptyLife.links.length, 0);
  const emptySvg = VG.renderSankeySVG(emptyLife);
  assert.ok(emptySvg.includes('<svg'), 'Empty SVG must contain <svg>');
  assert.ok(!emptySvg.includes('NaN'), 'Empty SVG must not contain NaN');

  // 2. Single invoice
  const singleState = {
    ...state,
    invoices: [
      {
        id: 'INV-SINGLE',
        invoiceNumber: 'INV-S-01',
        supplierId: 'SUP-01',
        supplierName: 'CloudScale Infrastructure GmbH',
        amount: 5000,
        currency: 'EUR',
        status: 'ready_to_pay'
      }
    ]
  };
  const singleLife = VG.computeSankeyData(singleState, { mode: 'lifecycle' });
  assert.equal(singleLife.total, 5000);
  for (let s = 0; s < 3; s++) {
    const sum = Number(singleLife.nodes.filter((n) => n.stage === s).reduce((acc, n) => acc + n.value, 0).toFixed(2));
    assert.equal(sum, 5000, `Single invoice stage ${s} must equal 5000`);
  }

  // 3. 100% fraud edge case
  const fraudState = {
    ...state,
    invoices: [
      { id: 'INV-F1', invoiceNumber: 'F1', supplierId: 'S1', supplierName: 'ScamCo', amount: 1000, currency: 'EUR', status: 'flagged' },
      { id: 'INV-F2', invoiceNumber: 'F2', supplierId: 'S1', supplierName: 'ScamCo', amount: 2000, currency: 'EUR', status: 'rejected' }
    ]
  };
  const fraudLife = VG.computeSankeyData(fraudState, { mode: 'lifecycle' });
  assert.equal(fraudLife.total, 3000);
  const fraudBlocked = fraudLife.nodes.find((n) => n.id === 'blocked_prevented');
  assert.equal(fraudBlocked.value, 3000, '100% fraud must flow entirely to blocked_prevented');

  // 4. Count metric
  const countLife = VG.computeSankeyData(state, { mode: 'lifecycle', metric: 'count' });
  assert.equal(countLife.total, 10);
  assert.equal(countLife.metric, 'count');

  // SVG rendering checks
  const svgDark = VG.renderSankeySVG(life, { width: 920, height: 340, theme: 'dark' });
  assert.ok(svgDark.includes('<svg'), 'SVG markup must contain <svg>');
  assert.ok(svgDark.includes('<path'), 'SVG markup must contain <path> ribbon links');
  assert.ok(svgDark.includes('<rect'), 'SVG markup must contain <rect> node bars');
  assert.ok(svgDark.includes('<text'), 'SVG markup must contain <text> labels');
  assert.ok(svgDark.includes('viewBox="0 0 920 340"'), 'SVG must have valid viewBox');
  assert.ok(!svgDark.includes('NaN'), 'Sankey SVG must not contain NaN');
  assert.ok(!svgDark.includes('width="-'), 'Sankey SVG must not contain negative width');
  assert.ok(!svgDark.includes('height="-'), 'Sankey SVG must not contain negative height');

  const svgLight = VG.renderSankeySVG(life, { width: 920, height: 340, theme: 'light' });
  assert.ok(svgLight.includes('<svg'));
  assert.ok(!svgLight.includes('NaN'));

  // Mode switching in DOM harness updates SVG nodes and links
  const wrapper = elements.get('sankey-diagram-wrapper');
  const btnDept = elements.get('btn-sankey-dept');
  const btnLife = elements.get('btn-sankey-lifecycle');
  if (wrapper && btnDept && btnLife) {
    btnDept.click();
    assert.ok(wrapper.innerHTML.includes('<svg'), 'Sankey wrapper must contain SVG after switching to supplier flow');
    btnLife.click();
    assert.ok(wrapper.innerHTML.includes('<svg'), 'Sankey wrapper must contain SVG after switching back to lifecycle flow');
  }
});

test('20. Suite E: Companion Charts Visual Clarity — at most 2 companion charts on Overview, visual SVG graphics, and Cash-Flow forecast chart in Payments', () => {
  const { html, elements } = getDomHarness();

  // 1. Overview has at most 2 companion charts
  const overviewMatch = html.match(/<section[^>]*id="panel-overview"[^>]*>([\s\S]*?)<\/section>/);
  assert.ok(overviewMatch, '#panel-overview must exist in index.html');
  const chartCards = overviewMatch[1].match(/class="card chart-card"[^>]*id="chart-[^"]+"/g) || [];
  assert.ok(chartCards.length <= 2, `Overview companion charts (${chartCards.length}) must be <= 2`);
  assert.equal(chartCards.length, 2, 'Overview must have exactly 2 companion charts');
  assert.ok(overviewMatch[1].includes('id="chart-monthly-trends"'), '#chart-monthly-trends must exist');
  assert.ok(overviewMatch[1].includes('id="chart-supplier-trends"'), '#chart-supplier-trends must exist');

  // 2. Charts render visual SVG graphics with non-zero dimensions and legible labels
  const monthlyChart = elements.get('chart-monthly-trends');
  assert.ok(monthlyChart, '#chart-monthly-trends must exist in DOM');
  const monthlySvg = monthlyChart.innerHTML;
  assert.ok(monthlySvg.includes('<svg'), '#chart-monthly-trends must render <svg>');
  assert.ok(monthlySvg.includes('<rect'), '#chart-monthly-trends must render visual <rect> bars');
  assert.ok(monthlySvg.includes('<text'), '#chart-monthly-trends must render <text> labels');
  assert.ok(!monthlySvg.includes('NaN'), '#chart-monthly-trends SVG must not contain NaN');

  const supplierChart = elements.get('chart-supplier-trends');
  assert.ok(supplierChart, '#chart-supplier-trends must exist in DOM');
  const supplierSvg = supplierChart.innerHTML;
  assert.ok(supplierSvg.includes('<svg'), '#chart-supplier-trends must render <svg>');
  assert.ok(supplierSvg.includes('<rect'), '#chart-supplier-trends must render visual <rect> bars');
  assert.ok(supplierSvg.includes('<text'), '#chart-supplier-trends must render <text> labels');
  assert.ok(!supplierSvg.includes('NaN'), '#chart-supplier-trends SVG must not contain NaN');

  // 3. Payments view includes visual cash-flow forecast chart
  const paymentsMatch = html.match(/<section[^>]*id="panel-payments"[^>]*>([\s\S]*?)<\/section>/);
  assert.ok(paymentsMatch, '#panel-payments must exist in index.html');
  assert.ok(paymentsMatch[1].includes('id="chart-cashflow-container"'), '#chart-cashflow-container must exist');
  assert.ok(paymentsMatch[1].includes('id="chart-cashflow-svg"'), '#chart-cashflow-svg must exist');

  const cashflowEl = elements.get('chart-cashflow-svg');
  assert.ok(cashflowEl, '#chart-cashflow-svg must exist in DOM');
  const cashflowSvg = cashflowEl.innerHTML;
  assert.ok(cashflowSvg.includes('<rect'), '#chart-cashflow-svg must render forecast bucket bars');
  assert.ok(cashflowSvg.includes('<text'), '#chart-cashflow-svg must render bucket labels');
  assert.ok(cashflowSvg.includes('Overdue') || cashflowSvg.includes('Next 7 Days'), 'Cash-flow forecast must display aging buckets');
  assert.ok(!cashflowSvg.includes('NaN'), '#chart-cashflow-svg SVG must not contain NaN');
});

test('21. Suite F: Light & Dark Theme Adaptability — #btn-theme-toggle switches light/dark and SVG charts adapt', () => {
  const { elements } = getDomHarness();
  const css = fs.readFileSync(path.join(__dirname, 'styles.css'), 'utf8');

  // 1. CSS theme token verification
  assert.ok(css.includes(':root'), 'styles.css must declare :root theme variables');
  assert.ok(css.includes('[data-theme="dark"]'), 'styles.css must declare [data-theme="dark"] theme variables');
  assert.ok(css.includes('--sankey-link-op'), 'styles.css must define --sankey-link-op variable');
  assert.ok(css.includes('--chart-grid'), 'styles.css must define --chart-grid variable');

  // 2. #btn-theme-toggle toggles between light and dark
  const themeBtn = elements.get('btn-theme-toggle');
  assert.ok(themeBtn, '#btn-theme-toggle must exist in DOM');
  const docEl = globalThis.document?.documentElement;
  assert.ok(docEl, 'document.documentElement must exist');

  const initialTheme = docEl.getAttribute('data-theme') || 'dark';
  const expectedNext = initialTheme === 'light' ? 'dark' : 'light';

  themeBtn.click();
  assert.equal(docEl.getAttribute('data-theme'), expectedNext, `Theme must toggle to ${expectedNext}`);

  themeBtn.click();
  assert.equal(docEl.getAttribute('data-theme'), initialTheme, `Theme must toggle back to ${initialTheme}`);

  // 3. SVG charts and Sankey adapt cleanly to both themes
  const state = VG.createInitialState();
  const data = VG.computeSankeyData(state);

  const darkSvg = VG.renderSankeySVG(data, { theme: 'dark', width: 900, height: 320 });
  assert.ok(darkSvg.includes('<svg'));
  assert.ok(!darkSvg.includes('NaN'));

  const lightSvg = VG.renderSankeySVG(data, { theme: 'light', width: 900, height: 320 });
  assert.ok(lightSvg.includes('<svg'));
  assert.ok(!lightSvg.includes('NaN'));
});

test('22. Suite G: Full Regression & Integration Safety — E2E workflow: Ingest -> Audit -> Approve -> Schedule -> SEPA Batch -> Reconcile -> Flow Conservation', async () => {
  const state = VG.createInitialState();

  // Baseline initial flow conservation
  const initialLife = VG.computeSankeyData(state, { mode: 'lifecycle' });
  const initialTotal = initialLife.total;
  assert.ok(initialTotal > 0);

  // 1. Ingest new invoice
  const newInv = VG.ingestInvoice(
    state,
    {
      invoiceNumber: 'E2E-2026-901',
      supplierId: 'SUP-01',
      supplierName: 'CloudScale Infrastructure GmbH',
      vatNumber: 'DE812345678',
      iban: 'DE89370400440532013000',
      amount: 4500,
      currency: 'EUR',
      poNumber: 'PO-E2E-901',
      poAmount: 4500,
      grnNumber: 'GRN-E2E-901',
      grnStatus: 'matched',
      senderEmail: 'billing@cloudscale.de',
      department: 'Engineering',
      issueDate: '2026-10-10',
      dueDate: '2026-10-25',
      autoRunChecks: false
    },
    'api'
  );
  assert.equal(newInv.status, 'received');
  assert.equal(state.invoices.length, 11);

  // Flow after ingestion
  const postIngestLife = VG.computeSankeyData(state, { mode: 'lifecycle' });
  assert.equal(Number((postIngestLife.total - initialTotal).toFixed(2)), 4500);
  for (let s = 0; s < 3; s++) {
    const sum = Number(postIngestLife.nodes.filter((n) => n.stage === s).reduce((acc, n) => acc + n.value, 0).toFixed(2));
    assert.ok(Math.abs(sum - postIngestLife.total) < 0.02, `Post-ingest stage ${s} flow conservation`);
  }

  // 2. Run 9-point checks
  const auditor = state.users.find((u) => u.role === 'auditor');
  VG.performWorkflowAction(state, newInv.id, 'run_checks', {}, auditor);
  assert.equal(newInv.checklist.length, 9);
  assert.equal(newInv.riskLevel, 'low');
  assert.equal(newInv.status, 'pending_verification');

  const postAuditLife = VG.computeSankeyData(state, { mode: 'lifecycle' });
  assert.ok(Math.abs(postAuditLife.total - postIngestLife.total) < 0.02);
  for (let s = 0; s < 3; s++) {
    const sum = Number(postAuditLife.nodes.filter((n) => n.stage === s).reduce((acc, n) => acc + n.value, 0).toFixed(2));
    assert.ok(Math.abs(sum - postAuditLife.total) < 0.02, `Post-audit stage ${s} flow conservation`);
  }

  // 3. Approve invoice
  const approver = state.users.find((u) => u.id === 'USR-APPROVER-1');
  VG.performWorkflowAction(state, newInv.id, 'approve', { note: 'Verified genuine' }, approver);
  assert.ok(
    newInv.status === 'verified_approved' || newInv.status === 'ready_to_pay',
    `Expected verified_approved or ready_to_pay, got ${newInv.status}`
  );

  const postApproveLife = VG.computeSankeyData(state, { mode: 'lifecycle' });
  for (let s = 0; s < 3; s++) {
    const sum = Number(postApproveLife.nodes.filter((n) => n.stage === s).reduce((acc, n) => acc + n.value, 0).toFixed(2));
    assert.ok(Math.abs(sum - postApproveLife.total) < 0.02, `Post-approve stage ${s} flow conservation`);
  }

  // 4. Schedule payment
  const payer = state.users.find((u) => u.id === 'USR-PAYER-1');
  VG.scheduleInvoicePayment(state, newInv.id, { scheduledDate: '2026-10-20', useEarlyDiscount: false }, payer);
  assert.equal(newInv.status, 'scheduled');

  const postScheduleLife = VG.computeSankeyData(state, { mode: 'lifecycle' });
  for (let s = 0; s < 3; s++) {
    const sum = Number(postScheduleLife.nodes.filter((n) => n.stage === s).reduce((acc, n) => acc + n.value, 0).toFixed(2));
    assert.ok(Math.abs(sum - postScheduleLife.total) < 0.02, `Post-schedule stage ${s} flow conservation`);
  }

  // 5. Generate SEPA XML batch
  const batch = VG.createPaymentBatch(state, [newInv.id], { executionDate: '2026-10-15' }, payer);
  assert.equal(batch.invoiceCount, 1);
  assert.ok(batch.sepaXml.includes('pain.001.001.03'));
  assert.ok(batch.sepaXml.includes('E2E-2026-901'));

  // 6. Reconcile payment batch
  VG.reconcilePaymentBatch(state, batch.id, payer);
  assert.equal(newInv.status, 'paid');
  assert.equal(newInv.reconciled, true);

  // 7. Verify updated Sankey flow and conservation
  const finalLife = VG.computeSankeyData(state, { mode: 'lifecycle' });
  assert.equal(finalLife.total, postIngestLife.total);

  // Stage conservation
  for (let s = 0; s < 3; s++) {
    const sum = Number(finalLife.nodes.filter((n) => n.stage === s).reduce((acc, n) => acc + n.value, 0).toFixed(2));
    assert.ok(Math.abs(sum - finalLife.total) < 0.02, `Final stage ${s} flow conservation`);
  }

  // Node conservation for intermediate nodes
  for (const midId of ['in_audit', 'flagged_fraud']) {
    const node = finalLife.nodes.find((n) => n.id === midId);
    if (!node || node.value === 0) continue;
    const inFlow = Number(finalLife.links.filter((l) => l.target === midId).reduce((acc, l) => acc + l.value, 0).toFixed(2));
    const outFlow = Number(finalLife.links.filter((l) => l.source === midId).reduce((acc, l) => acc + l.value, 0).toFixed(2));
    assert.ok(Math.abs(inFlow - node.value) < 0.02);
    assert.ok(Math.abs(outFlow - node.value) < 0.02);
  }

  // Scheduled / Paid node contains newly paid invoice
  const paidNode = finalLife.nodes.find((n) => n.id === 'scheduled_paid');
  assert.ok(paidNode.invoiceIds.includes(newInv.id), 'scheduled_paid node must include new invoice ID');

  // Supplier mode flow verification
  const finalSup = VG.computeSankeyData(state, { mode: 'supplier' });
  for (let s = 0; s < 3; s++) {
    const sum = Number(finalSup.nodes.filter((n) => n.stage === s).reduce((acc, n) => acc + n.value, 0).toFixed(2));
    assert.ok(Math.abs(sum - finalSup.total) < 0.02, `Final supplier stage ${s} flow conservation`);
  }
  const destPaid = finalSup.nodes.find((n) => n.id === 'dest_paid');
  assert.ok(destPaid.invoiceIds.includes(newInv.id), 'dest_paid node must include new invoice ID');

  // SVG rendering of final state
  const finalSvg = VG.renderSankeySVG(finalLife, { width: 920, height: 340, theme: 'dark' });
  assert.ok(finalSvg.includes('<svg'));
  assert.ok(finalSvg.includes('<path'));
  assert.ok(finalSvg.includes('<rect'));
  assert.ok(!finalSvg.includes('NaN'));

  // Audit log cryptographic chain integrity
  const integrity = VG.verifyAuditLogIntegrity(state.auditLog);
  assert.equal(integrity.valid, true, 'Cryptographic hash chain must be valid across all actions');
  assert.ok(integrity.count >= 6, 'Audit chain must track all lifecycle transitions');
});


