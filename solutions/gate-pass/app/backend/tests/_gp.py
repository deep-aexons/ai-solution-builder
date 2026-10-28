# AI-owned helpers for the gate pass tests (not collected: name does not start with test_).
SUBMITTED = {
    "_state": "submitted",
    "docstatus": 1,
    "items": [{"item_code": "BOLT", "qty": 10}, {"item_code": "NUT", "qty": 4}],
}


def seed(fake_erp, kind, doc_id, **over):
    fake_erp.seed(kind, doc_id, {**SUBMITTED, **over})


def body(direction="outbound", ref="DN-1", lines=None, **extra):
    data = {
        "direction": direction,
        "vehicle_no": "MH 12 AB 1234",
        "driver": "Ravi",
        "gate_time": "2026-10-20T09:30:00Z",
        "lines": lines if lines is not None else [{"item": "BOLT", "quantity": "5"}],
    }
    if direction == "outbound":
        data.update(delivery_note_kind="delivery_note", delivery_note_id=ref)
    else:
        data.update(purchase_receipt_kind="purchase_receipt", purchase_receipt_id=ref)
    data.update(extra)
    return data


def create(client, **kw):
    return client.post("/api/gate_pass/", body(**kw), format="json")


def act(client, pk, action, **data):
    return client.post(
        f"/api/gate_pass/{pk}/transition/", {"action": action, **data}, format="json"
    )
