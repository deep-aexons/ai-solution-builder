from asb.connector import AuthFailed, Unavailable
from entities.models import GatePass

from tests._gp import create, seed


class _Down:
    def __init__(self, exc):
        self.exc = exc

    def get(self, kind, id):
        raise self.exc


def _break(monkeypatch, exc):
    import erp

    monkeypatch.setattr(erp, "get_connector", lambda: _Down(exc))


def test_r1_erp_unavailable_returns_503(api, fake_erp, monkeypatch):
    store = api("store_user")
    _break(monkeypatch, Unavailable("connection refused"))
    resp = create(store)
    assert resp.status_code == 503, resp.content
    assert resp.json()["detail"] == "ERP unavailable: connection refused"
    assert GatePass.objects.count() == 0


def test_r1_auth_failure_returns_503(api, fake_erp, monkeypatch):
    _break(monkeypatch, AuthFailed("bad key"))
    resp = create(api("store_user"))
    assert resp.status_code == 503
    assert resp.json()["detail"].startswith("ERP unavailable:")


def test_r1_cancelled_reference_refused(api, fake_erp):
    seed(fake_erp, "outbound_shipment", "DN-X", _state="cancelled", docstatus=2)
    resp = create(api("store_user"), ref="DN-X")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "outbound_shipment DN-X not found or not submitted"
