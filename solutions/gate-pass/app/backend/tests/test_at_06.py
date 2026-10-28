import pytest

from tests._gp import act, create, seed

# AT-06: A manager can read and export gate passes but cannot create or change them.
# covers: permissions


@pytest.mark.at("AT-06")
def test_at_06(api, fake_erp):
    seed(fake_erp, "outbound_shipment", "DN-1")
    pk = create(api("store_user")).json()["id"]
    boss = api("manager")

    assert boss.get("/api/gate_pass/").status_code == 200
    assert boss.get(f"/api/gate_pass/{pk}/").status_code == 200
    assert create(boss).status_code == 403
    patch = boss.patch(f"/api/gate_pass/{pk}/", {"driver": "x"}, format="json")
    assert patch.status_code == 403
    assert boss.delete(f"/api/gate_pass/{pk}/").status_code == 403
    for action in ("submit", "approve", "reject", "close"):
        assert act(boss, pk, action, reason="r").status_code == 403, action
    meta = boss.get("/api/meta/").json()["user"]
    assert meta["permissions"]["gate_pass"] == ["read", "export"]
