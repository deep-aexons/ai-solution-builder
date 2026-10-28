"""Test cases copied into the generated gate_pass backend and run there by pytest.

Not collected by the builder's own pytest run (name does not match test_*.py).
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from entities.models import GatePass, TransitionLog
from rest_framework.test import APIClient

PASS = {
    "direction": "outbound",
    "vehicle_no": "MH 12 AB 1234",
    "driver": "Ravi",
    "lines": [{"item": "bolt", "quantity": "2.5"}],
}


@pytest.fixture(autouse=True)
def _rules_off(monkeypatch):
    """Generated rule stubs raise NotImplementedError until the AI implements them."""
    import rules

    monkeypatch.setattr(rules, "run_rules", lambda obj: None)


@pytest.fixture
def users(db):
    call_command("asb_sync_roles")
    User = get_user_model()
    made = {}
    for name, role in [
        ("store1", "store_user"),
        ("store2", "store_user"),
        ("guard", "security"),
        ("boss", "manager"),
    ]:
        user = User.objects.create_user(name, password="pw-" + name)
        user.groups.add(Group.objects.get(name=role))
        made[name] = user
    return made


def login(name):
    client = APIClient(enforce_csrf_checks=True)
    token = client.get("/api/auth/csrf/").json()["csrfToken"]
    resp = client.post(
        "/api/auth/login/",
        {"username": name, "password": "pw-" + name},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert resp.status_code == 200, resp.content
    client.credentials(HTTP_X_CSRFTOKEN=resp.json()["csrfToken"])
    return client


def make_pass(client, **extra):
    resp = client.post("/api/gate_pass/", {**PASS, **extra}, format="json")
    assert resp.status_code == 201, resp.content
    return resp.json()


def act(client, pk, action, **body):
    return client.post(
        f"/api/gate_pass/{pk}/transition/", {"action": action, **body}, format="json"
    )


def test_unauthenticated_rejected(users):
    resp = APIClient().get("/api/gate_pass/")
    assert resp.status_code in (401, 403)
    assert APIClient().get("/api/meta/").status_code in (401, 403)


def test_login_requires_csrf_token(users):
    client = APIClient(enforce_csrf_checks=True)
    creds = {"username": "store1", "password": "pw-store1"}
    assert client.post("/api/auth/login/", creds, format="json").status_code == 403
    token = client.get("/api/auth/csrf/").json()["csrfToken"]
    resp = client.post(
        "/api/auth/login/", creds, format="json", HTTP_X_CSRFTOKEN="x" * 64
    )
    assert resp.status_code == 403
    resp = client.post("/api/auth/login/", creds, format="json", HTTP_X_CSRFTOKEN=token)
    assert resp.status_code == 200


def test_login_logout(users):
    client = APIClient(enforce_csrf_checks=True)
    token = client.get("/api/auth/csrf/").json()["csrfToken"]
    bad = client.post(
        "/api/auth/login/",
        {"username": "store1", "password": "no"},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert bad.status_code == 400
    good = client.post(
        "/api/auth/login/",
        {"username": "store1", "password": "pw-store1"},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert good.status_code == 200
    body = good.json()
    assert body["username"] == "store1"
    assert body["roles"] == ["store_user"]
    assert "csrftoken" in good.cookies
    assert client.get("/api/gate_pass/").status_code == 200
    client.credentials(HTTP_X_CSRFTOKEN=body["csrfToken"])
    assert client.post("/api/auth/logout/").status_code == 200
    assert client.get("/api/gate_pass/").status_code in (401, 403)
    assert client.get("/api/auth/csrf/").status_code == 200


def test_csrf_enforced_for_session_writes(users):
    client = APIClient(enforce_csrf_checks=True)
    client.login(username="store1", password="pw-store1")
    resp = client.post("/api/gate_pass/", PASS, format="json")
    assert resp.status_code == 403


def test_create_with_nested_lines_and_replace(users):
    client = login("store1")
    made = make_pass(client)
    assert made["state"] == "draft"
    assert made["number"].startswith("GP-")
    assert made["created_by"] == "store1"
    assert [ln["item"] for ln in made["lines"]] == ["bolt"]
    pk = made["id"]
    resp = client.patch(
        f"/api/gate_pass/{pk}/",
        {
            "lines": [
                {"item": "nut", "quantity": "1"},
                {"item": "washer", "quantity": "3"},
            ]
        },
        format="json",
    )
    assert resp.status_code == 200, resp.content
    assert sorted(ln["item"] for ln in resp.json()["lines"]) == ["nut", "washer"]
    assert GatePass.objects.get(pk=pk).lines.count() == 2
    resp = client.patch(f"/api/gate_pass/{pk}/", {"driver": "Sam"}, format="json")
    assert resp.status_code == 200
    assert resp.json()["driver"] == "Sam"
    assert len(resp.json()["lines"]) == 2
    resp = client.patch(f"/api/gate_pass/{pk}/", {"lines": []}, format="json")
    assert resp.json()["lines"] == []


def test_system_fields_are_read_only(users):
    client = login("store1")
    made = make_pass(client, state="approved", number="X-1", created_by="guard")
    assert made["state"] == "draft"
    assert made["number"] != "X-1"
    assert made["created_by"] == "store1"


def test_validation_errors_are_400(users):
    client = login("store1")
    resp = client.post(
        "/api/gate_pass/", {**PASS, "vehicle_no": "bad plate!"}, format="json"
    )
    assert resp.status_code == 400
    assert "vehicle_no" in resp.json()
    resp = client.post(
        "/api/gate_pass/",
        {**PASS, "lines": [{"item": "x", "quantity": "-1"}]},
        format="json",
    )
    assert resp.status_code == 400
    resp = client.post("/api/gate_pass/", {"direction": "outbound"}, format="json")
    assert resp.status_code == 400
    # PATCH must not skip required child fields when rows are replaced.
    pk = make_pass(client)["id"]
    resp = client.patch(
        f"/api/gate_pass/{pk}/", {"lines": [{"item": "no qty"}]}, format="json"
    )
    assert resp.status_code == 400


def test_external_ref_is_flat(users):
    client = login("store1")
    made = make_pass(
        client, delivery_note_kind="delivery_note", delivery_note_id="DN-1"
    )
    assert made["delivery_note_kind"] == "delivery_note"
    assert made["delivery_note_id"] == "DN-1"


def test_manager_reads_but_cannot_create_or_change(users):
    pk = make_pass(login("store1"))["id"]
    boss = login("boss")
    assert boss.get("/api/gate_pass/").status_code == 200
    assert boss.get(f"/api/gate_pass/{pk}/").status_code == 200
    resp = boss.post("/api/gate_pass/", PASS, format="json")
    assert resp.status_code == 403
    assert "detail" in resp.json()
    assert (
        boss.patch(f"/api/gate_pass/{pk}/", {"driver": "z"}, format="json").status_code
        == 403
    )
    assert boss.delete(f"/api/gate_pass/{pk}/").status_code == 403
    assert act(boss, pk, "submit").status_code == 403


def test_child_entities_have_no_endpoint(users):
    assert login("store1").get("/api/gate_pass_line/").status_code == 404


def test_submit_approve_and_log(users):
    store = login("store1")
    guard = login("guard")
    pk = make_pass(store)["id"]
    resp = act(store, pk, "submit")
    assert resp.status_code == 200, resp.content
    assert resp.json()["state"] == "pending_security"
    denied = act(store, pk, "approve")
    assert denied.status_code == 403
    assert "detail" in denied.json()
    assert GatePass.objects.get(pk=pk).state == "pending_security"
    resp = act(guard, pk, "approve")
    assert resp.status_code == 200
    assert resp.json()["state"] == "approved"
    rows = list(TransitionLog.objects.filter(object_id=str(pk)).order_by("id"))
    assert [(r.entity, r.from_state, r.to_state, r.action) for r in rows] == [
        ("gate_pass", "draft", "pending_security", "submit"),
        ("gate_pass", "pending_security", "approved", "approve"),
    ]
    assert rows[1].user.username == "guard"
    assert rows[1].at is not None
    assert rows[1].data == {}
    assert act(guard, pk, "close").status_code == 200


def test_role_checked_before_state(users):
    store = login("store1")
    guard = login("guard")
    pk = make_pass(store)["id"]
    assert act(store, pk, "approve").status_code == 403  # not a store_user action
    assert act(guard, pk, "submit").status_code == 403  # security cannot submit
    assert act(guard, pk, "approve").status_code == 400  # allowed role, wrong state
    assert act(guard, pk, "explode").status_code == 400  # unknown action
    assert TransitionLog.objects.count() == 0
    assert client_post_no_action(guard, pk).status_code == 400


def client_post_no_action(client, pk):
    return client.post(f"/api/gate_pass/{pk}/transition/", {}, format="json")


def test_reject_requires_reason(users):
    store = login("store1")
    guard = login("guard")
    pk = make_pass(store)["id"]
    act(store, pk, "submit")
    resp = act(guard, pk, "reject")
    assert resp.status_code == 400
    assert "reason" in resp.json()["detail"]
    assert resp.json()["fields"] == ["reason"]
    assert act(guard, pk, "reject", reason="").status_code == 400
    assert act(guard, pk, "reject", reason="   ").status_code == 400  # blank is missing
    assert GatePass.objects.get(pk=pk).state == "pending_security"
    assert TransitionLog.objects.filter(action="reject").count() == 0
    resp = act(guard, pk, "reject", reason="wrong truck")
    assert resp.status_code == 200
    assert resp.json()["state"] == "rejected"
    assert resp.json()["reason"] == "wrong truck"
    log = TransitionLog.objects.get(action="reject")
    assert log.data == {"reason": "wrong truck"}


def test_update_own_draft(users):
    owner = login("store1")
    other = login("store2")
    pk = make_pass(owner)["id"]
    assert (
        other.patch(f"/api/gate_pass/{pk}/", {"driver": "x"}, format="json").status_code
        == 403
    )
    assert (
        owner.patch(
            f"/api/gate_pass/{pk}/", {"driver": "mine"}, format="json"
        ).status_code
        == 200
    )
    act(owner, pk, "submit")
    resp = owner.patch(f"/api/gate_pass/{pk}/", {"driver": "late"}, format="json")
    assert resp.status_code == 403
    assert GatePass.objects.get(pk=pk).driver == "mine"
    assert (
        login("guard")
        .patch(f"/api/gate_pass/{pk}/", {"driver": "g"}, format="json")
        .status_code
        == 403
    )


def test_meta_lists_actions_per_role(users):
    def meta(name):
        resp = login(name).get("/api/meta/")
        assert resp.status_code == 200
        return resp.json()

    store = meta("store1")
    assert store["user"]["username"] == "store1"
    assert store["user"]["roles"] == ["store_user"]
    assert store["user"]["actions"]["gate_pass"] == ["submit"]
    assert store["user"]["permissions"]["gate_pass"] == [
        "create",
        "read",
        "update_own_draft",
    ]
    assert meta("guard")["user"]["actions"]["gate_pass"] == [
        "approve",
        "reject",
        "close",
    ]
    assert meta("guard")["user"]["permissions"]["gate_pass"] == ["read", "approve"]
    boss = meta("boss")
    assert boss["user"]["actions"]["gate_pass"] == []
    assert boss["user"]["permissions"]["gate_pass"] == ["read", "export"]
    assert boss["user"]["permissions"]["gate_pass_line"] == ["read", "export"]
    assert store["user"]["actions"].get("gate_pass_line", []) == []
    ents = {e["name"]: e for e in store["entities"]}
    assert set(ents) == {"gate_pass", "gate_pass_line"}
    gp = ents["gate_pass"]
    assert gp["label"] == "Gate Pass"
    assert gp["numbering"] == "GP-{YYYY}-{#####}"
    assert gp["child_of"] is None
    assert ents["gate_pass_line"]["child_of"] == "gate_pass"
    fields = {f["name"]: f for f in gp["fields"]}
    assert fields["direction"]["options"] == ["outbound", "inbound"]
    assert fields["direction"]["required"] is True
    assert fields["delivery_note"]["to"] == ["delivery_note"]
    assert fields["lines"]["type"] == "table"
    assert fields["lines"]["of"] == "gate_pass_line"
    assert set(fields["vehicle_no"]) == {
        "name",
        "type",
        "required",
        "options",
        "to",
        "of",
        "read_only",
    }
    (wf,) = store["workflows"]
    assert wf["entity"] == "gate_pass"
    assert wf["initial"] == "draft"
    assert wf["final_states"] == ["rejected", "closed"]
    assert {
        "from": "pending_security",
        "to": "rejected",
        "action": "reject",
        "roles": ["security"],
        "require": ["reason"],
    } in wf["transitions"]
    assert store["reports"] == []
    assert meta("guard")["reports"] == ["gate_register"]
    assert meta("boss")["reports"] == ["gate_register"]


def test_sync_roles_creates_groups_idempotently(db):
    call_command("asb_sync_roles")
    call_command("asb_sync_roles")
    names = set(Group.objects.values_list("name", flat=True))
    assert names == {"store_user", "security", "manager"}


def test_patch_cannot_write_system_fields(users):
    client = login("store1")
    pk = make_pass(client)["id"]
    resp = client.patch(
        f"/api/gate_pass/{pk}/",
        {"state": "approved", "number": "X-9", "created_by": "guard", "driver": "d2"},
        format="json",
    )
    assert resp.status_code == 200
    obj = GatePass.objects.get(pk=pk)
    assert (obj.state, obj.driver, obj.created_by.username) == ("draft", "d2", "store1")
    assert obj.number == make_number(pk)


def make_number(pk):
    return GatePass.objects.get(pk=pk).number


def test_stale_update_cannot_undo_a_transition(users):
    from api.serializers import build_serializer

    store, guard = login("store1"), login("guard")
    pk = make_pass(store)["id"]
    stale = GatePass.objects.get(pk=pk)  # loaded while still a draft
    act(store, pk, "submit")
    act(guard, pk, "approve")
    ser = build_serializer("gate_pass")(stale, data={"driver": "late"}, partial=True)
    assert ser.is_valid(), ser.errors
    ser.save()
    obj = GatePass.objects.get(pk=pk)
    assert obj.state == "approved"
    assert obj.driver == "late"
    last = TransitionLog.objects.filter(object_id=str(pk)).order_by("id").last()
    assert last.to_state == obj.state
    # and over HTTP the owner can no longer edit the now-approved pass
    resp = store.patch(f"/api/gate_pass/{pk}/", {"driver": "x"}, format="json")
    assert resp.status_code == 403
    assert GatePass.objects.get(pk=pk).state == "approved"


def test_user_without_edit_rights_cannot_change_rows_via_parent(users):
    owner, other, boss = login("store1"), login("store2"), login("boss")
    pk = make_pass(owner)["id"]
    for client in (other, boss):
        resp = client.patch(
            f"/api/gate_pass/{pk}/",
            {"lines": [{"item": "evil", "quantity": "9"}]},
            format="json",
        )
        assert resp.status_code == 403
    assert [r.item for r in GatePass.objects.get(pk=pk).lines.all()] == ["bolt"]


def test_meta_actions_require_read(users):
    from workflow.engine import available_actions

    user = users["store1"]
    assert available_actions(user, "gate_pass") == ["submit"]
    Group.objects.get(name="store_user").user_set.remove(user)
    assert available_actions(user, "gate_pass") == []
