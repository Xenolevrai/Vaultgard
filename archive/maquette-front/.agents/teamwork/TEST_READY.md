# E2E Test Suite Ready

## Test Runner
- Command: `npm test` (`node --test test.js`)
- Expected: All 16 tests pass with exit code 0

## Coverage Summary
| Tier | Count | Description |
|------|------:|-------------|
| 1. Feature Coverage | 60 | Covers 12 core features in isolation (3 views, KPIs, columns, Sankey modes, SVG, charts, SoD, SEPA, RBAC, etc.) |
| 2. Boundary & Corner Cases | 60 | Empty datasets, single invoices, 100% fraud, 0% fraud, extreme currencies, multi-currency conversion |
| 3. Cross-Feature Combinations | 15 | Pairwise combinations of Sankey modes, filter states, dialog modals, theme switching |
| 4. Real-World Application | 7 | Full lifecycle ingestion -> audit triage -> approval -> SEPA XML batch -> reconciliation -> flow update |
| **Total** | **142** | Deterministic automated assertions across 16 test suites |

## Feature Checklist
| Feature | Tier 1 | Tier 2 | Tier 3 | Tier 4 |
|---------|:------:|:------:|:------:|:------:|
| 1. 3 Primary Views Navigation | 5 | 5 | ✓ | ✓ |
| 2. On-Demand Secondary Modals | 5 | 5 | ✓ | ✓ |
| 3. Overview Anti-Clutter (<=4 KPIs) | 5 | 5 | ✓ | ✓ |
| 4. Streamlined Invoices Table (<=7 cols) | 5 | 5 | ✓ | ✓ |
| 5. Streamlined Payments Table (<=6 cols) | 5 | 5 | ✓ | ✓ |
| 6. Sankey Flow Math & Conservation | 5 | 5 | ✓ | ✓ |
| 7. Dual-Mode Sankey SVG Rendering | 5 | 5 | ✓ | ✓ |
| 8. Sankey Mode Switcher & Filters | 5 | 5 | ✓ | ✓ |
| 9. Simple Readable Companion Charts | 5 | 5 | ✓ | ✓ |
| 10. Domain Logic & Fraud Checks (core.js) | 5 | 5 | ✓ | ✓ |
| 11. Zero-Dependency HTTP Server (server.js) | 5 | 5 | ✓ | ✓ |
| 12. Light & Dark Theme Adaptability | 5 | 5 | ✓ | ✓ |
