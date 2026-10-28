# Discovery — gate_pass

> **Offline discovery from a recorded ERPNext sample** — re-run `asb discover gate-pass` on the Mac against erpnext.localhost (needs ASB_ERP_URL/KEY/SECRET).
> Generated with `asb.discover.discover()` and `tests/e2e/fixtures/recorded_erpnext.py`; the live ERP was unreachable from this environment.

## Connection

System version: 15.x (recorded sample)

## External data

| Name | Kind | System document | Fields available | Sample records | Status |
|---|---|---|---|---|---|
| delivery_note | outbound_shipment | Delivery Note | 15 | 3 | ok |
| purchase_receipt | inbound_receipt | Purchase Receipt | 14 | 3 | ok |

## Write access requested

None — read only

## Gaps

None

## Notes for design

Design only against external data marked ok; treat each gap as a requirement to resolve with the client before relying on it.
