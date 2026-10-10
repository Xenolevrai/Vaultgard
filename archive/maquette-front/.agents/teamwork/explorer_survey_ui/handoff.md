# UI Architecture & Frontend Survey Handoff Report

## 1. Observation

### 1.1 Frontend File Structure & Dependencies
- **Files located**:
  - HTML structure: `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/index.html` (453 lines, 22.6 KB)
  - CSS styling & themes: `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/styles.css` (884 lines, 16.3 KB)
  - UI controller & client logic: `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/app.js` (1,493 lines, 71.7 KB)
  - Core domain logic: `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/core.js` (3,193 lines, 115.7 KB)
  - Zero-dependency HTTP static server: `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/server.js` (124 lines, 4.6 KB)
  - Test suite: `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/test.js` (633 lines, 24.1 KB)
  - Project configuration: `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/package.json` (11 lines, 309 B)
- **Dependency findings**:
  - `package.json` contains 0 runtime dependencies and 0 devDependencies. Pure vanilla standard library and modern browser APIs.
  - No external JavaScript libraries (no D3, Chart.js, React, or jQuery) are loaded or imported in `index.html` (lines 449-450: only `<script src="core.js"></script><script src="app.js"></script>`).

### 1.2 Existing Navigation & Views Structure
- **Current Navigation Tabs** (`index.html` lines 37-92):
  - Sidebar (`<aside class="sidebar" id="app-sidebar">`) contains **6 navigation tabs** grouped into 3 sections:
    1. Group "Audit & Queue":
       - `data-tab="overview"`: Overview
       - `data-tab="invoices"`: Invoices & Audit (badge: `#badge-invoices-count`)
       - `data-tab="alerts"`: Alerts & SLA (badge: `#badge-alerts-count`)
    2. Group "Payments & Vendors":
       - `data-tab="payments"`: Payments & SEPA (badge: `#badge-payable-count`)
       - `data-tab="suppliers"`: Suppliers
    3. Group "Compliance & Admin":
       - `data-tab="governance"`: Audit Trail & Settings
  - Top Chrome Bar (`index.html` lines 12-33):
    - Sidebar toggle button: `#btn-toggle-sidebar`
    - Quick search button: `#btn-focus-search` (switches to invoices tab)
    - Day/Night Theme toggle button: `#btn-theme-toggle`
    - Action button: `#btn-open-ingest` ("+ New invoice")
- **Tab Switching Mechanism** (`app.js` lines 1190-1201):
  ```javascript
  function switchTab(tabId) {
    ui.activeTab = tabId;
    document.querySelectorAll('.nav-tab').forEach((btn) => {
      const isMatch = btn.getAttribute('data-tab') === tabId;
      btn.classList.toggle('active', isMatch);
      btn.setAttribute('aria-selected', isMatch ? 'true' : 'false');
    });
    document.querySelectorAll('.tab-panel').forEach((panel) => {
      panel.classList.toggle('active', panel.id === `panel-${tabId}`);
    });
    renderAll();
  }
  ```
- **Current Panels**:
  - `#panel-overview` (`index.html` lines 97-120):
    - `#kpi-top-cards`: 4 cards populated by `app.js` lines 213-255. Each card contains 3-4 dense text lines (`<div class="kpi-sub">`).
    - Card "Status Breakdown — Click any status to filter queue": contains `#kpi-status-grid` (`index.html` line 107) displaying all 10 statuses as individual cards (`app.js` lines 258-272), creating high visual density.
    - Container `.chart-row`: contains 2 text-heavy HTML div progress-bar charts: `#chart-monthly-trends` and `#chart-supplier-trends` (`app.js` lines 291-329).
  - `#panel-invoices` (`index.html` lines 123-238):
    - `#saved-views-bar`: Saved view pills and 8 status badge filter buttons (`app.js` lines 334-379).
    - `.filters-grid`: Dense 11-field grid spanning search, status, supplier, risk level, department, assignee, payment method, date from, date to, min amount, max amount (`index.html` lines 131-198).
    - `.toolbar-row`: Bulk action buttons (Run Checks, Assign, Approve, Hold, Flag), Save View, Reset, and CSV/XLS/PDF exports.
    - Table `#invoices-table` (`index.html` lines 219-236): **11 columns**:
      1. Checkbox (`#chk-select-all`)
      2. Invoice Number / ID (`data-sort="invoiceNumber"`)
      3. Supplier Name / Department / Method (`data-sort="supplierName"`)
      4. Amount (`data-sort="amount"`)
      5. Issue Date (`data-sort="issueDate"`)
      6. Due Date (`data-sort="dueDate"`)
      7. Status Badge (`data-sort="status"`)
      8. Risk Level Badge (`data-sort="riskScore"`)
      9. PO Number
      10. Assignee (`data-sort="assignee"`)
      11. Action button ("Inspect / Audit")
  - `#panel-payments` (`index.html` lines 241-275):
    - Header with `#btn-create-sepa-batch`
    - `#cashflow-cards`: 4 KPI cards (Overdue/Today, Next 7d, Next 30d, Early Discount).
    - Table (`index.html` lines 253-268): **9 columns**:
      1. Invoice
      2. Supplier & IBAN
      3. Status
      4. Due / Scheduled
      5. Balance
      6. Early Discount
      7. Approved By
      8. Eligibility (SoD)
      9. Actions (Schedule, Pay Full, Partial, Credit Note)
    - `#batches-container`: SEPA XML batch listing with download and reconcile buttons.
  - `#panel-suppliers` (`index.html` lines 277-285): Contains `#suppliers-grid` (vendor cards with IBAN change log and whitelist/blacklist buttons).
  - `#panel-alerts` (`index.html` lines 287-302): Contains `#alerts-list` and `#digest-preview-box`.
  - `#panel-governance` (`index.html` lines 305-352): Contains `#analytics-summary`, `#integrations-box`, `#settings-box`, and `#audit-log-tbody` (table with 7 columns).

### 1.3 Modals, Drawers & Details
- **Invoice Detail Modal** (`index.html` lines 358-367):
  - Uses native `<dialog id="dialog-invoice-detail">`.
  - Opens via `openInvoiceDetail(invoiceId)` (`app.js` lines 478-485).
  - Contains 2-column layout (`.detail-split`):
    - Left: Forensic PDF / OCR Viewer (`.doc-preview`), Linked Documents (PO, GRN, Vendor Master Record), Internal Comments & @Mentions (`#input-detail-comment`, `#btn-detail-comment`), Attachments (`#btn-detail-attach`).
    - Right: Workflow action buttons (Re-run checks, Assign, Callback verify, Approve L1/L2, Hold, Flag, Reject), 9-Point Fraud & Compliance Checklist (`.checklist-list`), Full Lifecycle Timeline & Version History (`.timeline-list`).
- **Ingestion Modal** (`index.html` lines 370-445):
  - Native `<dialog id="dialog-ingest">` for OCR raw text parsing and invoice submission.

### 1.4 Themes, CSS Variables & Styling
- **Theme Mechanism**:
  - Root element attribute: `<html lang="en" data-theme="light">` (or `data-theme="dark"`).
  - Toggled in `app.js` lines 1223-1228.
- **CSS Variables** (`styles.css` lines 1-41):
  - Light mode:
    `--shell-bg: #f3f3f2; --bg: #ffffff; --bg-elevated: #ffffff; --bg-card: #ffffff; --bg-subtle: #f8f8f7; --bg-hover: #ebebea;`
    `--text: #141413; --text-secondary: #5c5c59; --text-muted: #787774; --border: #e5e5e3; --border-strong: #d4d4d1;`
    `--accent: #181817; --success: #0d9488; --warning: #d97706; --danger: #dc2626; --teal: #14b8a6; --orange: #d97706;`
  - Dark mode:
    `--shell-bg: #141413; --bg: #1c1c1b; --bg-elevated: #242422; --bg-card: #222220; --bg-subtle: #181817; --bg-hover: #2c2c29;`
    `--text: #f3f3f2; --text-secondary: #b5b4b0; --text-muted: #8e8d8a; --border: #2e2e2b; --border-strong: #3e3e3a; --accent: #f3f3f2;`
- **Charts & SVG Usage**:
  - Currently, SVG is only used for inline icons (e.g., Lucide/Feather icon paths in badges and navigation).
  - Existing charts are purely HTML `<div>` bar fills (`.bar-track`, `.bar-fill` in `styles.css` lines 720-750). No canvas or `<svg>` charts exist in the codebase currently.

### 1.5 Automated Test Suite Constraints
- **Test Command**: `npm test` runs `node --test test.js`.
- **Test 14 Verification**:
  - `test.js` lines 355-391 verifies:
    Every `getElementById('...')` in `app.js` MUST exist in either `index.html` or `dynamicIds`.
  - `test.js` lines 485-494 verifies that the DOM harness elements (`kpi-top-cards`, `kpi-status-grid`, `invoices-tbody`, `payable-tbody`, `suppliers-grid`, `alerts-list`, `audit-log-tbody`, `analytics-summary`) are populated with specific expected strings upon initial render.
- Test 14 can and should be adapted as authorized in R4 ("updating DOM/UI tests as needed to reflect the simplified 3-view layout and adding programmatic verification for the Sankey diagram and chart data/rendering").

---

## 2. Logic Chain

```
Observation 1.2: Current navigation has 6 top-level tabs, while R1 specifies at most 3 primary views (Overview, Invoices, Payments).
    └──> Step 1: Sidebar navigation must be reduced to exactly 3 top-level tabs: [Overview, Invoices, Payments].
    └──> Step 2: The remaining 3 views (Alerts, Suppliers, Governance/Settings/Audit) must be moved into on-demand drawers or modals accessible on demand (e.g., via top chrome bar or compact secondary actions), preventing screen clutter.

Observation 1.2 & 1.4: Overview currently renders a 10-card status grid (#kpi-status-grid) and dense multi-line KPI cards, causing visual clutter.
    └──> Step 3: Remove the 10-card grid from the primary Overview layout. Move status cards into a collapsible/on-demand section or replace them with the Sankey diagram, which represents status flow natively.
    └──> Step 4: Streamline the 4 KPI cards to single primary numbers with a single, concise subtitle (e.g. "Ready to Pay: €52,300 · 2 ready").

Observation 1.2: Invoices table has 11 columns and Payments table has 9 columns, exceeding the R1 maximum of 6–7 columns.
    └──> Step 5: Condense Invoices table to 7 clean columns:
         [Select, Invoice, Supplier, Amount, Due Date, Status / Risk, Actions].
         Move Issue Date, PO, Department, Assignee into the detail modal (#dialog-invoice-detail).
    └──> Step 6: Condense Payments table to 6 clean columns:
         [Invoice, Supplier, Due Date, Balance, Status / SoD, Actions].
         Move secondary metadata (raw IBAN, discount details, approver details) into detail view.

Observation 1.4: No SVG charts currently exist; charts are rendered via div elements. R2 requires a prominent dual-mode Sankey diagram and R3 requires companion charts on Overview & Payments.
    └──> Step 7: Build a zero-dependency SVG Sankey engine supporting:
         - Mode 1: Lifecycle Flow (Ingested → In Audit → Approved & Ready → Scheduled/Paid vs Flagged/Blocked).
         - Mode 2: Supplier / Department Flow (Departments/Suppliers → Audit Outcome → Paid/SEPA vs Held/Blocked).
         - Conservation of flow: Input totals equal output totals at each stage.
         - Proportional cubic bezier paths (`<path>`), node rectangles (`<rect>`), legible text labels (`<text>`), and theme-aware styling.
         - Click/hover interactions to filter and inspect invoices.
    └──> Step 8: Replace div progress bars on Overview with 2 clean SVG companion charts (Monthly Volume & Audit Status, Supplier Volume & Risk).
    └──> Step 9: Add clean SVG companion chart to Payments (Cash-Flow Due Timeline & Aging).

Observation 1.1 & 1.5: package.json has 0 dependencies; test.js validates DOM integrity and test 14 verifies getElementById mappings.
    └──> Step 10: All SVG generation must use vanilla JavaScript (createElementNS('http://www.w3.org/2000/svg', ...)).
    └──> Step 11: Implement flow computation helpers in core.js (e.g., VG.computeSankeyData(state, mode)) so that flow conservation and stage calculations can be tested programmatically in test.js and rendered cleanly in app.js.
    └──> Step 12: Maintain DOM container IDs for secondary panels in on-demand drawers/modals in index.html, and add comprehensive automated tests in test.js for the 3-tab layout, column counts, Sankey flows, and chart rendering.
```

---

## 3. Caveats

1. **DOM ID Compatibility in Test 14**:
   `test.js` Test 14 extracts all `getElementById` calls from `app.js` and asserts that they exist in `index.html`. If elements like `suppliers-grid` or `alerts-list` are moved into secondary drawers or modals, their element IDs must remain in `index.html` or be updated in concert with `test.js` to avoid breaking test 14.
2. **Zero-Dependency SVG Requirement**:
   External visualization libraries (D3, Chart.js, Plotly) cannot be added via npm because the project is designed for zero dependencies and runs in standard Node/browser environments. The Sankey layout algorithm and chart generators must be implemented in clean, vanilla JS.
3. **Multi-Currency Normalization in Sankey**:
   Invoices exist in multiple currencies (EUR, GBP). The Sankey diagram flow volumes must normalize all values into the base currency (`state.settings.baseCurrency`, default EUR) using `VG.convertCurrency` to guarantee strict mathematical conservation of flow.

---

## 4. Conclusion & Concrete Transformation Blueprint

### 4.1 Navigation & Primary Views (R1)
- **Top-level Navigation**:
  In `index.html`, reduce `.nav-tabs` to exactly **3 primary tabs**:
  - `Overview` (`data-tab="overview"`)
  - `Invoices` (`data-tab="invoices"`)
  - `Payments` (`data-tab="payments"`)
- **Secondary Details on Demand**:
  - Add an on-demand "System, Vendors & Compliance" drawer/modal (or individual modals: `#dialog-alerts`, `#dialog-suppliers`, `#dialog-governance`) accessible via top-bar icons (e.g., an Alert badge button and a Settings/Compliance button in `.header-controls`).
  - Move the 10-status cards grid (`#kpi-status-grid`) into a collapsible section (`<details class="collapsible-status-grid">`) on Overview, keeping it accessible on demand while eliminating main-screen clutter.

### 4.2 KPI Summary Cards (R1)
- In `app.js` (`renderOverview`), render exactly **4 spacious, scannable cards** in `#kpi-top-cards`:
  1. **Ready to Pay**: Primary amount (e.g., `€52,300`), subtitle: `2 invoices ready to pay`
  2. **In Audit Queue**: Primary amount (e.g., `€39,000`), subtitle: `3 invoices pending review`
  3. **Fraud Prevented**: Primary amount (e.g., `€59,350`), subtitle: `€9,850 active risk intercepted`
  4. **Overdue / Due**: Primary count & amount (e.g., `1 invoice · €5,400`), subtitle: `Action required`

### 4.3 Table Simplification (R1)
- **Invoices Table** (`#invoices-table`):
  Reduce from 11 columns to **7 columns**:
  1. `<th><input type="checkbox" id="chk-select-all" /></th>`
  2. `<th>Invoice</th>` (Invoice Number + ID)
  3. `<th>Supplier</th>` (Supplier Name)
  4. `<th>Amount</th>` (Formatted Amount & Currency)
  5. `<th>Due Date</th>` (Due date + Overdue badge if applicable)
  6. `<th>Status & Risk</th>` (Clean status badge + risk pill)
  7. `<th>Actions</th>` (`<button class="btn btn-sm" data-inspect-id="...">Inspect</button>`)
  *All secondary fields (PO number, GRN status, department, payment method, assignee, forensic PDF notes) remain fully viewable in the on-demand detail modal.*
- **Payments Table** (`#payable-tbody`):
  Reduce from 9 columns to **6 columns**:
  1. `<th>Invoice</th>`
  2. `<th>Supplier</th>`
  3. `<th>Due Date</th>`
  4. `<th>Balance</th>` (Remaining amount)
  5. `<th>Eligibility</th>` (SoD / Eligible / Blocked badge)
  6. `<th>Actions</th>` (Pay, Schedule, Discount, Credit Note)

### 4.4 Interactive Dual-Mode Sankey Diagram (R2)
- **Container**:
  Place a prominent card on `#panel-overview` directly below the 4 KPI cards:
  ```html
  <div class="card sankey-container-card">
    <div class="sankey-header">
      <div>
        <h3 class="card-title">Financial Flow Diagram (Sankey)</h3>
        <p class="sankey-subtitle">Interactive flow conservation across audit and settlement stages</p>
      </div>
      <div class="sankey-mode-toggle" role="group" aria-label="Sankey Flow Perspective">
        <button type="button" class="btn btn-sm active" id="btn-sankey-lifecycle">Lifecycle Flow</button>
        <button type="button" class="btn btn-sm" id="btn-sankey-dept">Supplier / Dept Flow</button>
      </div>
    </div>
    <div id="sankey-diagram-wrapper" class="sankey-viewport">
      <svg id="sankey-svg" width="100%" height="320" viewBox="0 0 900 320" preserveAspectRatio="xMidYMid meet"></svg>
    </div>
    <div id="sankey-tooltip" class="sankey-tooltip" style="display:none;"></div>
  </div>
  ```
- **Flow Engine & Math**:
  - Implement `computeSankeyData(state, mode)` in `core.js`:
    - **Lifecycle Mode**:
      - Stage 0: `Ingested Invoices` (Total volume)
      - Stage 1: `Audit Queue & Screening` (`Untriaged`, `In Review`, `Fraud Suspects`)
      - Stage 2: `Audit Outcome` (`Approved & Verified`, `Held / Disputed`, `Flagged / Scam`)
      - Stage 3: `Settlement` (`Paid / Scheduled`, `Ready to Pay`, `Blocked Scam`)
    - **Supplier / Department Mode**:
      - Stage 0: `Origin` (`Engineering`, `Security`, `Operations`, `Logistics`, `Finance`)
      - Stage 1: `Audit Gate` (`Approved`, `Flagged / Held`)
      - Stage 2: `Settlement` (`Paid / SEPA`, `Held / Blocked`)
    - **Conservation of flow**:
      Every invoice amount traces an exact path from Stage 0 to Stage N.
      For every node: $\sum \text{inflow} = \text{node.value} = \sum \text{outflow}$.
      At every stage $k$: $\sum \text{stage nodes} = \text{Total System Volume}$.
  - **SVG Rendering**:
    - Draw nodes as `<rect class="sankey-node" rx="4" ...>` with `<text class="sankey-label">` showing name, count, and amount.
    - Draw links as smooth cubic bezier ribbons:
      `M x0 y0Top C (x0+dx) y0Top, (x1-dx) y1Top, x1 y1Top L x1 y1Bot C (x1-dx) y1Bot, (x0+dx) y0Bot, x0 y0Bot Z`
    - Click interaction: Clicking any node or link activates the corresponding filter and navigates to the Invoices table.
    - Theme support: Use CSS custom properties (`var(--teal)`, `var(--danger)`, `var(--warning)`, `var(--text)`) with semi-transparent alpha fills (`0.35` normal, `0.75` hover).

### 4.5 Simple, Readable Companion Charts (R3)
- **Overview Companion Charts** (max 2):
  Replace the HTML div progress bars in `.chart-row` with:
  1. `<svg id="chart-monthly-svg">`: SVG grouped/stacked bar chart for monthly volume (Approved vs Flagged/Scam) with clean X/Y axes, numeric labels, and legend.
  2. `<svg id="chart-supplier-svg">`: SVG horizontal bar chart for top suppliers by volume with risk-colored bars (low risk in teal, high risk in red/amber).
- **Payments Companion Chart**:
  Add an SVG cash-flow timeline chart to `#panel-payments`:
  - `<svg id="chart-cashflow-svg">`: Visual bar chart depicting payment buckets (Overdue, Due Today, Next 7 Days, Next 30 Days, Beyond 30 Days).

### 4.6 Verification & Testing Strategy (R4)
- Add dedicated test cases in `test.js`:
  1. **Primary Navigation Structure**: Assert that primary nav has at most 3 tabs (`assert.equal(navTabs.length, 3)`).
  2. **Table Column Limits**: Assert that `#invoices-table` has $\le 7$ columns and payments table has $\le 6$ columns.
  3. **Overview KPI Cards**: Assert that Overview displays $\le 4$ KPI summary cards.
  4. **Sankey Flow Calculations & Conservation**:
     - Compute flow data for both modes via `VG.computeSankeyData`.
     - Assert that $\sum \text{inputs} = \sum \text{outputs}$ at every stage and node.
  5. **Sankey & Chart SVG Rendering**:
     - Verify SVG nodes (`<rect>`) and path ribbons (`<path>`) have non-zero dimensions.
     - Verify mode switching dynamically updates SVG nodes and links.
     - Verify companion charts render valid SVG graphics.
  6. **Regression**: Run complete test suite (`npm test`) to confirm 0 failures across all 15 test suites.

---

## 5. Verification Method

To independently verify these survey findings and recommendations:

1. **Verify Existing Tests Pass**:
   Run:
   ```bash
   npm test
   ```
   Confirm all 9 test suites pass with 0 failures.

2. **Verify Navigation and Table Columns in Source**:
   - Check navigation tabs count in `index.html` lines 37-92 (currently 6 tabs).
   - Check invoices table header in `index.html` lines 221-233 (currently 11 columns).
   - Check payments table header in `index.html` lines 255-265 (currently 9 columns).

3. **Verify DOM Element ID Coverage in Test 14**:
   Inspect `test.js` lines 355-391 to observe how `referencedIds` in `app.js` are checked against `index.html`.

4. **Verify Zero Dependency Setup**:
   Inspect `package.json` to confirm no third-party libraries exist.
