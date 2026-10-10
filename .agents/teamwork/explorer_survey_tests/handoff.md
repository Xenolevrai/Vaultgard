# Automated Test Suite Survey & Redesign Test Architecture Report

**Agent**: Explorer Test Suite Survey  
**Working Directory**: `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/.agents/teamwork/explorer_survey_tests/`  
**Target Project**: `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/`  
**Date**: 2026-10-10  

---

## 1. Observation

### 1.1 Environment, Tooling & Dependency Architecture
- **Configuration File**: `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/package.json`
  ```json
  {
    "name": "vaultgard-dashboard",
    "version": "1.0.0",
    "description": "Invoice Audit & Payment Dashboard with 9-Point Fraud Detection, 3-Way Match, Segregation of Duties, and SEPA Batch Execution",
    "main": "core.js",
    "scripts": {
      "start": "node server.js",
      "test": "node --test test.js"
    }
  }
  ```
- **Dependencies**: Exactly 0 production dependencies and 0 `devDependencies`. There is no `node_modules` directory in `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/`.
- **Node Runtime**: Node.js `v26.7.0` (confirmed via `node -v`).
- **Test Framework**: Node.js standard built-in test runner `node:test` and strict assertions `node:assert/strict` (imported in `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/test.js`, lines 1–2):
  ```javascript
  const test = require('node:test');
  const assert = require('node:assert/strict');
  ```
- **DOM Emulation**: Custom lightweight in-memory mock harness in `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/test.js` (lines 394–480). It mocks `globalThis.window`, `globalThis.document`, `globalThis.Vaultgard`, and `globalThis.vgStorage` without third-party dependencies (no `jsdom`, no `happy-dom`, no browser automation like Puppeteer/Playwright):
  ```javascript
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
      get innerHTML() { return this._html; },
      set innerHTML(val) {
        this._html = String(val);
        for (const m of this._html.matchAll(/\bid="([^"]+)"/g)) {
          if (!elements.has(m[1])) elements.set(m[1], makeEl(m[1]));
        }
      },
      addEventListener(evt, fn) { listeners[evt] = listeners[evt] || []; listeners[evt].push(fn); },
      trigger(evt, eventObj = {}) { for (const fn of listeners[evt] || []) { fn({ target: el, preventDefault() {}, ...eventObj }); } },
      click() { this.trigger('click'); },
      getAttribute(k) { return this.attributes[k] || ''; },
      setAttribute(k, v) { this.attributes[k] = String(v); },
      querySelectorAll() { return []; },
      showModal() { this.open = true; },
      close() { this.open = false; },
      appendChild() {},
      remove() {}
    };
    return el;
  }
  ```

### 1.2 Baseline Execution Status and Timings
Execution of `npm test` (`node --test test.js`) in `/Users/hugobefort/dev/Secure_Horizon/Vaultgard` yielded:
```text
> vaultgard-dashboard@1.0.0 test
> node --test test.js

✔ 1. Invoice Status Model — all 10 required statuses exist and are seeded (12.4375ms)
✔ 2. Main Overview KPIs — status totals, ready-to-pay buckets, oldest pending, overdue, and multi-currency (1.37675ms)
✔ 3. Invoice List, Search, Filtering, Sorting & CSV Export (including edge cases) (1.2635ms)
✔ 4. Audit and Fraud Checks — all 9 checks detect fraud and edge cases (0.532ms)
✔ 5 & 6. Workflow Actions, RBAC, Phone Callback Verification, and Multi-Level Approvals (0.925833ms)
✔ 7 & 10. Payment Blocking Rules, Segregation of Duties (SoD), Partial Payments, Credit Notes & SEPA XML (2.440583ms)
✔ 8, 9, 11, 12, 13. Alerts, Audit Chain Integrity, OCR Ingestion & REST API Server (2.492291ms)
✔ 14. Frontend DOM & Controller Integrity — every getElementById in app.js exists in index.html (5.824667ms)
✔ 15. Regression Suite — OCR multiline & thousand-separator parsing, Analytics currency consistency, Discount/CreditNote math, RBAC scope, and Batch deduplication (1.31175ms)
ℹ tests 9
ℹ suites 0
ℹ pass 9
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 4288.985709
```
- Total test count: 9 tests.
- Status: 9 passed, 0 failed, 0 skipped, 0 cancelled.
- Pure assertion execution time across all 9 tests: ~28.6ms. Total process duration: ~4.29s (startup, module loading, static file checks).

### 1.3 Detailed Catalog of Existing Test Cases
The 9 tests in `test.js` cover:
1. **Test 1 (`test.js:8-28`)**: `VG.ALL_STATUS_KEYS` matches 10 lifecycle statuses (`received`, `pending_verification`, `under_review`, `flagged`, `rejected`, `verified_approved`, `ready_to_pay`, `scheduled`, `paid`, `on_hold`). Validates `VG.createInitialState()` seeds at least 1 invoice per status.
2. **Test 2 (`test.js:30-62`)**: `VG.computeKPIs(state, '2026-10-10T12:00:00Z')` status counts, `pendingVerification` queue (count 3, oldest item `INV-1002`, age >= 120h), `flagged` metrics (amount at risk €9,850, scam prevented €49,500, money saved €59,350), `overdue` (unpaid invoice `INV-1010`, excluding rejected `INV-1005`), and EUR to USD FX conversion.
3. **Test 3 (`test.js:64-103`)**: `VG.queryInvoices` filters (PO number `PO-2026-412`, risk level `high`, amount range 5000–10000, sort by amount descending) and `VG.exportInvoicesCSV` RFC 4180 escaping (quotes and commas).
4. **Test 4 (`test.js:105-140`)**: `VG.runAuditChecks` on `INV-1004` (fails 5 checks: `bank_details`, `three_way_match`, `amount_checks`, `document_checks`, `email_sender`; risk >= 65), duplicate detection check, zero/negative amount rejection.
5. **Test 5 & 6 (`test.js:142-204`)**: RBAC permissions (`viewer` and `auditor` blocked from approving); `verify_callback` on `INV-1010` (clears bank failure); 2-tier approval workflow on `INV-1003` (€24,500 threshold: first approval keeps `under_review`, duplicate approval rejected, second approval advances to `verified_approved`); `@mentions` regex parsing.
6. **Test 7 & 10 (`test.js:206-268`)**: `VG.canPayInvoice` payment blocking rules; Segregation of Duties (SoD: approver `USR-APPROVER-1` cannot pay `INV-1007` even with admin role); early payment discount scheduling (2% on €9,200 = €184); credit note + partial payment + reconciliation lifecycle; SEPA XML ISO 20022 `pain.001.001.03` generation; supplier blacklisting blocks payment.
7. **Test 8, 9, 11, 12, 13 (`test.js:270-353`)**: `VG.computeAlerts` (4 alert types); OCR ingestion spoof auto-flagging; SHA-256 audit log hash chain validation (`VG.verifyAuditLogIntegrity`); in-memory REST API tests via `createServer(state).handleRequest`: `GET /api/kpis` (200), `GET /api/invoices?status=flagged` (200), `POST /api/invoices/ingest` (201), `GET /` (200), and path traversal protection `GET /../../etc/passwd` (404).
8. **Test 14 (`test.js:355-502`)**: Frontend DOM and controller integrity:
   - Static regex check: Every `document.getElementById(...)` in `app.js` must exist in `index.html` or `dynamicIds` (at least 30 IDs required).
   - Mock DOM controller execution: executes `require('./app.js')`.
   - InnerHTML checks: `kpi-top-cards` ('Ready to Pay'), `kpi-status-grid` ('Received / New'), `invoices-tbody` ('CS-2026-091'), `payable-tbody` ('NCS-2026-390'), `suppliers-grid` ('CloudScale Infrastructure GmbH'), `alerts-list` ('SLA Breach'), `audit-log-tbody` ('SYSTEM_INIT'), and `analytics-summary` ('Verification Turnaround Time by Supplier', 'Top Suppliers by Volume').
   - Button interactions: `btn-save-view` (localStorage persistence), `btn-theme-toggle`, `btn-toggle-sidebar`.
9. **Test 15 (`test.js:504-631`)**: Regressions: multiline OCR edge cases; initial pending checklist state on ingested invoices; currency conversion consistency in `computeAnalytics`; early discount idempotency; credit note blocking on fraud; RBAC department scoping; SEPA batch deduplication and reconciliation; static file server dot-file access block (`/.git/HEAD` -> 404).

---

## 2. Logic Chain

### 2.1 Impact of 3-View Redesign on Existing Test 14
1. **The 3-View Redesign Requirements** (`ORIGINAL_REQUEST.md`, lines 12–26, 33–45) require:
   - At most 3 primary views: `Overview`, `Invoices`, `Payments`.
   - Elimination of visual clutter: "The `Overview` view displays at most 4 top-level KPI summary cards, the Sankey diagram, and at most 2 simple companion charts — with no dense multi-line text blocks or 10-card status grids cluttering the screen."
   - Secondary capabilities (Suppliers, Alerts, Audit Trail, Settings) must appear only on demand (drawers/modals/collapsible sections).
2. **Breakage in Test 14 (`test.js:486`)**:
   - `assert.ok(elements.get('kpi-status-grid').innerHTML.includes('Received / New'));`
   - Reasoning: If `kpi-status-grid` (the 10-card status grid) is removed from the Overview workspace to comply with AC2, this assertion will throw `TypeError: Cannot read properties of undefined (reading 'includes')` or `AssertionError`.
3. **Breakage in Test 14 (`test.js:489–493`)**:
   - `assert.ok(elements.get('suppliers-grid').innerHTML.includes('CloudScale Infrastructure GmbH'));`
   - `assert.ok(elements.get('alerts-list').innerHTML.includes('SLA Breach'));`
   - `assert.ok(elements.get('audit-log-tbody').innerHTML.includes('SYSTEM_INIT'));`
   - `assert.ok(elements.get('analytics-summary').innerHTML.includes('Verification Turnaround Time by Supplier'));`
   - `assert.ok(elements.get('analytics-summary').innerHTML.includes('Top Suppliers by Volume'));`
   - Reasoning: Currently, these elements reside in obsolete top-level views: Tab 4 (`panel-suppliers`), Tab 5 (`panel-alerts`), and Tab 6 (`panel-governance`). If these tabs are removed from the primary layout, either the elements will not be rendered on initial page load, or `renderAll()` will be refactored, causing these assertions to fail immediately.
4. **Breakage in Test 14 (`test.js:386–391`)**:
   - Static ID validation:
     ```javascript
     for (const id of referencedIds) {
       assert.ok(
         htmlIds.has(id) || dynamicIds.has(id),
         `app.js references getElementById("${id}") which is missing from index.html and dynamic templates`
       );
     }
     ```
   - Reasoning: If IDs are pruned from `index.html` (e.g. `panel-suppliers`, `panel-alerts`, `panel-governance`, `digest-preview-box`, `integrations-box`, `settings-box`) while `app.js` still contains queries for them, Test 14 will fail during the static ID scan before running the controller.

### 2.2 Coverage Gaps in Current Test Suite
The existing test suite has zero assertions verifying the acceptance criteria specified in `ORIGINAL_REQUEST.md`:
1. **Navigation**: Does NOT assert `<= 3` primary navigation tabs (currently has 6 tabs in `index.html`, lines 41–90).
2. **Overview KPI Density**: Does NOT assert `<= 4` top-level KPI summary cards.
3. **Table Columns**: Does NOT assert `<= 7` table columns for `Invoices` (currently 11 columns in `index.html`, lines 222–233) or `Payments` (currently 9 columns in `index.html`, lines 256–265).
4. **Sankey Diagram**: Zero tests exist for:
   - Sankey lifecycle flow calculation
   - Sankey supplier/department flow calculation
   - Mathematical conservation of flow across stages ($\sum \text{inputs} = \sum \text{outputs}$)
   - SVG node/link generation (`<svg>`, `<path>`, `<rect>`/`<g>`)
   - Dual-mode dynamic toggle (`lifecycle` vs `supplier`)
   - Hover/click interactive invoice filtering
5. **Companion Charts**: Zero tests exist for companion chart rendering (at most 2 companion charts on Overview, visual SVG/canvas representation, light/dark theme adaptation).
6. **Theme Compatibility**: Theme toggle is only clicked in Test 14 line 500 without verifying that chart/Sankey styles adapt to light and dark themes.

---

## 3. Caveats
1. **Mock DOM Query Capability**: The current mock DOM in `test.js` (`makeEl`) has a dummy `querySelectorAll() { return []; }`. To test multi-element queries (e.g. counting `.nav-tab` buttons, table `<th>` elements, KPI `.card` elements, or SVG `<rect>`/`<path>` elements), tests must either:
   - Parse `index.html` and rendered element `innerHTML` using standard regular expressions/string matching, OR
   - Slightly enhance `makeEl` with a basic tag/class query selector.
2. **Zero-Dependency Mandate**: The test suite must remain strictly zero-dependency. Introducing `jsdom` or other external npm packages would violate the project's zero-dependency architecture.
3. **Module Boundaries for Sankey**: Pure calculation logic for Sankey flows (`computeSankeyLifecycleFlow`, `computeSankeySupplierFlow`, or `computeSankeyFlow`) should reside in `core.js` so it can be tested headlessly in `test.js` without requiring DOM rendering. The SVG generation (`renderSankeySVG`) can also be exported by `core.js` (or `app.js`) to allow pure functional verification of SVG markup.

---

## 4. Conclusion & New Test Suite Specification

### 4.1 Update Required for Existing Test 14
Modify Test 14 to:
1. Retain the static ID audit, but update the allowed/required ID set:
   - Add new 3-view IDs (e.g. `sankey-container`, `sankey-mode-toggle`, `sankey-mode-lifecycle`, `sankey-mode-supplier`, `kpi-summary-cards`, `chart-overview-1`, `chart-overview-2`).
   - Remove obsolete tab IDs or ensure secondary drawer/modal IDs are declared in `dynamicIds`.
2. Update rendered innerHTML assertions:
   - Replace assertions on `kpi-status-grid` with assertions on the simplified KPI cards and Sankey container.
   - For secondary features (suppliers, alerts, audit log), verify they are rendered when their respective drawers/modals are invoked, rather than expecting them on the initial top-level page surface.

### 4.2 Specifications for New Test Suites
The following 7 test suites must be added to `test.js`:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       VAULTGARD TEST SUITE ARCHITECTURE                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ Existing Preserved Domain & API Suites (Tests 1–13, 15):                   │
│   • 10 Lifecycle Statuses & Seed Validation                                 │
│   • Domain KPIs, Verification Queue, Multi-Currency FX                      │
│   • Query Engine, Filtering, Sorting, RFC 4180 CSV                          │
│   • 9-Point Fraud & Anomaly Audit Rules                                     │
│   • RBAC, Callback Verification, Multi-Tier Approval Workflow               │
│   • Payment Guards, Segregation of Duties (SoD), ISO 20022 SEPA XML        │
│   • Alert Engine, SHA-256 Audit Hash Chain, OCR Ingestion, REST API Server  │
│   • Edge-Case Regressions (OCR multiline, discount idempotency, dot-files) │
├─────────────────────────────────────────────────────────────────────────────┤
│ New Suites (3-View Redesign & Visual Components):                           │
│   • Suite A: 3-Tab Primary Navigation Structure & Workspace Verification    │
│   • Suite B: Overview KPI Summary Count (<= 4) & Anti-Clutter Verification │
│   • Suite C: Main Tables Simplification (Columns <= 7) & Modal Drawer Check │
│   • Suite D: Interactive Dual-Mode Sankey Diagram & Flow Conservation      │
│   • Suite E: Companion Charts Visual Clarity (<= 2 on Overview)             │
│   • Suite F: Light & Dark Theme Adaptability Verification                   │
│   • Suite G: Full Regression & Integration Safety Harness                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Suite A: 3-Tab Primary Navigation Structure & Workspace Layout
- **Test Objective**: Verify strict enforcement of at most 3 top-level primary navigation views (`Overview`, `Invoices`, `Payments`).
- **Assertions**:
  1. Static analysis of `index.html`: Find all `<button>` or `<a>` elements within `.nav-tabs` or `[role="tablist"]`.
     - `assert.ok(navTabs.length <= 3, `Primary navigation tabs count (${navTabs.length}) exceeds 3`);`
     - `assert.deepEqual(navTabIds.sort(), ['invoices', 'overview', 'payments']);`
  2. Obsolete top-level tabs (`alerts`, `suppliers`, `governance`) must NOT exist in the primary navigation bar.
  3. Panel containers: Verify `<main>` contains panels corresponding to the 3 views (`panel-overview`, `panel-invoices`, `panel-payments`).
  4. Controller interaction: In the DOM harness, triggering clicks on `nav-tab` for `overview`, `invoices`, and `payments` toggles the `.active` class and `aria-selected` attribute correctly.

#### Suite B: Overview KPI Summary Count & Anti-Clutter Verification
- **Test Objective**: Verify that the Overview view presents at most 4 KPI summary cards and eliminates the 10-card status grid.
- **Assertions**:
  1. Count cards in `#kpi-top-cards` (or `#kpi-summary-cards`):
     - `const cardCount = (elements.get('kpi-top-cards').innerHTML.match(/class="card\b/g) || []).length;`
     - `assert.ok(cardCount <= 4, `Top KPI cards (${cardCount}) must be <= 4`);`
     - `assert.ok(cardCount >= 3, `Top KPI cards should display core summary metrics`);`
  2. Elimination of status grid:
     - `const statusGrid = elements.get('kpi-status-grid');`
     - `assert.ok(!statusGrid || !statusGrid.innerHTML || statusGrid.innerHTML.trim() === '', '10-card status grid must not clutter Overview');`
  3. Monetary formatting and currency resilience:
     - Verify KPI values contain formatted currency symbols (e.g. `€` or `$`).
     - Test switching `state.settings.baseCurrency = 'USD'` re-renders KPIs with converted amounts without throwing.

#### Suite C: Main Tables Column Count & Simplification Verification
- **Test Objective**: Verify that main tables (`Invoices` and `Payments`) display at most 6–7 clean columns.
- **Assertions**:
  1. Invoices Table:
     - Extract `<th>` headers from `#invoices-table`:
       `const invHeaders = Array.from(html.matchAll(/<table[^>]*id="invoices-table"[^>]*>[\s\S]*?<thead>[\s\S]*?<tr>([\s\S]*?)<\/tr>/g))[0];`
       `const thCount = (invHeaders[1].match(/<th\b/g) || []).length;`
     - `assert.ok(thCount <= 7, `Invoices table columns (${thCount}) must be <= 7`);`
  2. Payments Table:
     - Extract `<th>` headers from the payable queue table in `panel-payments`:
       `assert.ok(payThCount <= 7, `Payments table columns (${payThCount}) must be <= 7`);`
  3. Detail Drawer Verification:
     - Assert `#dialog-invoice-detail` exists in `index.html`.
     - Verify that invoking `openInvoiceDetail(invoiceId)` renders the complete 9-point audit checklist, approval history, and audit timeline inside the modal body without cluttering the main table.

#### Suite D: Dual-Mode Sankey Diagram & Flow Conservation Suite
- **Test Objective**: Mathematically verify flow conservation across stages in both modes, and assert valid SVG rendering.
- **Calculations to Test (`core.js`)**:
  1. **Mode 1: Invoice Lifecycle Flow (`computeSankeyLifecycleFlow`)**:
     - `const flow = VG.computeSankeyData(state, 'lifecycle');`
     - Stages:
       - Stage 0: `Ingested / Received`
       - Stage 1: `In Audit / Review`
       - Stage 2: `Approved & Ready to Pay`
       - Stage 3: `Terminal / Outcome` (`Paid & Scheduled` vs `Flagged & Blocked`)
     - Flow Conservation Checks:
       - Total system volume: $V_{\text{total}} = \sum \text{invoices.amount}$.
       - For every stage transition $s \to s+1$:
         $$\sum_{l \in \text{links}_{s \to s+1}} l.\text{value} == V_{\text{total}} \quad (\pm 0.01)$$
       - For intermediate node $n$:
         $$\sum_{l: \text{target}=n} l.\text{value} == \sum_{l: \text{source}=n} l.\text{value}$$
  2. **Mode 2: Supplier Financial Flow (`computeSankeySupplierFlow`)**:
     - `const flow = VG.computeSankeyData(state, 'supplier');`
     - Stages:
       - Stage 0: Suppliers (e.g. CloudScale, Nexus, Lumina, Apex, etc.)
       - Stage 1: Audit Outcome (`Approved`, `Under Review`, `Flagged / Blocked`)
       - Stage 2: Payment Outcome (`Paid / SEPA`, `Scheduled`, `Held / Blocked`)
     - Flow Conservation Checks:
       - Total supplier volume == Total audit outcome volume == Total payment volume == $V_{\text{total}}$.
       - Each supplier node's outgoing links sum to that supplier's total invoice volume.
  3. **Edge Case Tests**:
     - Empty invoice set (`state.invoices = []`): returns valid empty structure (`{ nodes: [], links: [], totalVolume: 0 }`) without NaN or errors.
     - Single invoice, 100% scam invoice, 100% paid invoices.
  4. **SVG Node & Link Rendering (`renderSankeySVG`)**:
     - `const svg = VG.renderSankeySVG(flow, { width: 800, height: 380, theme: 'dark' });`
     - Assert `<svg` element with valid `viewBox="0 0 800 380"`.
     - Assert `<rect` or `<g` elements exist for each node, with `width > 0` and `height > 0`.
     - Assert `<path` elements exist for links, with cubic Bézier curves `d="M ... C ..."`.
     - Assert `<text` elements exist for node labels with non-empty text content.
     - Assert no `NaN` or `undefined` strings in SVG attributes (`assert.ok(!svg.includes('NaN'))`).
     - Assert no negative coordinates (`assert.ok(!svg.includes('width="-') && !svg.includes('height="-'))`).
  5. **Dynamic Mode Switching in Controller**:
     - In DOM harness, click mode switch button (e.g. `#btn-sankey-mode-supplier`).
     - Assert container `#sankey-container` updates innerHTML with new supplier SVG nodes.

#### Suite E: Companion Charts & Visual Clarity Suite
- **Test Objective**: Verify clean visual charts (maximum 2 on Overview) with scannable numbers.
- **Assertions**:
  1. Chart count constraint:
     - On `#panel-overview`, count chart containers:
       `const chartContainers = html.match(/id="chart-[^"]+"/g) || [];`
       `assert.ok(chartContainers.length <= 2, `Overview companion charts (${chartContainers.length}) must be <= 2`);`
  2. Visual SVG/Canvas rendering:
     - Assert chart elements generate visual markup (SVG `<rect>`, `<path>`, `<polyline>`, `<line>` or canvas), avoiding raw dense text walls.
     - Check labels contain formatted values (e.g. `€` or `$`).
  3. Cash-Flow Forecast Chart (Payments view):
     - Assert payments view includes a visual cash-flow / scheduling forecast chart displaying upcoming payment commitments.

#### Suite F: Light & Dark Theme Compatibility Suite
- **Test Objective**: Verify visual elements adapt to theme switching.
- **Assertions**:
  1. Toggle theme button `#btn-theme-toggle`:
     - Initial: `data-theme="light"`. Click -> updates `data-theme="dark"`. Click -> updates `data-theme="light"`.
  2. Theme styles:
     - Inspect rendered SVG elements in `#sankey-container` and companion charts. Verify fills/strokes utilize CSS theme variables (`var(--...)`) or dynamically adapt to theme changes.

#### Suite G: Full Regression & Integration Safety Harness
- **Test Objective**: Guarantee 100% regression safety across all existing domain logic.
- **Assertions**:
  - Re-run all existing domain tests (1 through 13, 15) to confirm 0 regressions in:
    - 10-status invoice lifecycle model.
    - 9-point fraud checks and duplicate detection.
    - RBAC permissions, callback verification, and 2-level approvals.
    - Segregation of Duties (SoD) and payment blocking.
    - ISO 20022 SEPA XML `pain.001.001.03` generation.
    - REST API server endpoints (`/api/kpis`, `/api/invoices`, `/api/invoices/ingest`, `/`).
    - Cryptographic audit trail hash verification.

---

## 5. Verification Method

### 5.1 Independent Test Execution Command
Run the automated test suite from the project root:
```bash
npm test
```
or directly via the Node test runner:
```bash
node --test test.js
```

### 5.2 Specific Files to Inspect
1. `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/package.json` — verify zero external dependencies are added.
2. `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/index.html` — verify at most 3 navigation tabs (`overview`, `invoices`, `payments`), at most 4 KPI summary cards, at most 2 companion charts, at most 7 table columns, and detail modal/drawer.
3. `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/core.js` — inspect exports for `computeSankeyData` (or `computeSankeyLifecycleFlow` / `computeSankeySupplierFlow`) and `renderSankeySVG`.
4. `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/app.js` — inspect 3-view navigation handler, Sankey mode switch handler, and detail drawer triggers.
5. `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/test.js` — verify all baseline tests pass and new suites (A–G) pass with 0 failures.

### 5.3 Invalidation Conditions
The survey and test architecture will be considered invalidated if:
1. `npm test` requires external npm packages (violating the zero-dependency requirement).
2. The Sankey flow conservation equation ($\sum \text{in} == \sum \text{out}$) produces discrepancies greater than $\epsilon = 0.01$ in either mode.
3. `index.html` retains more than 3 primary tabs in `<nav>`, more than 4 top-level KPI cards, or more than 7 columns in either main table.
4. Any existing domain rules (SoD, SEPA XML, 9-point checks, RBAC) fail or are modified.
