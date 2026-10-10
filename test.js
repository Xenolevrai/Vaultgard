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

test('14. Frontend DOM & Controller Integrity — every getElementById in app.js exists in index.html', () => {
  const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
  const appJs = fs.readFileSync(path.join(__dirname, 'app.js'), 'utf8');

  const htmlIds = new Set(
    Array.from(html.matchAll(/\bid="([^"]+)"/g), (m) => m[1])
  );
  // Dynamic IDs injected by app.js templates into modals/cards before querying them
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

  // Execute app.js inside a lightweight DOM harness to verify initial render & event handlers
  const elements = new Map();
  function makeEl(id = '') {
    const listeners = {};
    const el = {
      id,
      value: '',
      checked: false,
      open: false,
      _html: '',
      textContent: '',
      className: '',
      parentNode: {},
      attributes: { 'data-theme': 'dark', ' data-tab': 'overview' },
      classList: { toggle() {} },
      get innerHTML() {
        return this._html;
      },
      set innerHTML(val) {
        this._html = String(val);
        // Auto-register any dynamically injected IDs
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
          fn({ target: el, preventDefault() {}, ...eventObj });
        }
      },
      click() {
        this.trigger('click');
      },
      getAttribute(k) {
        return this.attributes[k] || '';
      },
      setAttribute(k, v) {
        this.attributes[k] = String(v);
      },
      querySelectorAll() {
        return [];
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
    elements.set(id, makeEl(id));
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
    querySelectorAll() {
      return [];
    },
    createElement(tag) {
      return makeEl(tag);
    }
  };

  // Run app.js controller
  require('./app.js');

  // Verify KPI cards, status grid, invoices table, payable queue, suppliers, alerts, and audit log rendered
  assert.ok(elements.get('kpi-top-cards').innerHTML.includes('Ready to Pay'));
  assert.ok(elements.get('kpi-status-grid').innerHTML.includes('Received / New'));
  assert.ok(elements.get('invoices-tbody').innerHTML.includes('CS-2026-091'));
  assert.ok(elements.get('payable-tbody').innerHTML.includes('NCS-2026-390'));
  assert.ok(elements.get('suppliers-grid').innerHTML.includes('CloudScale Infrastructure GmbH'));
  assert.ok(elements.get('alerts-list').innerHTML.includes('SLA Breach'));
  assert.ok(elements.get('audit-log-tbody').innerHTML.includes('SYSTEM_INIT'));
  assert.ok(elements.get('analytics-summary').innerHTML.includes('Verification Turnaround Time by Supplier'));
  assert.ok(elements.get('analytics-summary').innerHTML.includes('Top Suppliers by Volume'));

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

