"""Rule/report/export behaviour of the generated gate_pass app.

Copied to backend/tests/ by the builder test (after the rule and report bodies have been
written, as the AI would) and run there in a subprocess; not collected by the builder run.
"""

import pytest
from entities.models import GatePass, GatePassLine, TransitionLog

from asb.connector import Unavailable

BODY = {
    "direction": "outbound",
    "vehicle_no": "MH 12 AB 1234",
    "driver": "Ravi",
    "lines": [{"item": "bolt", "quantity": "2.5"}],
}
DN = {"delivery_note_kind": "delivery_note", "delivery_note_id": "DN-1"}


def post(client, **extra):
    return client.post("/api/gate_pass/", {**BODY, **extra}, format="json")


def test_violation_is_400_with_rule_and_rolls_back(api, fake_erp):
    fake_erp.seed("outbound_shipment", "DN-1", {"_state": "draft"})
    resp = post(api("store_user"), **DN)
    assert resp.status_code == 400, resp.content
    assert resp.json() == {"detail": "DN-1 is not submitted", "rule": "R1"}
    assert GatePass.objects.count() == 0
    assert GatePassLine.objects.count() == 0  # nested rows rolled back too


def test_passing_rules_save(api, fake_erp):
    fake_erp.seed("outbound_shipment", "DN-1", {"_state": "submitted"})
    assert post(api("store_user"), **DN).status_code == 201


def test_rules_that_do_not_use_the_erp_never_connect(api):
    # No fake_erp and no connector configured: only a rule that touches erp would fail.
    assert post(api("store_user")).status_code == 201


def test_update_runs_rules(api, fake_erp):
    fake_erp.seed("outbound_shipment", "DN-1", {"_state": "draft"})
    client = api("store_user")
    pk = post(client).json()["id"]
    resp = client.patch(f"/api/gate_pass/{pk}/", DN, format="json")
    assert resp.status_code == 400 and resp.json()["rule"] == "R1"
    assert GatePass.objects.get(pk=pk).delivery_note_id == ""


def test_rules_run_in_model_order(api, monkeypatch):
    seen = []
    monkeypatch.setattr("rules.r1.check", lambda obj, erp: seen.append("R1"))
    monkeypatch.setattr("rules.r2.check", lambda obj, erp: seen.append("R2"))
    assert post(api("store_user")).status_code == 201
    assert seen == ["R1", "R2"]


def test_erp_failures_are_503(api, fake_erp, monkeypatch):
    client = api("store_user")
    resp = post(client, **DN)  # not seeded -> NotFound, not caught by the rule
    assert resp.status_code == 503
    assert resp.json()["detail"].startswith("ERP unavailable:")

    def down(kind, id):
        raise Unavailable("connection refused")

    monkeypatch.setattr(fake_erp, "get", down)
    resp = post(client, **DN)
    assert resp.status_code == 503
    assert resp.json() == {"detail": "ERP unavailable: connection refused"}
    assert GatePass.objects.count() == 0


def test_missing_connector_is_503(api):
    resp = post(api("store_user"), **DN)
    assert resp.status_code == 503
    assert "no connector configured" in resp.json()["detail"]


def test_unimplemented_rule_propagates(api, monkeypatch):
    def stub(obj, erp):
        raise NotImplementedError("R2 not implemented")

    monkeypatch.setattr("rules.r2.check", stub)
    with pytest.raises(NotImplementedError, match="R2 not implemented"):
        post(api("store_user"))


def test_transition_runs_rules_before_the_state_changes(api):
    pk = post(api("store_user")).json()["id"]
    GatePass.objects.filter(pk=pk).update(driver="Blocked")
    assert (
        api("store_user")
        .post(f"/api/gate_pass/{pk}/transition/", {"action": "submit"}, format="json")
        .status_code
        == 400
    )  # rule R2 refuses drivers named Blocked
    assert GatePass.objects.get(pk=pk).state == "draft"
    assert not TransitionLog.objects.exists()


def test_transition_passes_when_rules_pass(api):
    pk = post(api("store_user")).json()["id"]
    resp = api("store_user").post(
        f"/api/gate_pass/{pk}/transition/", {"action": "submit"}, format="json"
    )
    assert resp.status_code == 200 and resp.json()["state"] == "pending_security"


def test_rules_see_required_values_before_saving(api, monkeypatch):
    seen = []
    monkeypatch.setattr("rules.r1.check", lambda obj, erp: seen.append(obj.reason))
    store = api("store_user")
    pk = post(store).json()["id"]
    store.post(f"/api/gate_pass/{pk}/transition/", {"action": "submit"}, format="json")
    resp = api("security").post(
        f"/api/gate_pass/{pk}/transition/",
        {"action": "reject", "reason": "wrong truck"},
        format="json",
    )
    assert resp.status_code == 200
    assert seen[-1] == "wrong truck"


def test_report_endpoint(api):
    store = post(api("store_user"))
    assert store.status_code == 201
    resp = api("security").get("/api/reports/gate_register/?direction=outbound")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["name"] == "gate_register"
    assert body["columns"] == [
        "name", "direction", "vehicle_no", "driver", "gate_time", "state",
    ]  # fmt: skip
    assert body["rows"] == [{"direction": "outbound", "n": 1}]
    assert api("store_user").get("/api/reports/gate_register/").status_code == 403
    assert api("security").get("/api/reports/nope/").status_code == 404
    assert api("manager").get("/api/meta/").json()["reports"] == ["gate_register"]


def test_export_csv(api):
    store = api("store_user")
    assert post(store, driver="=cmd|' /C calc'!A0").status_code == 201
    resp = api("manager").get("/api/gate_pass/export/")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")
    lines = resp.content.decode().splitlines()
    assert lines[0].startswith("id,number,state,direction,")
    assert "'=cmd" in lines[1]  # formula neutralised
    assert "GP-" in lines[1] and "store_user_" in lines[1]
    assert (
        store.get("/api/gate_pass/export/").status_code == 403
    )  # no export permission
    assert api("security").get("/api/gate_pass/export/").status_code == 403
