# Project: Vaultgard Invoice Audit & Payment Dashboard Redesign

## Architecture
Vaultgard is a zero-dependency web dashboard for invoice auditing, fraud detection, and payment execution.
- `core.js`: Universal domain logic module (UMD). Implements invoice models, 9-point fraud checks, RBAC, payment rules, SEPA XML ISO 20022 generation, SHA-256 audit hash chain, and Sankey flow conservation calculations (`computeSankeyData`, `renderSankeySVG`).
- `server.js`: Zero-dependency Node.js HTTP server. Serves static files and REST APIs (`/api/kpis`, `/api/invoices`, `/api/invoices/ingest`, etc.).
- `index.html`: Web interface structured into at most 3 primary views (`Overview`, `Invoices`, `Payments`) with on-demand modals/drawers for secondary details.
- `styles.css`: CSS styling with light and dark theme variable support (`data-theme="light"` / `data-theme="dark"`), spacious layout, and clean typography.
- `app.js`: Frontend UI controller. Manages 3-view navigation, interactive dual-mode Sankey SVG rendering and event handlers, companion charts, search/filters, and table rendering.
- `test.js`: Automated test suite running natively via `node --test test.js` (`npm test`) with zero dependencies, validating domain rules, API endpoints, DOM integrity, Sankey flow conservation, and visual components.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | 3 Primary Views Navigation | Navigation limited to at most 3 top-level views: Overview, Invoices, Payments | M2 | ORIGINAL_REQUEST R1 |
| 2 | On-Demand Secondary Details | Alerts, Suppliers, Governance/Settings moved to drawers/modals/chrome actions | M2 | ORIGINAL_REQUEST R1 |
| 3 | Overview Anti-Clutter & KPIs | Max 4 KPI summary cards; 10-status cards grid removed from primary view | M2 | ORIGINAL_REQUEST R1 |
| 4 | Streamlined Invoices Table | Main table displaying at most 6–7 essential columns, details in modal | M2 | ORIGINAL_REQUEST R1 |
| 5 | Streamlined Payments Table | Main payable queue showing at most 6 essential columns | M2 | ORIGINAL_REQUEST R1 |
| 6 | Sankey Flow Math & Conservation | Lifecycle & Supplier flow calculation with strict flow conservation in core.js | M1 | ORIGINAL_REQUEST R2 |
| 7 | Dual-Mode Sankey SVG Rendering | Interactive SVG rendering (<svg>, <path>, <rect>/<g>) with theme adaptation | M3 | ORIGINAL_REQUEST R2 |
| 8 | Sankey Mode Switcher & Filters | Interactive toggle between Lifecycle and Supplier/Dept flow; click-to-filter | M3 | ORIGINAL_REQUEST R2 |
| 9 | Simple Readable Charts | Max 2 SVG companion charts on Overview, 1 cash-flow forecast chart on Payments | M3 | ORIGINAL_REQUEST R3 |
| 10 | Domain Logic Preservation | Retain 10 statuses, 9-point fraud checks, SoD, SEPA XML, RBAC in core.js | M1 | ORIGINAL_REQUEST R4 |
| 11 | HTTP Server Preservation | Retain zero-dependency server.js and API endpoints | M1 | ORIGINAL_REQUEST R4 |
| 12 | Automated Test Suite & Regression | node:test suite with 0 failures, testing 3 views, Sankey math, SVG, and domain | M4 | ORIGINAL_REQUEST R4 |
| 13 | Adversarial & Integrity Hardening | Empirical edge-case validation and forensic zero-tolerance integrity audit | M5 | ORIGINAL_REQUEST AC |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | M1: Core Domain & Sankey Engine | `computeSankeyData` (lifecycle & supplier flows, conservation math), SVG generation helper in `core.js` | none | DONE |
| 2 | M2: UI Markup & CSS Simplification | 3-tab layout, <=4 KPI cards, <=7 table columns, on-demand modals in `index.html` & `styles.css` | M1 | DONE |
| 3 | M3: Controller & Visual Components | Interactive Sankey diagram, mode toggle, companion SVG charts in `app.js` | M1, M2 | DONE |
| 4 | M4: E2E Test Suite & Verification | Update Test 14 and author Suites A–G in `test.js` (`npm test`) | M1, M2, M3 | DONE |
| 5 | M5: Adversarial Hardening & Forensic Audit | Challenger stress tests, edge cases, and Forensic Auditor verification | M4 | DONE |

## Interface Contracts
### core.js ↔ app.js & test.js
- `VG.computeSankeyData(state, options)`:
  - Input: `state` (object with `invoices`, `settings`), `options` (`{ mode: 'lifecycle' | 'supplier', metric: 'amount' | 'count' }`)
  - Output: `{ mode, metric, total, stages: [...], nodes: [{ id, label, stage, value, count, invoiceIds }], links: [{ source, target, value, count, invoiceIds }] }`
  - Invariant: For every stage $k$, $\sum_{n \in \text{stage}_k} n.\text{value} == \text{total}$. For every intermediate node $n$, $\sum_{\text{in}} == \sum_{\text{out}}$.
- `VG.renderSankeySVG(sankeyData, options)`:
  - Input: `sankeyData` (from `computeSankeyData`), `options` (`{ width, height, theme }`)
  - Output: string of valid SVG markup containing `<svg>`, `<g>`, `<rect>`, `<path>`, `<text>`.

### index.html ↔ app.js & test.js
- Navigation: `.nav-tab` buttons for `overview`, `invoices`, `payments`.
- Overview containers: `#kpi-top-cards` (max 4 cards), `#sankey-container` (or `#sankey-diagram-wrapper`), `#chart-monthly-container`, `#chart-supplier-container`.
- Secondary modals: `#dialog-invoice-detail`, `#dialog-alerts`, `#dialog-suppliers`, `#dialog-governance`.
- Invoices table: `#invoices-table` with at most 7 `<th>` columns.
- Payments table: `#payable-tbody` with at most 6 `<th>` columns.

## Code Layout
- Exclusive Write Boundaries:
  - Worker M1: `core.js`
  - Worker M2: `index.html`, `styles.css`
  - Worker M3: `app.js`
  - Worker M4: `test.js`
