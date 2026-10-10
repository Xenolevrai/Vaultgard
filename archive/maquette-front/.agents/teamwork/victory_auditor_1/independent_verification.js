const http = require('http');
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const crypto = require('crypto');

// Load target modules from project root
const projectRoot = path.resolve(__dirname, '../../..');
const VG = require(path.join(projectRoot, 'core.js'));
const htmlContent = fs.readFileSync(path.join(projectRoot, 'index.html'), 'utf8');
const cssContent = fs.readFileSync(path.join(projectRoot, 'styles.css'), 'utf8');

console.log('================================================================');
console.log('VICTORY AUDITOR: INDEPENDENT VERIFICATION HARNESS');
console.log('================================================================\n');

let assertionCount = 0;
function check(cond, msg) {
  assertionCount++;
  if (!cond) {
    throw new Error(`VICTORY AUDIT FAILED: ${msg}`);
  }
}

// -----------------------------------------------------------------------------
// CHECK 1: DOM & LAYOUT CONSTRAINTS IN index.html
// -----------------------------------------------------------------------------
console.log('▶ Check 1: Primary Navigation & Layout Anti-Clutter...');

// 1.1 Nav tabs
const navMatch = htmlContent.match(/<nav class="nav-tabs"[^>]*>([\s\S]*?)<\/nav>/);
check(navMatch !== null, '<nav class="nav-tabs"> must exist');
const tabMatches = Array.from(navMatch[1].matchAll(/data-tab="([^"]+)"/g), m => m[1]);
console.log('  Primary nav tabs:', tabMatches);
check(tabMatches.length === 3, `Expected exactly 3 primary tabs, found ${tabMatches.length}`);
check(tabMatches.includes('overview') && tabMatches.includes('invoices') && tabMatches.includes('payments'), 'Expected overview, invoices, payments tabs');

// 1.2 Invoices table columns
const invTheadMatch = htmlContent.match(/<table[^>]*id="invoices-table"[^>]*>[\s\S]*?<thead>([\s\S]*?)<\/thead>/);
check(invTheadMatch !== null, '#invoices-table <thead> must exist');
const invThs = (invTheadMatch[1].match(/<th\b/g) || []).length;
console.log('  Invoices table columns:', invThs);
check(invThs <= 7, `Invoices table columns (${invThs}) must be <= 7`);
check(invThs === 7, `Invoices table columns (${invThs}) must be exactly 7`);

// 1.3 Payments table columns
const payTheadMatch = htmlContent.match(/<table[^>]*id="payments-table"[^>]*>[\s\S]*?<thead>([\s\S]*?)<\/thead>/);
check(payTheadMatch !== null, '#payments-table <thead> must exist');
const payThs = (payTheadMatch[1].match(/<th\b/g) || []).length;
console.log('  Payments table columns:', payThs);
check(payThs <= 6, `Payments table columns (${payThs}) must be <= 6`);
check(payThs === 6, `Payments table columns (${payThs}) must be exactly 6`);

// 1.4 Overview companion charts
const overviewSection = htmlContent.match(/<section[^>]*id="panel-overview"[^>]*>([\s\S]*?)<\/section>/);
check(overviewSection !== null, '#panel-overview section must exist');
const chartCards = overviewSection[1].match(/class="card chart-card"[^>]*id="chart-[^"]+"/g) || [];
console.log('  Overview companion charts count:', chartCards.length);
check(chartCards.length <= 2, `Overview companion charts (${chartCards.length}) must be <= 2`);
check(chartCards.length === 2, `Overview companion charts (${chartCards.length}) must be exactly 2`);

// 1.5 10-status grid inside collapsible details
const detailsBlocks = overviewSection[1].match(/<details\b[^>]*>([\s\S]*?)<\/details>/g) || [];
const hasStatusGridInDetails = detailsBlocks.some(d => d.includes('id="kpi-status-grid"'));
check(hasStatusGridInDetails, '10-status grid must be inside on-demand <details> element');

// 1.6 On-demand dialogs
const requiredDialogs = ['dialog-invoice-detail', 'dialog-ingest', 'dialog-alerts', 'dialog-suppliers', 'dialog-governance'];
for (const dlgId of requiredDialogs) {
  check(htmlContent.includes(`id="${dlgId}"`), `Required on-demand dialog #${dlgId} must exist in index.html`);
}
console.log('  ✔ Check 1 Passed: Navigation, layout limits, and on-demand drawers verified.\n');

// -----------------------------------------------------------------------------
// CHECK 2: THEME CSS RESILIENCE
// -----------------------------------------------------------------------------
console.log('▶ Check 2: Theme Tokens in styles.css...');
check(cssContent.includes(':root {'), 'styles.css must have :root selector');
check(cssContent.includes('[data-theme="dark"]'), 'styles.css must have [data-theme="dark"] selector');
const requiredThemeTokens = ['--shell-bg', '--bg', '--text', '--border', '--teal', '--danger', '--warning'];
for (const token of requiredThemeTokens) {
  check(cssContent.includes(token), `Theme token ${token} must be defined in styles.css`);
}
console.log('  ✔ Check 2 Passed: Light and dark theme tokens verified.\n');

// -----------------------------------------------------------------------------
// CHECK 3: SANKEY FLOW ENGINE FUZZER (1,000 SYNTHETIC INVOICES)
// -----------------------------------------------------------------------------
console.log('▶ Check 3: Independent Sankey Flow Engine Stress Test...');
const STATUSES = VG.ALL_STATUS_KEYS;
const CURRENCIES = ['EUR', 'USD', 'GBP', 'CHF'];
const DEPARTMENTS = ['IT', 'Security', 'Operations', 'Finance', 'Logistics'];

const syntheticInvoices = [];
for (let i = 1; i <= 1000; i++) {
  syntheticInvoices.push({
    id: `FUZZ-${i}`,
    invoiceNumber: `INV-FUZZ-${i}`,
    supplierId: `SUP-${(i % 12) + 1}`,
    supplierName: `Supplier ${(i % 12) + 1} Corp`,
    department: DEPARTMENTS[i % DEPARTMENTS.length],
    amount: Number((10 + (i * 37.13) % 45000).toFixed(2)),
    currency: CURRENCIES[i % CURRENCIES.length],
    status: STATUSES[i % STATUSES.length],
    dueDate: '2026-11-20'
  });
}

const fuzzState = { invoices: syntheticInvoices, settings: { baseCurrency: 'EUR' } };

const testModes = [
  { mode: 'lifecycle', metric: 'amount' },
  { mode: 'lifecycle', metric: 'count' },
  { mode: 'supplier', metric: 'amount' },
  { mode: 'supplier', metric: 'count' },
  { mode: 'department', metric: 'amount' },
  { mode: 'department', metric: 'count' }
];

for (const tm of testModes) {
  const data = VG.computeSankeyData(fuzzState, tm);
  check(typeof data.total === 'number' && data.total > 0, `Total must be positive number for ${tm.mode}/${tm.metric}`);
  check(Array.isArray(data.stages) && data.stages.length >= 3, `Expected at least 3 stages for ${tm.mode}`);

  // Test conservation across each stage
  for (let s = 0; s < data.stages.length; s++) {
    const stageNodes = data.nodes.filter(n => n.stage === s);
    const stageSum = Number(stageNodes.reduce((sum, n) => sum + n.value, 0).toFixed(2));
    const diff = Math.abs(stageSum - data.total);
    check(diff <= 0.02, `Stage ${s} (${data.stages[s]}) sum ${stageSum} != total ${data.total} (diff: ${diff})`);
  }

  // Test intermediate node flow conservation
  for (let s = 1; s < data.stages.length - 1; s++) {
    const midNodes = data.nodes.filter(n => n.stage === s && n.value > 0);
    for (const node of midNodes) {
      const inSum = Number(data.links.filter(l => l.target === node.id).reduce((sum, l) => sum + l.value, 0).toFixed(2));
      const outSum = Number(data.links.filter(l => l.source === node.id).reduce((sum, l) => sum + l.value, 0).toFixed(2));
      check(Math.abs(inSum - node.value) <= 0.02, `Node ${node.id} inSum ${inSum} != value ${node.value}`);
      check(Math.abs(outSum - node.value) <= 0.02, `Node ${node.id} outSum ${outSum} != value ${node.value}`);
    }
  }

  // Test SVG rendering
  for (const theme of ['light', 'dark']) {
    const svg = VG.renderSankeySVG(data, { theme, width: 960, height: 420 });
    check(svg.startsWith('<svg') && svg.endsWith('</svg>'), 'Rendered SVG must be well-formed');
    check(!svg.includes('NaN'), 'SVG must never contain NaN');
    check(!svg.includes('undefined'), 'SVG must never contain undefined');
    check(!svg.includes('width="-'), 'SVG must not contain negative width');
    check(!svg.includes('height="-'), 'SVG must not contain negative height');
  }
}
console.log('  ✔ Check 3 Passed: 1,000 synthetic invoices fuzzed across all modes with strict conservation.\n');

// -----------------------------------------------------------------------------
// CHECK 4: CORE DOMAIN CAPABILITIES & CRYPTOGRAPHIC HASH CHAIN
// -----------------------------------------------------------------------------
console.log('▶ Check 4: Domain Fraud Checks, SoD, SEPA XML & Hash Chain...');

const seededState = VG.createInitialState();
check(Array.isArray(seededState.invoices) && seededState.invoices.length === 10, 'Seeded state must have 10 invoices');

// 4.1 Fraud checks: verify 9-point checks detect high risk
const scamInv = {
  id: 'SCAM-99',
  invoiceNumber: 'SCAM-99',
  supplierId: 'SUP-NEW',
  supplierName: 'Phishing Vendor Ltd',
  amount: 85000,
  currency: 'EUR',
  vatNumber: 'INVALID_VAT',
  iban: 'INVALID_IBAN',
  status: 'received',
  poNumber: 'PO-FAKE',
  issueDate: '2026-10-10',
  dueDate: '2026-10-11',
  senderEmail: 'scam@phish.ru',
  sanctionsHit: true
};
const auditRes = VG.runAuditChecks(scamInv, seededState);
check(auditRes.riskLevel === 'high', 'Scam invoice must be flagged as high risk');
check(auditRes.riskReasons.length >= 2, 'Scam invoice must have multiple fraud detection reasons');

// 4.2 Segregation of Duties
const testInv = seededState.invoices.find(i => i.status === 'ready_to_pay') || seededState.invoices[0];
const approverUser = { id: 'U-1', name: 'Auditor One', role: 'auditor' };
testInv.approvedBy = 'Auditor One';
const sodSelf = VG.verifySoD(testInv, approverUser);
check(sodSelf.allowed === false, 'Approver cannot pay the same invoice (SoD violation)');

// 4.3 SEPA XML generation
const payableInvs = seededState.invoices.slice(0, 2);
const batch = VG.createPaymentBatch(payableInvs, 'Batch Test', { name: 'Treasurer' });
const sepaXml = VG.generateSepaXml(batch, { name: 'Vaultgard Corp', iban: 'DE89370400440532013000', bic: 'DBEUMM21' });
check(typeof sepaXml === 'string' && sepaXml.includes('<?xml') && sepaXml.includes('pain.001.001.03'), 'SEPA XML must be pain.001.001.03 format');

// 4.4 Cryptographic Audit Trail Hash Chain
const integrity = VG.verifyAuditLogIntegrity(seededState);
check(integrity.valid === true, 'Seeded audit trail hash chain must be cryptographically valid');

console.log('  ✔ Check 4 Passed: Fraud checks, SoD, SEPA XML and SHA-256 audit chain verified.\n');

// -----------------------------------------------------------------------------
// CHECK 5: HTTP SERVER LIVE EXECUTION (/api/kpis, /api/invoices, /api/invoices/ingest)
// -----------------------------------------------------------------------------
console.log('▶ Check 5: Live Zero-Dependency HTTP Server Execution...');

const serverModule = require(path.join(projectRoot, 'server.js'));
const server = http.createServer(serverModule.requestHandler);

async function runServerChecks() {
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  console.log(`  Server listening on ephemeral port ${port}`);

  function fetchUrl(urlPath, method = 'GET', body = null) {
    return new Promise((resolve, reject) => {
      const req = http.request({
        host: '127.0.0.1',
        port,
        path: urlPath,
        method,
        headers: body ? { 'Content-Type': 'application/json' } : {}
      }, (res) => {
        let raw = '';
        res.on('data', chunk => { raw += chunk; });
        res.on('end', () => {
          resolve({ status: res.statusCode, headers: res.headers, data: raw });
        });
      });
      req.on('error', reject);
      if (body) req.write(typeof body === 'string' ? body : JSON.stringify(body));
      req.end();
    });
  }

  // 5.1 Static root
  const rootRes = await fetchUrl('/');
  check(rootRes.status === 200, 'GET / must return 200');
  check(rootRes.data.includes('Vaultgard'), 'GET / must return HTML containing Vaultgard');

  // 5.2 /api/kpis
  const kpisRes = await fetchUrl('/api/kpis');
  check(kpisRes.status === 200, 'GET /api/kpis must return 200');
  const kpisData = JSON.parse(kpisRes.data);
  check(typeof kpisData.totalInvoices === 'number', 'KPIs must return totalInvoices');
  check(kpisData.totalInvoices === 10, `Expected 10 totalInvoices, got ${kpisData.totalInvoices}`);

  // 5.3 /api/invoices
  const invsRes = await fetchUrl('/api/invoices');
  check(invsRes.status === 200, 'GET /api/invoices must return 200');
  const invsData = JSON.parse(invsRes.data);
  check(Array.isArray(invsData) && invsData.length === 10, 'Expected 10 invoices from /api/invoices');

  // 5.4 /api/invoices/ingest
  const ingestPayload = {
    invoiceNumber: 'INGEST-INDEP-001',
    supplierName: 'Independent Auditor Vendor',
    amount: 12500,
    currency: 'EUR',
    dueDate: '2026-11-30'
  };
  const ingestRes = await fetchUrl('/api/invoices/ingest', 'POST', ingestPayload);
  check(ingestRes.status === 201, `POST /api/invoices/ingest must return 201, got ${ingestRes.status}`);
  const ingestedInv = JSON.parse(ingestRes.data);
  check(ingestedInv.invoiceNumber === 'INGEST-INDEP-001', 'Ingested invoice must match payload');

  // Close server
  await new Promise((resolve) => server.close(resolve));
  console.log('  ✔ Check 5 Passed: HTTP server verified live on ephemeral port.\n');
}

runServerChecks().then(() => {
  console.log('================================================================');
  console.log(`ALL 5 INDEPENDENT AUDIT PHASES PASSED CLEANLY!`);
  console.log(`Total independent assertions: ${assertionCount}`);
  console.log('FINAL AUDIT RESULT: VICTORY CONFIRMED');
  console.log('================================================================');
  process.exit(0);
}).catch((err) => {
  console.error('\n❌ INDEPENDENT AUDIT FAILED:', err);
  process.exit(1);
});
