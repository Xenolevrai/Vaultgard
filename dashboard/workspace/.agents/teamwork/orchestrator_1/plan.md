# Plan: Vaultgard Invoice Audit & Payment Dashboard Redesign

## Phase 0: Survey & Discovery
- [ ] Dispatch 3 Explorers / Spec Miners in parallel:
  - Explorer 1 (Architecture & UI): Inspect index.html, public/ assets, CSS, client-side JS, current views, components, and layout.
  - Explorer 2 (Core Domain & Backend): Inspect core.js, server.js, data models, state flows, calculation helpers, and API endpoints.
  - Explorer 3 (Test Suite & Verification): Inspect test.js, package.json, test runner, DOM mocks/harnesses, assertions, and coverage.
- [ ] Synthesize explorer findings into `PROJECT.md` (Feature Inventory, Architecture, Interfaces, Code Layout) and `TEST_INFRA.md`.

## Phase 1: Planning & Decomposition
- [ ] Define concrete milestones:
  - M1: Data Model & Flow Engine for Dual-Mode Sankey and Simplified Metrics (Lifecycle vs Supplier Flow calculation, flow conservation).
  - M2: UI Redesign — 3-Tab Architecture (`Overview`, `Invoices`, `Payments`) with simplified tables, whitespace, detail drawer/modal.
  - M3: Visual Components — Interactive Dual-Mode SVG Sankey Diagram & Companion Charts (light/dark theme support).
  - M4: Integration & E2E Testing — Wire everything together, update/extend test suite (`npm test`), verify 0 failures.
- [ ] Establish Interface Contracts and Code Layout boundaries in `PROJECT.md`.

## Phase 2: Execution (Dual-Track)
- [ ] Implementation Track: Execute milestones via Explorer -> Worker -> Reviewer -> Challenger -> Auditor cycle.
- [ ] E2E Testing Track: Build robust opaque-box test cases for the 3-tab layout, Sankey SVG paths/nodes/conservation, chart rendering, and existing domain logic.
- [ ] Publish `TEST_READY.md`.

## Phase 3: Final Verification & Audit Hardening
- [ ] Phase 1 of Final Milestone: Pass 100% of E2E tests across all tiers.
- [ ] Phase 2 of Final Milestone: Adversarial coverage hardening (Challengers + Workers).
- [ ] Forensic integrity audit verification (Zero tolerance).
- [ ] Report completion to Sentinel.
