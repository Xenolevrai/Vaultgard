Invoice Audit & Payment Dashboard: Functionalities
1. Invoice status model
Received / New: just ingested, no checks run yet
Pending verification: in the audit queue
Under review: assigned to an auditor
Flagged / Suspicious: fraud indicators detected
Rejected / Confirmed scam: blocked, cannot be paid
Verified & approved: audited and clean
Ready to pay: approved, due date reached or approaching
Scheduled: payment date set
Paid: with payment reference
On hold / Disputed: waiting on supplier or internal clarification
2. Main overview (KPIs)
Count and total amount per status
Amount ready to pay today / this week / this month
Amount pending verification and its oldest item
Number of flagged invoices and estimated amount at risk
Average verification time
Overdue invoices (past due date, not paid)
Trend charts over time, by status or supplier
3. Invoice list and search
Sortable table with invoice number, supplier, amount, currency, issue date, due date, status, assignee
Color-coded status badges and risk score column
Search by invoice number, supplier, amount, or PO number
Filters: status, supplier, date range, amount range, risk level, department, assignee, payment method
Saved filters and custom views (e.g. “Ready to pay this week”)
Bulk selection and bulk actions
Export to CSV / Excel / PDF
4. Audit and fraud checks (per invoice)
Supplier validation: supplier exists in the approved vendor list, tax ID / VAT number valid, company registration check
Bank details check: IBAN matches the one on file, alert if the bank account changed recently
Duplicate detection: same number, amount, supplier, or date
Three-way match: invoice vs purchase order vs goods received / delivery note
Amount checks: unusual amount, round numbers, amounts just under approval thresholds
Document checks: signs of tampering, metadata anomalies, missing mandatory fields (VAT, legal mentions)
Email / sender check: spoofed domain, lookalike addresses
Anomaly detection: behavior that deviates from the supplier’s history
Sanctions / blacklist screening
Risk score (low / medium / high) with the reasons listed
Checklist showing which checks passed, failed, or are still pending
5. Invoice detail page
Original document viewer (PDF/image) next to extracted data
Full timeline: received, checked, reviewed, approved, paid
Audit results and risk breakdown
Linked documents: PO, contract, delivery receipt, supplier history
Internal comments and @mentions
Attachments (supplier replies, proof of verification)
6. Workflow and actions
Assign to an auditor
Approve, reject, or flag as suspicious
Request more information from the supplier
Escalate to a manager or fraud team
Put on hold or release
Mark as “verified by phone / callback” with notes
Multi-level approval based on amount thresholds
Approve and schedule payment in one step
7. Payment management
“Ready to pay” queue, only containing audited and approved invoices
Payment blocking rules (cannot pay flagged, unverified, or duplicate invoices)
Payment batch creation (e.g. SEPA file export)
Scheduling by due date or early-payment discount
Payment status tracking and confirmation, with bank reconciliation
Partial payments and credit notes handling
Cash-flow forecast of upcoming payments
8. Supplier view
Supplier profile with verification status
History of invoices, payments, and flags
Bank detail change log
Supplier risk rating
Whitelist / blacklist management
9. Alerts and notifications
New high-risk invoice detected
Invoice stuck in verification beyond a set time (SLA breach)
Upcoming due dates and late payments
Bank detail change detected
Duplicate invoice detected
Email, in-app, Slack, or Teams notifications
Daily or weekly digest
10. Roles and permissions
Roles: viewer, auditor, approver, payer, admin
Segregation of duties (the person who approves cannot also pay)
Access limited by entity, department, or amount
11. Audit trail and compliance
Immutable log of every action (who, what, when)
Version history of invoice data
Evidence retention for audits
Exportable compliance reports
GDPR and data retention settings
12. Reporting and analytics
Fraud attempts caught and money saved
Verification turnaround time by auditor or supplier
Payment performance (on time vs late)
Top suppliers by volume or risk
Scheduled and custom reports
13. Integrations and ingestion
Email inbox ingestion, upload, or API
OCR extraction of invoice data
ERP / accounting sync (SAP, Oracle, QuickBooks, Sage, etc.)
Bank / payment provider integration
VAT / company registry lookups
Webhooks and REST API
14. Settings and admin
Configurable risk rules and thresholds
Custom statuses and workflows
Approval matrices
Notification preferences
Multi-language and multi-currency support
Dark mode, responsive and mobile-friendly UI
