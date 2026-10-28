import pytest
from entities.models import GatePass

from tests._gp import act, create, seed

# AT-04: Rejecting a pending gate pass requires a reason.
# covers: workflow:reject


@pytest.mark.at("AT-04")
def test_at_04(api, fake_erp):
    seed(fake_erp, "outbound_shipment", "DN-1")
    store, guard = api("store_user"), api("security")
    pk = create(store).json()["id"]
    act(store, pk, "submit")

    resp = act(guard, pk, "reject")
    assert resp.status_code == 400
    assert resp.json()["fields"] == ["reason"]
    assert act(guard, pk, "reject", reason="").status_code == 400
    assert GatePass.objects.get(pk=pk).state == "pending_security"

    ok = act(guard, pk, "reject", reason="Seal number does not match")
    assert ok.status_code == 200, ok.content
    assert ok.json()["state"] == "rejected"
    assert GatePass.objects.get(pk=pk).reason == "Seal number does not match"
