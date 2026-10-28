"""A recorded ERPNext-shaped sample, used where erpnext.localhost is unreachable.

Shape follows ERPNextConnector.inspect() / list(): field names are the real
Delivery Note and Purchase Receipt fieldnames; rows are made-up samples.
"""

from __future__ import annotations

from typing import Any

VERSION = "15.x (recorded sample)"

DELIVERY_NOTE_FIELDS = [
    "name", "naming_series", "customer", "customer_name", "posting_date",
    "posting_time", "company", "status", "docstatus", "set_warehouse",
    "total_qty", "items", "lr_no", "vehicle_no", "driver_name",
]  # fmt: skip
PURCHASE_RECEIPT_FIELDS = [
    "name", "naming_series", "supplier", "supplier_name", "posting_date",
    "posting_time", "company", "status", "docstatus", "set_warehouse",
    "total_qty", "items", "lr_no", "supplier_delivery_note",
]  # fmt: skip

KINDS: dict[str, Any] = {
    "outbound_shipment": {
        "doctype": "Delivery Note",
        "fields": DELIVERY_NOTE_FIELDS,
    },
    "inbound_receipt": {
        "doctype": "Purchase Receipt",
        "fields": PURCHASE_RECEIPT_FIELDS,
    },
}

ROWS: dict[str, list[dict[str, Any]]] = {
    "outbound_shipment": [
        {"name": "DN-00001", "customer": "Acme Traders", "posting_date": "2026-10-01", "docstatus": 1},
        {"name": "DN-00002", "customer": "Bharat Steel", "posting_date": "2026-10-02", "docstatus": 1},
        {"name": "DN-00003", "customer": "Acme Traders", "posting_date": "2026-10-03", "docstatus": 0},
    ],
    "inbound_receipt": [
        {"name": "PR-00001", "supplier": "Metro Fasteners", "posting_date": "2026-10-01", "docstatus": 1},
        {"name": "PR-00002", "supplier": "Zenith Bearings", "posting_date": "2026-10-02", "docstatus": 1},
        {"name": "PR-00003", "supplier": "Metro Fasteners", "posting_date": "2026-10-03", "docstatus": 2},
    ],
}  # fmt: skip


class FakeConnector:
    """Read-only stand-in returning the recorded sample."""

    def inspect(self) -> dict[str, Any]:
        return {"version": VERSION, "kinds": KINDS}

    def get(self, kind: str, id: str) -> dict[str, Any]:
        for row in ROWS[kind]:
            if row["name"] == id:
                return dict(row)
        raise KeyError(id)

    def list(self, kind, filters=None, fields=None, limit=50):
        return [dict(r) for r in ROWS[kind][:limit]]

    def create_draft(self, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("recorded sample is read-only")
