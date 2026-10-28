import pytest
from entities.models import GatePass, TransitionLog

from tests._gp import act, create, seed

# AT-02: A store_user cannot approve a pending gate pass; a security user can.
# covers: workflow


@pytest.mark.at("AT-02")
def test_at_02(api, fake_erp):
    seed(fake_erp, "outbound_shipment", "DN-1")
    store, guard = api("store_user"), api("security")
    pk = create(store).json()["id"]
    assert act(store, pk, "submit").json()["state"] == "pending_security"

    denied = act(store, pk, "approve")
    assert denied.status_code == 403
    assert GatePass.objects.get(pk=pk).state == "pending_security"

    ok = act(guard, pk, "approve")
    assert ok.status_code == 200, ok.content
    assert ok.json()["state"] == "approved"
    log = TransitionLog.objects.get(action="approve", object_id=str(pk))
    assert (log.from_state, log.to_state) == ("pending_security", "approved")
    assert log.user == guard.user

    assert act(guard, pk, "close").json()["state"] == "closed"
