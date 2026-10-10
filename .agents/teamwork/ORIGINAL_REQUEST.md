# Original User Request

## 2026-10-10T16:10:02Z

Redesign and drastically simplify the Vaultgard Invoice Audit & Payment Dashboard to eliminate visual clutter and information overload, organizing the interface into at most 3 spacious views (`Overview`, `Invoices`, `Payments`) with generous whitespace, an interactive dual-mode Sankey diagram, and simple, immediately readable charts.

Working directory: /Users/hugobefort/dev/Secure_Horizon/Vaultgard
Integrity mode: development

## Requirements

### R1. Radical Simplification & Maximum 3 Primary Views
Streamline navigation and on-screen layout to at most 3 primary views (`Overview`, `Invoices`, `Payments`) with generous whitespace and minimal text density. Secondary details (full 9-point fraud checklist, audit trail, supplier history, settings, or secondary metadata) must not clutter the main views and should only appear on demand (e.g., in a clean detail drawer/modal or compact collapsible section). Main tables must display only essential columns (e.g., Invoice, Supplier, Amount, Due Date, Status/Risk) without crowding the screen.

### R2. Interactive Dual-Mode Sankey Diagram
Feature a prominent, clean, readable Sankey diagram on the `Overview` view with a simple mode switcher supporting two flow perspectives:
1. **Invoice Lifecycle Flow**: Ingested / Received → In Audit / Review → Approved & Ready to Pay → Scheduled / Paid vs. Flagged / Blocked (Fraud).
2. **Supplier / Department Financial Flow**: Suppliers (or Departments) → Audit Outcome → Paid / SEPA vs. Held / Blocked.
Nodes and proportional flow links must clearly display counts and/or monetary volumes, support hover/click inspection (filtering or highlighting related invoices), and adapt cleanly to both light and dark themes.

### R3. Simple, Readable Charts
Replace dense, text-heavy widgets on the `Overview` and `Payments` views with clean, legible visual charts (such as a clear monthly volume/status chart and a simple risk/supplier or cash-flow chart) with uncluttered axes, clear legends, and scannable numbers.

### R4. Preserve Core Domain Capabilities & Automated Test Suite
Maintain the existing core domain logic (`core.js`), HTTP server (`server.js`), and automated test suite (`npm test`), updating DOM/UI tests as needed to reflect the simplified 3-view layout and adding programmatic verification for the Sankey diagram and chart data/rendering.

## Verification Resources

- Existing test suite: `npm test` (`node --test test.js`) in `/Users/hugobefort/dev/Secure_Horizon/Vaultgard`.

## Acceptance Criteria

### UI Simplification & Navigation
- [ ] Primary navigation contains at most 3 top-level tabs/views (`Overview`, `Invoices`, `Payments`).
- [ ] The `Overview` view displays at most 4 top-level KPI summary cards, the Sankey diagram, and at most 2 simple companion charts — with no dense multi-line text blocks or 10-card status grids cluttering the screen.
- [ ] The `Invoices` and `Payments` tables show at most 6–7 clean columns on the main screen, moving detailed audit checklists, timelines, and secondary metadata into the on-demand detail modal/drawer.

### Sankey Diagram & Readable Charts
- [ ] The Sankey diagram renders valid SVG nodes and proportional curved path links (`<svg>`, `<path>`, `<rect>`/`<g>`) with non-zero dimensions and no overlapping labels.
- [ ] Switching the Sankey selector between **Lifecycle Flow** and **Supplier/Department Flow** dynamically updates the rendered SVG nodes and links to match the current invoice state, and conservation of flow holds across stages (input totals match output totals).
- [ ] Companion charts render as clean visual SVG/canvas charts with legible labels and support both light and dark themes.

### Verification & Regression
- [ ] `npm test` passes with 0 failures, including automated tests verifying the 3-tab structure, Sankey node/link flow calculations for both modes, SVG rendering, and existing domain workflows.
