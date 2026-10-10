## 2026-10-10T16:35:33Z
You are Worker M2: UI Markup & CSS Simplification.
Your working directory is: /Users/hugobefort/dev/Secure_Horizon/Vaultgard/.agents/teamwork/worker_m2/
You MUST read ORIGINAL_REQUEST.md at: /Users/hugobefort/dev/Secure_Horizon/Vaultgard/.agents/teamwork/ORIGINAL_REQUEST.md.
Also read PROJECT.md at: /Users/hugobefort/dev/Secure_Horizon/Vaultgard/.agents/teamwork/PROJECT.md and the UI Survey at: /Users/hugobefort/dev/Secure_Horizon/Vaultgard/.agents/teamwork/explorer_survey_ui/handoff.md.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

File Ownership: You exclusively own:
- `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/index.html`
- `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/styles.css`
Do NOT modify core.js, app.js, server.js, or test.js.

Objective:
1. In `index.html` and `styles.css`:
   - Primary navigation (`.nav-tabs` in sidebar): Exactly 3 primary views: `Overview` (`data-tab="overview"`), `Invoices` (`data-tab="invoices"`), and `Payments` (`data-tab="payments"`).
   - Move secondary views (`suppliers`, `alerts`, `governance`/audit trail/settings) to on-demand drawers/modals or secondary header actions (e.g. `<dialog id="dialog-alerts">`, `<dialog id="dialog-suppliers">`, `<dialog id="dialog-governance">`, or compact modal containers) so that their DOM IDs (`alerts-list`, `suppliers-grid`, `audit-log-tbody`, `analytics-summary`, `integrations-box`, `settings-box`, `digest-preview-box`) remain present in the DOM for `app.js` and tests, but do NOT clutter the primary 3 views.
   - On `#panel-overview`:
     * Header & `#kpi-top-cards`: Spacious layout with max 4 clean KPI cards.
     * Prominent Sankey diagram card: Container `#sankey-container` with title, subtitle, mode switcher button group (`#btn-sankey-lifecycle` and `#btn-sankey-dept` / `#btn-sankey-supplier`), and SVG viewport (`#sankey-svg` or `#sankey-diagram-wrapper`).
     * Maximum 2 companion charts container in `.chart-row`: `#chart-monthly-container` and `#chart-supplier-container` (or `#chart-monthly-trends` / `#chart-supplier-trends`), styled for clean visual charts.
     * Move `#kpi-status-grid` into a clean collapsible `<details class="status-grid-collapsible">` or on-demand secondary section so it is available on demand but does NOT crowd the primary Overview screen.
   - On `#panel-invoices`:
     * Simplify `#invoices-table`: Exactly 7 columns in the main table:
       1. Checkbox (`#chk-select-all`)
       2. Invoice Number (`data-sort="invoiceNumber"`)
       3. Supplier Name (`data-sort="supplierName"`)
       4. Amount (`data-sort="amount"`)
       5. Due Date (`data-sort="dueDate"`)
       6. Status & Risk (`data-sort="status"`)
       7. Actions (`Inspect / Audit`)
     * All detailed checklists, PO/GRN matching, comments, and timelines remain in `#dialog-invoice-detail`.
   - On `#panel-payments`:
     * Simplify Payments table: Exactly 6 columns in the main table:
       1. Invoice
       2. Supplier
       3. Due Date
       4. Balance
       5. Eligibility (SoD)
       6. Actions
     * Companion chart container for Cash-Flow forecast / Due Date buckets (`#chart-cashflow-container`).
   - Generous whitespace, clean modern aesthetic, and full support for both light and dark themes via CSS custom properties (`data-theme="light"` / `data-theme="dark"`).
2. Verification: Check that all IDs expected by `app.js` and existing tests are preserved in `index.html`.
3. Document all changes and verification in `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/.agents/teamwork/worker_m2/handoff.md`.
When finished, send a message back to the orchestrator.
