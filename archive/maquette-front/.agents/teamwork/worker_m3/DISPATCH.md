## 2026-10-10T16:48:00Z
You are Worker M3: Controller & Visual Components.
Your working directory is: /Users/hugobefort/dev/Secure_Horizon/Vaultgard/.agents/teamwork/worker_m3/
You MUST read ORIGINAL_REQUEST.md at: /Users/hugobefort/dev/Secure_Horizon/Vaultgard/.agents/teamwork/ORIGINAL_REQUEST.md.
Also read PROJECT.md at: /Users/hugobefort/dev/Secure_Horizon/Vaultgard/.agents/teamwork/PROJECT.md, Worker M1 handoff at: /Users/hugobefort/dev/Secure_Horizon/Vaultgard/.agents/teamwork/worker_m1/handoff.md, and Worker M2 handoff at: /Users/hugobefort/dev/Secure_Horizon/Vaultgard/.agents/teamwork/worker_m2/handoff.md.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

File Ownership: You exclusively own `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/app.js`. Do not modify index.html, core.js, styles.css, server.js, or test.js.

Objective:
1. Update `app.js` to implement:
   - Primary 3-view navigation (`overview`, `invoices`, `payments`) in `switchTab`.
   - On-demand dialog triggers:
     * `#btn-open-alerts`, `#btn-sidebar-alerts` -> open `#dialog-alerts`
     * `#btn-open-suppliers`, `#btn-sidebar-suppliers` -> open `#dialog-suppliers`
     * `#btn-open-governance`, `#btn-sidebar-governance` -> open `#dialog-governance`
     * Ensure modal close buttons (`data-close="dialog-..."`) work properly.
   - On `#panel-overview`:
     * Render at most 4 top-level clean KPI cards in `#kpi-top-cards` (e.g. Ready to Pay, In Audit Queue, Fraud Prevented, Total Pipeline Volume) without dense multi-line text walls.
     * Render the interactive dual-mode Sankey diagram:
       - State variable `ui.sankeyMode` (default `'lifecycle'`, toggles to `'supplier'` or `'department'`).
       - Call `Vaultgard.computeSankeyData(state, { mode: ui.sankeyMode, metric: 'amount' })`.
       - Call `Vaultgard.renderSankeySVG(sankeyData, { theme: document.documentElement.getAttribute('data-theme') || 'dark' })`.
       - Inject into `#sankey-diagram-wrapper` (or `#sankey-container`).
       - Wire up click handlers on `#btn-sankey-lifecycle` and `#btn-sankey-dept` / `#btn-sankey-supplier` to update `ui.sankeyMode` and re-render with `.active` class toggled on buttons.
       - Wire up interactive click/hover handlers: clicking a node or link filters invoices by `invoiceIds` and switches to the Invoices tab. Hovering shows `#sankey-tooltip`.
     * Render at most 2 clean companion SVG charts in `.chart-row`:
       - `#chart-monthly-trends`: Visual SVG bar chart showing monthly volume and audit breakdown (e.g., Approved vs Flagged).
       - `#chart-supplier-trends`: Visual SVG horizontal bar chart showing top suppliers by volume with risk indicators.
       - Replace any dense HTML div progress bars with clean SVG graphics with non-zero dimensions, scannable numbers, and legible labels.
   - On `#panel-invoices`:
     * Render `#invoices-tbody` rows matching the 7 columns:
       1. Checkbox (`<input type="checkbox" ...>`)
       2. Invoice (`<strong>${inv.invoiceNumber}</strong><br><small class="text-muted">${inv.id}</small>`)
       3. Supplier (`${inv.supplierName}`)
       4. Amount (`${formatMoney(inv.amount, inv.currency)}`)
       5. Due Date (`${inv.dueDate} ${overdueBadge}`)
       6. Status & Risk (`${statusBadge} ${riskPill}`)
       7. Actions (`<button class="btn btn-sm" data-inspect-id="${inv.id}">Inspect</button>`)
     * Clicking a row or "Inspect" opens `#dialog-invoice-detail` with full 9-point checklist, timeline, and actions.
   - On `#panel-payments`:
     * Render `#payable-tbody` rows matching the 6 columns:
       1. Invoice
       2. Supplier
       3. Due Date
       4. Balance
       5. Eligibility (SoD badge)
       6. Actions
     * Render companion SVG chart on Payments: Cash-flow forecast / Due Date buckets timeline chart in `#chart-cashflow-viewport` / `#chart-cashflow-svg`.
   - Theme toggle `#btn-theme-toggle`: Toggling theme must re-render the Sankey diagram and companion charts so SVG fills and strokes adapt cleanly.
2. Verification:
   - Run `npm test` (`node --test test.js`). All 9 tests must pass with 0 errors.
   - Ensure every `getElementById` in `app.js` exists in `index.html` (Test 14 static check).
3. Document your changes and verification in `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/.agents/teamwork/worker_m3/handoff.md`.
When finished, send a message back to the orchestrator.
