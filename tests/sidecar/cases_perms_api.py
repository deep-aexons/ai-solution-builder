"""Permission-semantics cases run inside a generated mini backend (see builder test)."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from rest_framework.test import APIClient


@pytest.fixture
def users(db):
    call_command("asb_sync_roles")
    User = get_user_model()
    for name, role in [("ann", "author"), ("bob", "author"), ("ed", "editor")]:
        u = User.objects.create_user(name, password="pw")
        u.groups.add(Group.objects.get(name=role))
    # Superusers get no bypass: roles come only from groups.
    User.objects.create_superuser("root", password="pw")


def login(name):
    c = APIClient()
    assert (
        c.post(
            "/api/auth/login/", {"username": name, "password": "pw"}, format="json"
        ).status_code
        == 200
    )
    return c


def act(c, pk, action):
    return c.post(f"/api/doc/{pk}/transition/", {"action": action}, format="json")


def test_non_initial_transition_needs_approve(users):
    ann = login("ann")
    pk = ann.post("/api/doc/", {"title": "t"}, format="json").json()["id"]
    assert act(ann, pk, "submit").status_code == 200
    # author is in the finish roles but lacks `approve`
    assert act(ann, pk, "finish").status_code == 403
    assert act(login("ed"), pk, "finish").status_code == 200


def test_update_allowed_in_non_final_state_only(users):
    ann, ed = login("ann"), login("ed")
    pk = ann.post("/api/doc/", {"title": "t"}, format="json").json()["id"]
    assert ed.patch(f"/api/doc/{pk}/", {"note": "d"}, format="json").status_code == 200
    act(ann, pk, "submit")
    assert ed.patch(f"/api/doc/{pk}/", {"note": "r"}, format="json").status_code == 200
    act(ed, pk, "finish")
    assert ed.patch(f"/api/doc/{pk}/", {"note": "x"}, format="json").status_code == 403


def test_delete_only_in_initial_state(users):
    ann, ed = login("ann"), login("ed")
    a = ann.post("/api/doc/", {"title": "a"}, format="json").json()["id"]
    b = ann.post("/api/doc/", {"title": "b"}, format="json").json()["id"]
    act(ann, b, "submit")
    assert ann.delete(f"/api/doc/{b}/").status_code == 403
    assert ed.delete(f"/api/doc/{b}/").status_code == 403
    assert ann.delete(f"/api/doc/{a}/").status_code == 204


def test_no_superuser_bypass(users):
    root = login("root")
    assert root.get("/api/doc/").status_code == 403
    assert root.post("/api/doc/", {"title": "t"}, format="json").status_code == 403
    meta = root.get("/api/meta/").json()
    assert meta["user"]["roles"] == []
    assert meta["user"]["actions"]["doc"] == []


def test_entity_without_workflow(users):
    ann, bob, ed = login("ann"), login("bob"), login("ed")
    resp = ann.post("/api/note/", {"text": "hi"}, format="json")
    assert resp.status_code == 201
    body = resp.json()
    assert "state" not in body
    pk = body["id"]
    assert (
        bob.patch(f"/api/note/{pk}/", {"text": "x"}, format="json").status_code == 403
    )
    assert (
        ann.patch(f"/api/note/{pk}/", {"text": "mine"}, format="json").status_code
        == 200
    )
    assert ed.get(f"/api/note/{pk}/").status_code == 200
    assert ed.delete(f"/api/note/{pk}/").status_code == 403
    resp = ann.post(f"/api/note/{pk}/transition/", {"action": "x"}, format="json")
    assert resp.status_code == 400
    assert ann.delete(f"/api/note/{pk}/").status_code == 204
