## 2026-10-10T16:23:23Z
You are Worker M1: Core Domain & Sankey Engine.
Your working directory is: /Users/hugobefort/dev/Secure_Horizon/Vaultgard/.agents/teamwork/worker_m1/
You MUST read ORIGINAL_REQUEST.md at: /Users/hugobefort/dev/Secure_Horizon/Vaultgard/.agents/teamwork/ORIGINAL_REQUEST.md.
Also read PROJECT.md at: /Users/hugobefort/dev/Secure_Horizon/Vaultgard/.agents/teamwork/PROJECT.md and the Domain Survey at: /Users/hugobefort/dev/Secure_Horizon/Vaultgard/.agents/teamwork/explorer_survey_domain/handoff.md.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

File Ownership: You exclusively own `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/core.js`. Do not modify any other file.

Objective:
1. In `core.js`, implement and export:
   - `computeSankeyData(state, options)`
   - `renderSankeySVG(sankeyData, options)`
2. `computeSankeyData(state, options)` must support:
   - `mode = 'lifecycle'` (Default):
     * Stage 0: `Ingested / Received` (all invoices)
     * Stage 1: `In Audit / Review` vs `Flagged / Blocked`
     * Stage 2: `In Review / On Hold`, `Approved & Ready to Pay`, `Scheduled / Paid`, and `Blocked (Fraud Prevented)`
   - `mode = 'supplier'` (or `'department'`):
     * Stage 0: Suppliers (or departments)
     * Stage 1: Audit Outcome (`Approved & Verified`, `In Review / On Hold`, `Flagged / Blocked`)
     * Stage 2: Financial Destination (`Paid / SEPA`, `Approved & Ready`, `Held / Review Queue`, `Blocked / Scam Intercepted`)
   - `metric = 'amount'` (default, normalized to baseCurrency via `convertCurrency`) and `metric = 'count'`.
   - STRICT CONSERVATION OF FLOW: At every stage transition, total input volume == total output volume. For every intermediate node, sum of inputs == sum of outputs.
   - Attach `invoiceIds` to nodes and links for interactive filtering.
   - Graceful edge-case handling: empty invoices array (`[]`), single invoice, 100% fraud, etc.
3. `renderSankeySVG(sankeyData, options)`:
   - Computes layout positions: node rectangles (`<rect>`) with non-zero width & height, smooth cubic bezier curve paths (`<path d="M... C... L... C... Z">`) representing ribbons with widths proportional to link values.
   - Clear `<text>` labels with node names, counts, and formatted currency amounts.
   - Uses CSS variables (`var(--teal)`, `var(--danger)`, `var(--warning)`, `var(--text)`) or theme parameter (`dark` / `light`) so it adapts seamlessly.
   - No `NaN`, no negative coordinates, and viewBox configured cleanly.
4. Verify: Run `npm test` to verify that all existing 9 tests pass with 0 regressions. Write a quick verification test or check flow conservation mathematically.
5. Document your work, commands run, and verification results in `/Users/hugobefort/dev/Secure_Horizon/Vaultgard/.agents/teamwork/worker_m1/handoff.md`.
When finished, send a message back to the orchestrator.
