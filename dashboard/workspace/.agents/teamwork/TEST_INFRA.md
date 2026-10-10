# E2E Test Infra: Vaultgard Dashboard Redesign

## Test Philosophy
- Opaque-box, requirement-driven, zero-dependency.
- Built on Node.js standard built-in `node:test` and `node:assert/strict`.
- Methodology: Category-Partition + Boundary Value Analysis + Flow Conservation + Regression Safety.

## Feature Inventory Test Coverage
| # | Feature | Source | Tier 1 | Tier 2 | Tier 3 |
|---|---------|--------|:------:|:------:|:------:|
| 1 | 3 Primary Navigation Views | ORIGINAL_REQUEST R1 | 5 | 5 | ✓ |
| 2 | On-Demand Secondary Details | ORIGINAL_REQUEST R1 | 5 | 5 | ✓ |
| 3 | Overview Anti-Clutter & <=4 KPIs | ORIGINAL_REQUEST R1 | 5 | 5 | ✓ |
| 4 | Streamlined Invoices Table (<=7 cols) | ORIGINAL_REQUEST R1 | 5 | 5 | ✓ |
| 5 | Streamlined Payments Table (<=6 cols) | ORIGINAL_REQUEST R1 | 5 | 5 | ✓ |
| 6 | Sankey Flow Math & Conservation | ORIGINAL_REQUEST R2 | 5 | 5 | ✓ |
| 7 | Dual-Mode Sankey SVG Rendering | ORIGINAL_REQUEST R2 | 5 | 5 | ✓ |
| 8 | Sankey Mode Switcher & Filters | ORIGINAL_REQUEST R2 | 5 | 5 | ✓ |
| 9 | Simple Readable Charts (<=2 on Overview) | ORIGINAL_REQUEST R3 | 5 | 5 | ✓ |
| 10 | Domain Logic Preservation | ORIGINAL_REQUEST R4 | 5 | 5 | ✓ |
| 11 | HTTP Server Preservation | ORIGINAL_REQUEST R4 | 5 | 5 | ✓ |
| 12 | Automated Test Suite (npm test) | ORIGINAL_REQUEST R4 | 5 | 5 | ✓ |

## Test Architecture
- Test Runner: `npm test` (`node --test test.js`)
- Test Suites:
  - Preserved Suites: Tests 1–13, 15 (Domain models, fraud checks, RBAC, SoD, SEPA XML, REST API).
  - Updated Suite 14: DOM and controller integrity for 3-view layout.
  - New Suites (A through G):
    - Suite A: 3-Tab Primary Navigation Structure & Workspace Layout
    - Suite B: Overview KPI Summary Count (<= 4) & Anti-Clutter Verification
    - Suite C: Main Tables Column Count (<= 7) & Detail Modal Inspection
    - Suite D: Dual-Mode Sankey Flow Math & Conservation of Flow
    - Suite E: Companion Charts Visual Clarity (<= 2 on Overview)
    - Suite F: Light & Dark Theme Adaptability
    - Suite G: Full Regression & Integration Safety Harness

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | Standard Ingestion to Payment Lifecycle | Ingest -> Audit -> Approve -> Pay -> Sankey Lifecycle update | High |
| 2 | Fraud Interception & Payment Blocking | Tampered Invoice -> 9-Point Check -> Flagged -> Blocked -> Sankey Flow | High |
| 3 | Supplier Financial Exposure Analysis | Supplier Flow Mode -> Multi-currency conversion -> Node filtering | Medium |
| 4 | On-Demand Audit Drawer Review | Row click -> Detail modal opens with 9 checks & timeline -> Main table uncluttered | Medium |
| 5 | SEPA XML Batch Generation & Theme Switch | Batch execution -> SEPA pain.001.001.03 export -> Dark/Light mode toggle | Medium |

## Coverage Thresholds
- Tier 1: >=5 test cases per feature
- Tier 2: >=5 boundary and corner cases per feature (e.g., empty state, 100% scam, single invoice, extreme currency amounts)
- Tier 3: pairwise combinations of flow modes, themes, and filter states
- Tier 4: >=5 realistic workflow application scenarios
