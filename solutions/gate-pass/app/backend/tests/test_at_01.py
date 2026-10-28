import pytest
from entities.models import GatePass

from tests._gp import create, seed

# AT-01: A gate pass whose referenced document is still a draft in the ERP is refused.
# covers: R1


@pytest.mark.at("AT-01")
def test_at_01(api, fake_erp):
    store = api("store_user")
    seed(fake_erp, "outbound_shipment", "DN-DRAFT", _state="draft", docstatus=0)
    resp = create(store, ref="DN-DRAFT")
    assert resp.status_code == 400, resp.content
    assert resp.json()["rule"] == "R1"
    assert resp.json()["detail"] == "outbound_shipment DN-DRAFT not found or not submitted"
    assert GatePass.objects.count() == 0  # refused, nothing saved

    seed(fake_erp, "outbound_shipment", "DN-OK")
    assert create(store, ref="DN-OK").status_code == 201


@pytest.mark.at("AT-01")
def test_at_01_unknown_and_wrong_kind(api, fake_erp):
    store = api("store_user")
    resp = create(store, ref="DN-MISSING")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "outbound_shipment DN-MISSING not found or not submitted"
    # an outward pass must reference a delivery note, not a purchase receipt
    bad = {"delivery_note_kind": "", "delivery_note_id": ""}
    resp = create(store, ref="PR-1", **bad)
    assert resp.status_code == 400
    assert resp.json()["rule"] == "R1"


@pytest.mark.at("AT-01")
def test_at_01_inbound_uses_purchase_receipt(api, fake_erp):
    store = api("store_user")
    seed(fake_erp, "inbound_receipt", "PR-DRAFT", _state="draft")
    resp = create(store, direction="inbound", ref="PR-DRAFT")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "inbound_receipt PR-DRAFT not found or not submitted"
    seed(fake_erp, "inbound_receipt", "PR-OK")
    assert create(store, direction="inbound", ref="PR-OK").status_code == 201
