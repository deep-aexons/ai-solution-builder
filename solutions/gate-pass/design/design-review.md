# Design review: Gate Pass

| # | Decision | Reason / source |
|---|---|---|
| 1 | Two entities: `gate_pass` with child `gate_pass_line` (item, quantity) | Spec §14 (entities); lines as a `table` field keeps the pass one document |
| 2 | Two external references (`delivery_note`, `purchase_receipt`), both read-only and neutral kinds `outbound_shipment` / `inbound_receipt` | Spec §14 ("reads Delivery Notes and Purchase Receipts, no ERP writes"); spec §5 (neutral kinds); discovery.md: both kinds found, 15 and 14 fields, 3 sample records each |
| 3 | Workflow draft -> pending_security -> approved / rejected -> closed; finals rejected, closed | Spec §14 |
| 4 | `reject` requires `reason` | Requirements must-have 4; AT-04 |
| 5 | Only security approves, rejects and closes; store_user submits | Requirements "Users and roles"; AT-02 |
| 6 | Manager has read and export only | Requirements must-have 5; AT-06 |
| 7 | R1 uses the ERP document state (`_state == submitted`); a cancelled or missing document is refused the same way | Spec §14 R1; discovery.md: docstatus is available on both kinds |
| 8 | R2 compares per item against the sum of the document's item rows (not cumulative across passes) | Spec §14 R2; requirements open question 2 |
| 9 | Vehicle number pattern `^[A-Z0-9 -]+$` | Requirements open question 4 (assumption) |
| 10 | Numbering `GP-{YYYY}-{#####}` | Client numbering convention for gate passes |

## Risks and open questions

- Discovery was produced offline from a recorded ERPNext sample; re-run `asb discover gate-pass` against erpnext.localhost and re-check that the item child-table (`items` with `item_code`, `qty`) exists as assumed by R2.
- Cumulative quantity across several passes for one document is not enforced (requirements open question 2).
- Who may close a pass (security assumed) to be confirmed with the client.
- R1/R2 timing: the generated app evaluates rules on every create, edit and transition, so an ERP document cancelled after submit also blocks approve and close. Judged safe (a cancelled document should not pass the gate); revisit if the client disagrees.
