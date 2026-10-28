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
    assert act(guard, pk, "reject", reason="   ").status_code == 400  # blank
    assert GatePass.objects.get(pk=pk).state == "pending_security"

    ok = act(guard, pk, "reject", reason="Seal number does not match")
    assert ok.status_code == 200, ok.content
    assert ok.json()["state"] == "rejected"
    assert GatePass.objects.get(pk=pk).reason == "Seal number does not match"


def _pending(api, fake_erp):
    seed(fake_erp, "outbound_shipment", "DN-1")
    store, guard = api("store_user"), api("security")
    pk = create(store).json()["id"]
    assert act(store, pk, "submit").status_code == 200
    return guard, pk


@pytest.mark.at("AT-04")
def test_at_04_reject_works_after_reference_cancelled(api, fake_erp):
    guard, pk = _pending(api, fake_erp)
    fake_erp.records["outbound_shipment"]["DN-1"].update(_state="cancelled")
    resp = act(guard, pk, "reject", reason="Document cancelled")
    assert resp.status_code == 200, resp.content
    assert resp.json()["state"] == "rejected"


@pytest.mark.at("AT-04")
def test_at_04_approve_and_close_do_not_need_the_erp(api, fake_erp):
    guard, pk = _pending(api, fake_erp)
    fake_erp.records["outbound_shipment"]["DN-1"].update(_state="cancelled")
    assert act(guard, pk, "approve").status_code == 200
    assert act(guard, pk, "close").json()["state"] == "closed"


@pytest.mark.at("AT-04")
def test_at_04_erp_down_does_not_block_reject(api, fake_erp, monkeypatch):
    import erp

    from asb.connector import Unavailable

    guard, pk = _pending(api, fake_erp)

    class Down:
        def get(self, kind, id):
            raise Unavailable("connection refused")

    monkeypatch.setattr(erp, "get_connector", lambda: Down())
    resp = act(guard, pk, "reject", reason="ERP is down, sending back")
    assert resp.status_code == 200, resp.content
    assert resp.json()["state"] == "rejected"
