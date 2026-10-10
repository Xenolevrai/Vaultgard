# Domain & Backend Survey Report: Vaultgard Architecture, Data Model, Lifecycles & Sankey Flow Conservation

**Date**: 2026-10-10  
**Author**: Explorer Domain Survey  
**Working Directory**: `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/.agents/teamwork/explorer_survey_domain`  
**Target Codebase**: `/Users/hugobefort/dev/Secure_Horizon/Vaultgard`  

---

## 1. Observation

### 1.1 Codebase Structure and Role Division
Direct inspection of the repository files revealed the following architecture:
- `core.js` (3,193 lines, 115,744 bytes): Universal UMD module (Node.js & browser global `Vaultgard`) implementing all domain business rules, fraud detection algorithms, RBAC, payment authorization, and initial state seeding.
- `server.js` (124 lines, 4,654 bytes): Zero-dependency Node.js HTTP server (`node:http`) providing static file serving and 7 REST API endpoints:
  - `GET /api/kpis` (line 48)
  - `GET /api/invoices` (line 51)
  - `POST /api/invoices/ingest` (line 55)
  - `POST /api/invoices/:id/action` (line 60)
  - `POST /api/payments/batch` (line 70)
  - `GET /api/alerts` (line 78)
  - `GET /api/audit-log` (line 81)
- `test.js` (633 lines, 24,146 bytes): Automated test suite running natively via `node --test test.js` with 9 passing test suites verifying all domain aspects.
- `app.js` (1,493 lines, 71,719 bytes): Frontend controller managing 6 navigation tabs (`overview`, `invoices`, `alerts`, `payments`, `suppliers`, `governance`), a 10-card status grid, search/filter bars, and table renderers.
- `index.html` (22,581 bytes) & `styles.css` (16,308 bytes): Existing DOM markup and styling.

### 1.2 Data Model Analysis
From `core.js` lines 2639–3148 (`createInitialState`):

#### A. Invoice Structure
Each invoice record possesses the following schema:
- **Identifiers**: `id` (e.g. `'INV-1001'`), `invoiceNumber` (e.g. `'CS-2026-091'`).
- **Counterparty**: `supplierId` (`'SUP-01'`), `supplierName` (`'CloudScale Infrastructure GmbH'`), `vatNumber` (`'DE812345678'`), `iban` (`'DE89370400440532013000'`), `senderEmail` (`'billing@cloudscale.de'`).
- **Financials**: `amount` (float), `currency` (`'EUR'`, `'GBP'`, `'USD'`, `'CHF'`), `paidAmount` (default 0), `creditNoteAmount` (default 0), `appliedDiscountAmount` (default 0), `earlyDiscountPercent` (float), `earlyDiscountDeadline` (`YYYY-MM-DD`).
- **Dates**: `issueDate`, `dueDate`, `receivedAt`, `verifiedAt`, `scheduledPaymentDate`, `paidAt`.
- **Status & Risk**:
  - `status`: One of 10 statuses defined in `STATUSES` (`core.js:16–27`).
  - `riskScore`: 0–100 calculated from 9 audit checks.
  - `riskLevel`: `'low'`, `'medium'`, or `'high'` (high if score >= 65, sanctions failed, or document tampering detected).
  - `riskReasons`: string array of detected anomalies.
- **Organization & Assignment**: `department` (`'Engineering'`, `'Operations'`, `'Security'`, `'Logistics'`, `'Finance'`), `entity` (`'Vaultgard EU'`, `'Vaultgard UK'`), `assignee`.
- **Match Documents**: `poNumber`, `poAmount`, `grnNumber`, `grnStatus` (`'matched'`, `'pending'`, `'mismatch'`, `'missing'`), `documentMeta` (`tampered`, `fontMismatch`, `modifiedAfterIssue`).
- **Audit & Governance**:
  - `checklist`: Array of 9 audit checks (`supplier_validation`, `bank_details`, `duplicate_detection`, `three_way_match`, `amount_checks`, `document_checks`, `email_sender`, `anomaly_detection`, `sanctions_screening`).
  - `requiredApprovalLevels`: 1 (<=€10k), 2 (<=€50k), or 3 (>€50k) (`core.js:507–513`).
  - `approvals`: Array of `{ level, userId, userName, role, timestamp, note }`.
  - `callbackVerified`: boolean (true if confirmed by phone callback).
  - `batchId`: string (SEPA batch ID if batched).
  - `comments`, `attachments`, `timeline`, `versionHistory`.

#### B. Seeded Invoice Inventory & Amounts
The 10 seeded invoices in `core.js` (lines 2779–3065) and their base EUR equivalents (`FX_RATES`: EUR: 1.0, USD: 0.92, GBP: 1.17, CHF: 1.04):
| ID | Invoice No | Supplier | Dept | Amount | Status | Risk | EUR Value |
|---|---|---|---|---|---|---|---|
| INV-1001 | CS-2026-091 | CloudScale | Engineering | €8,420.50 | `received` | Low (0) | €8,420.50 |
| INV-1002 | LUM-8821 | Lumiere Office | Operations | £1,850.00 | `pending_verification` | Low (0) | €2,164.50 |
| INV-1003 | NCS-2026-404 | Nordic CyberSec | Security | €24,500.00 | `under_review` | Low (0) | €24,500.00 |
| INV-1004 | APX-9910 | Apex Precision | Logistics | €9,850.00 | `flagged` | High (87) | €9,850.00 |
| INV-1005 | GSC-666 | Global Shadow | Finance | €49,500.00 | `rejected` | High (100) | €49,500.00 |
| INV-1006 | CS-2026-085 | CloudScale | Engineering | €9,200.00 | `verified_approved` | Low (0) | €9,200.00 |
| INV-1007 | NCS-2026-390 | Nordic CyberSec | Security | €7,650.00 | `ready_to_pay` | Low (0) | €7,650.00 |
| INV-1008 | LUM-8790 | Lumiere Office | Operations | £1,420.00 | `scheduled` | Low (0) | €1,661.40 |
| INV-1009 | CS-2026-070 | CloudScale | Engineering | €8,100.00 | `paid` | Low (0) | €8,100.00 |
| INV-1010 | APX-9840 | Apex Precision | Logistics | €5,400.00 | `on_hold` | Med (45) | €5,400.00 |
| **TOTAL** | | | | | | | **€126,446.40** |

#### C. Suppliers Inventory
- `SUP-01`: CloudScale Infrastructure GmbH (Verified, €14k avg, official domain `cloudscale.de`)
- `SUP-02`: Apex Precision Logistics SAS (Verified, recent unverified bank change, `apex-logistics.fr`)
- `SUP-03`: Lumiere Office Supplies Ltd (Verified, £2.2k avg, UK)
- `SUP-04`: Nordic CyberSec Solutions AB (Verified, €28k avg, Sweden)
- `SUP-05`: Global Shadow Consulting LLC (Blacklisted, Sanctions Hit, Cyprus)

#### D. Departments Inventory
1. `Engineering`: €25,720.50 (INV-1001, INV-1006, INV-1009)
2. `Security`: €32,150.00 (INV-1003, INV-1007)
3. `Finance`: €49,500.00 (INV-1005)
4. `Logistics`: €15,250.00 (INV-1004, INV-1010)
5. `Operations`: €3,825.90 (INV-1002, INV-1008)

---

## 2. Logic Chain

### 2.1 Mapping Granular Domain Statuses to Lifecycle Stages
The core engine has 10 granular statuses (`STATUSES`, `core.js:16–27`). Requirement R2 specifies the Lifecycle Flow stages:
`Ingested / Received → In Audit / Review → Approved & Ready to Pay → Scheduled / Paid vs. Flagged / Blocked (Fraud)`.

The mapping from the 10 domain statuses to the 5 lifecycle categories is logically partitioned as:

1. **Ingested / Received**:
   - `received`: Ingestion pipeline complete, initial pending audit state.
2. **In Audit / Review**:
   - `pending_verification`: Checks run, awaiting auditor triage (SLA tracking).
   - `under_review`: Assigned to auditor or awaiting level 2/3 approval.
   - `on_hold`: Disputed, awaiting supplier feedback, delivery receipt, or phone callback.
3. **Approved & Ready to Pay**:
   - `verified_approved`: Passed all 9 checks, multi-level approvals granted, due date in future.
   - `ready_to_pay`: Approved and due immediately/this week.
4. **Scheduled / Paid**:
   - `scheduled`: Payment execution date set / assigned to SEPA batch.
   - `paid`: Payment executed with bank reference and reconciled.
5. **Flagged / Blocked (Fraud)**:
   - `flagged`: High risk detected (lookalike domain, IBAN mismatch, tampering).
   - `rejected`: Confirmed scam, sanctions hit, or blacklisted vendor; hard-blocked from payment.

### 2.2 Mathematical Model for Sankey Flow Conservation
To guarantee **Conservation of Flow** (where for every intermediate node $\sum \text{in} = \sum \text{out}$, and every stage sums to the exact total volume $T$):

#### A. Partition Property
Let $\mathcal{I}$ be the set of invoices. For any pair of stages $k$ and $k+1$, the transition links are formed by partitioning $\mathcal{I}$ into mutually exclusive, collectively exhaustive subsets $\mathcal{I}_{u, v}$:
$$\bigcup_{u \in S_k, v \in S_{k+1}} \mathcal{I}_{u, v} = \mathcal{I} \quad \text{and} \quad \mathcal{I}_{u_1, v_1} \cap \mathcal{I}_{u_2, v_2} = \emptyset \quad \forall (u_1, v_1) \neq (u_2, v_2)$$
Because the flow weight of link $(u, v)$ is defined as:
$$\text{Weight}(u, v) = \sum_{i \in \mathcal{I}_{u, v}} \text{Metric}(i)$$
where $\text{Metric}(i)$ is either the EUR converted amount or 1 (for invoice count), the sum of all link weights entering any stage equals $\sum_{i \in \mathcal{I}} \text{Metric}(i) = T$ identically.

#### B. Flow 1: Invoice Lifecycle Flow (3 Stages)
- **Stage 0: Ingestion**
  - Node `ingested` ("Ingested / Received"): All invoices $\mathcal{I}$. Total: €126,446.40 (10 invoices).
- **Stage 1: Audit Evaluation**
  - Node `in_audit` ("In Audit / Review"): Invoices with status $\in \{\text{received}, \text{pending\_verification}, \text{under\_review}, \text{on\_hold}, \text{verified\_approved}, \text{ready\_to\_pay}, \text{scheduled}, \text{paid}\}$. Total: €67,096.40 (8 invoices).
  - Node `flagged_fraud` ("Flagged / Blocked"): Invoices with status $\in \{\text{flagged}, \text{rejected}\}$. Total: €59,350.00 (2 invoices).
  - *Conservation*: €67,096.40 + €59,350.00 = €126,446.40 (Input matches Output).
- **Stage 2: Settlement Status**
  - From `in_audit` (€67,096.40):
    - Link to `in_review_hold` ("In Review / On Hold"): Statuses $\in \{\text{received}, \text{pending\_verification}, \text{under\_review}, \text{on\_hold}\}$. €40,485.00 (4 invoices).
    - Link to `approved_ready` ("Approved & Ready to Pay"): Statuses $\in \{\text{verified\_approved}, \text{ready\_to\_pay}\}$. €16,850.00 (2 invoices).
    - Link to `scheduled_paid` ("Scheduled / Paid"): Statuses $\in \{\text{scheduled}, \text{paid}\}$. €9,761.40 (2 invoices).
    - *Node Conservation at `in_audit`*: €40,485.00 + €16,850.00 + €9,761.40 = €67,096.40.
  - From `flagged_fraud` (€59,350.00):
    - Link to `blocked_prevented` ("Blocked (Fraud Prevented)"): Statuses $\in \{\text{flagged}, \text{rejected}\}$. €59,350.00 (2 invoices).
    - *Node Conservation at `flagged_fraud`*: €59,350.00 = €59,350.00.
  - *Stage 2 Total*: €40,485.00 + €16,850.00 + €9,761.40 + €59,350.00 = €126,446.40 (Exact match).

#### C. Flow 2: Supplier & Department Financial Flow (3 Stages)
- **Stage 0: Origin**
  - Nodes: Suppliers (`SUP-01` €25,720.50, `SUP-02` €15,250.00, `SUP-03` €3,825.90, `SUP-04` €32,150.00, `SUP-05` €49,500.00) OR Departments (`Engineering` €25,720.50, `Security` €32,150.00, `Finance` €49,500.00, `Logistics` €15,250.00, `Operations` €3,825.90).
  - *Stage 0 Total*: €126,446.40.
- **Stage 1: Audit Outcome**
  - Node `audit_approved` ("Audited & Approved"): Statuses $\in \{\text{verified\_approved}, \text{ready\_to\_pay}, \text{scheduled}, \text{paid}\}$. €26,611.40 (4 invoices).
  - Node `audit_review` ("In Review / On Hold"): Statuses $\in \{\text{received}, \text{pending\_verification}, \text{under\_review}, \text{on\_hold}\}$. €40,485.00 (4 invoices).
  - Node `audit_flagged` ("Flagged / Blocked"): Statuses $\in \{\text{flagged}, \text{rejected}\}$. €59,350.00 (2 invoices).
  - *Stage 1 Total*: €26,611.40 + €40,485.00 + €59,350.00 = €126,446.40.
- **Stage 2: Financial Destination**
  - From `audit_approved` (€26,611.40):
    - Link to `dest_paid` ("Paid / SEPA"): Statuses $\in \{\text{scheduled}, \text{paid}\}$. €9,761.40 (2 invoices).
    - Link to `dest_ready` ("Approved & Ready"): Statuses $\in \{\text{verified\_approved}, \text{ready\_to\_pay}\}$. €16,850.00 (2 invoices).
  - From `audit_review` (€40,485.00):
    - Link to `dest_held` ("Held / Review Queue"): €40,485.00 (4 invoices).
  - From `audit_flagged` (€59,350.00):
    - Link to `dest_blocked` ("Blocked / Scam Intercepted"): €59,350.00 (2 invoices).
  - *Stage 2 Total*: €9,761.40 + €16,850.00 + €40,485.00 + €59,350.00 = €126,446.40 (Exact match).

### 2.3 Preserving Core Domain Logic (R4)
Requirement R4 mandates preserving `core.js` and `server.js` while supporting the redesigned metrics, Sankey calculations, and charts:
1. **Core Domain Immutability**: All existing functions in `core.js` (including 9 audit checks, `canPayInvoice`, SoD, SEPA XML pain.001.001.03 generator, SHA hash chain, OCR parser, and initial state generator) must remain 100% backward compatible.
2. **Domain Calculation Helper**: A pure helper function `computeSankeyData(state, options)` should be added to `core.js` and exported.
   - Zero side-effects: takes `state` and options (`mode`, `metric`), returns `{ mode, metric, total, stages, nodes, links }`.
   - Each link contains `invoiceIds` to allow immediate interactive click-to-filter on the UI.
3. **Automated Testing Suite**:
   - `test.js` tests 1–13 and 15 remain fully intact.
   - `test.js` test 14 is updated as explicitly permitted by R4 to verify the 3-tab layout (`overview`, `invoices`, `payments`), Sankey SVG element rendering, and on-demand modal/drawer elements.
   - Programmatic tests for `computeSankeyData` are added, validating flow conservation across all modes and edge cases.

---

## 3. Caveats

1. **Exchange Rates**: Invoices denominated in GBP (INV-1002, INV-1008) convert to EUR using `FX_RATES.GBP = 1.17`. Total sums must always convert through `convertCurrency(amount, currency, baseCurrency)` to prevent discrepancies when changing base currency.
2. **Dynamic Ingested Invoices**: Invoices added dynamically via OCR ingestion (`ingestInvoice`) or REST API will have new IDs and amounts. Flow conservation algorithms must dynamically calculate stage subsets from `state.invoices` rather than hardcoding seeded IDs.
3. **Credit Notes and Partial Payments**: Invoices with partial payments (like INV-1007 during payment tests) have a face `amount` and a `remainingAmount`. Sankey diagrams can compute based on gross face amount or remaining balance; gross face amount is recommended for initial lifecycle volume flow, with payment status reflecting remaining balance.

---

## 4. Conclusion & Concrete Recommendations

### 4.1 Domain Helper Implementation Recommendation
Add a pure calculation function `computeSankeyData` directly to `core.js`:

```javascript
function computeSankeyData(state, options = {}) {
  const mode = options.mode || 'lifecycle'; // 'lifecycle' | 'supplier' | 'department'
  const metric = options.metric || 'amount'; // 'amount' | 'count'
  const baseCurrency = (state.settings && state.settings.baseCurrency) || 'EUR';
  const invoices = state.invoices || [];

  const getWeight = (inv) => {
    if (metric === 'count') return 1;
    return convertCurrency(inv.amount, inv.currency, baseCurrency);
  };

  const total = Number(invoices.reduce((sum, inv) => sum + getWeight(inv), 0).toFixed(2));

  // Build nodes and links with strict invoice set partitioning
  // ... Returns { mode, metric, baseCurrency, total, stages, nodes, links }
}
```

### 4.2 Data Structures for UI & Companion Charts
1. **Overview Top KPIs (Maximum 4 Cards)**:
   - Card 1: **Ready to Pay** (Amount due today/this week, invoice count).
   - Card 2: **Audit Queue & SLA** (Pending verification amount, oldest item age).
   - Card 3: **Fraud & Scam Prevented** (Total money saved, flagged/rejected count).
   - Card 4: **Total Pipeline Volume** (Total tracked invoices, gross active volume).
2. **Overview Companion Charts (Maximum 2 Simple Visual Charts)**:
   - Chart 1: **Monthly Volume & Audit Status** (Simple stacked SVG bar chart: Verified/Paid vs Flagged).
   - Chart 2: **Risk Exposure Breakdown** (Simple horizontal SVG bars: Low, Medium, High risk volume).
3. **Payments View Chart**:
   - Chart: **Cash Flow Horizon / Upcoming Due Dates** (Today, 7 Days, 30 Days, Overdue).

### 4.3 Table Simplification Strategy
- **Invoices Table**: Reduce main columns from 11+ to 6: `[Invoice, Supplier, Department, Amount, Due Date, Status/Risk]`.
- **Payments Table**: Reduce main columns to 6: `[Invoice, Supplier, Amount, Due Date, Discount Opportunity, Action]`.
- **On-Demand Detail Modal / Drawer**: Triggered on row click, displaying the 9-point checklist, timeline, version history, supplier profile, and comments.

---

## 5. Verification Method

To verify these findings and implementations:

1. **Run Current Test Suite**:
   ```bash
   cd /Users/hugobefort/dev/Secure_Horizon/Vaultgard
   npm test
   ```
   *Expected*: 9 tests pass with 0 failures.

2. **Verify Conservation of Flow Calculation**:
   Run a Node.js verification script:
   ```javascript
   const VG = require('./core.js');
   const state = VG.createInitialState();
   const data = VG.computeSankeyData(state, { mode: 'lifecycle' });
   // Assert: sum of incoming links to each node equals node value
   // Assert: sum of nodes in each stage equals data.total
   ```

3. **Verify REST API & Server**:
   ```bash
   node -e "const { createServer } = require('./server.js'); const { server } = createServer(); console.log('Server initialized successfully'); server.close();"
   ```

4. **Invalidation Conditions**:
   - Any intermediate Sankey node where $\sum \text{in} \neq \sum \text{out}$ by more than 0.01 (due to rounding).
   - Any total stage sum that does not equal total invoice volume.
   - Any regression in the 9-point fraud checklist, SoD rules, or SEPA XML generation.
