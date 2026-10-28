# Design review: Gate Pass

| # | Decision | Reason / source |
|---|---|---|
| 1 | Two entities: `gate_pass` with child `gate_pass_line` (item, quantity) | Spec §14 (entities); lines as a `table` field keeps the pass one document |
| 2 | Two external references (`delivery_note`, `purchase_receipt`), both read-only and neutral kinds `outbound_shipment` / `inbound_receipt` | Spec §14 ("reads Delivery Notes and Purchase Receipts, no ERP writes"); spec §5 (neutral kinds); discovery.md: both kinds found, 15 and 14 fields, 3 sample records each |
| 3 | Workflow draft -> pending_security -> approved / rejected -> closed; finals rejected, closed | Spec §14 |
| 4 | `reject` requires `reason` | Requirements must-have 4; AT-04 |
| 5 | Only security approves, rejects and closes; store_user submits | Requirements "Users and roles"; AT-02 |
| 6 | Manager has read and export only | Requirements must-have 5; AT-06 |
| 7 | R1 uses the ERP document state (`_state == submitted`); a cancelled or missing document is refused the same way. R1 and R2 apply only while the pass is a draft (create, edit, submit); once pending with security, the ERP is not consulted, so security can always approve, reject or close, even if the reference was cancelled or the ERP is down | Spec §14 R1; `docstatus` is listed on both kinds in discovery.md (recorded sample) and mapped to `_state` by the ERPNext connector (`connectors/erpnext/asb_erpnext/mapping.yaml`: 0 draft, 1 submitted, 2 cancelled) |
| 8 | R2 compares per item against the sum of the document's item rows (not cumulative across passes) | Spec §14 R2; requirements open question 2 |
| 9 | Vehicle number pattern `^[A-Z0-9 -]+$` | Requirements open question 4 (assumption) |
| 10 | Numbering `GP-{YYYY}-{#####}` | Spec §5 (each entity carries a numbering pattern); the pattern itself (`{YYYY}` year, `{#####}` zero-padded yearly sequence, prefix GP) is our proposal, to confirm with the client |

## Risks and open questions

- Discovery was produced offline from a recorded ERPNext sample; re-run `asb discover gate-pass` against erpnext.localhost and re-check that the item child-table (`items` with `item_code`, `qty`) exists as assumed by R2.
- Cumulative quantity across several passes for one document is not enforced (requirements open question 2).
- Who may close a pass (security assumed) to be confirmed with the client.
- R1/R2 timing: rules are evaluated only while the pass is a draft. An ERP document cancelled after the pass was submitted is therefore not re-checked; security sees the pass and may reject it. Accepted so that a pending pass can never get stuck behind an ERP problem.
- Known limitation of R2: items are matched on the exact `item_code` text of the pass line against the document's `items[].item_code`, and the quantity compared is the transaction `qty` (not stock UOM `stock_qty`), so a pass in another unit of measure or with a differently spelled item code is refused or mis-compared. Not cumulative across passes either.
