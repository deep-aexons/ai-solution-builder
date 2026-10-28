import json

import httpx
import pytest
from asb_erpnext import ERPNextConnector, from_env

from asb.connector import (
    AuthFailed,
    Connector,
    ConnectorError,
    NotFound,
    Unavailable,
    WriteNotApproved,
)


def make(handler, **kw):
    kw.setdefault("sleep", lambda s: None)
    return ERPNextConnector(
        "http://erp.test/",
        "key",
        "secret",
        transport=httpx.MockTransport(handler),
        **kw,
    )


def test_protocol_and_repr_hides_secret():
    c = make(lambda r: httpx.Response(200, json={"data": {}}))
    assert isinstance(c, Connector)
    assert "secret" not in repr(c)


def test_get_maps_state_keeps_items_and_sends_auth():
    seen = {}

    def h(req):
        seen["url"] = str(req.url)
        seen["auth"] = req.headers["authorization"]
        return httpx.Response(
            200,
            json={
                "data": {"name": "DN-1", "docstatus": 1, "items": [{"item_code": "A"}]}
            },
        )

    rec = make(h).get("outbound_shipment", "DN 1")
    assert rec["_state"] == "submitted"
    assert rec["items"] == [{"item_code": "A"}]
    assert seen["url"] == "http://erp.test/api/resource/Delivery%20Note/DN%201"
    assert seen["auth"] == "token key:secret"


def test_list_passes_filters_fields_limit():
    seen = {}

    def h(req):
        seen.update(req.url.params)
        return httpx.Response(
            200, json={"data": [{"name": "A", "docstatus": 0}, {"name": "B"}]}
        )

    rows = make(h).list("customer", {"status": "Open"}, limit=5)
    assert json.loads(seen["filters"]) == [["status", "=", "Open"]]
    assert json.loads(seen["fields"]) == ["name"]
    assert seen["limit_page_length"] == "5"
    assert rows[0]["_state"] == "draft"
    assert "_state" not in rows[1]


def test_list_passes_list_filters_through():
    seen = {}

    def h(req):
        seen.update(req.url.params)
        return httpx.Response(200, json={"data": []})

    make(h).list("item", [["a", ">", 1]], fields=["name", "a"])
    assert json.loads(seen["filters"]) == [["a", ">", 1]]
    assert json.loads(seen["fields"]) == ["name", "a"]


@pytest.mark.parametrize("code", [401, 403])
def test_auth_failed(code):
    with pytest.raises(AuthFailed):
        make(lambda r: httpx.Response(code)).get("item", "x")


def test_not_found():
    with pytest.raises(NotFound):
        make(lambda r: httpx.Response(404)).get("item", "x")


def test_other_4xx_carries_server_message():
    h = lambda r: httpx.Response(417, json={"exception": "ValidationError: bad"})
    with pytest.raises(ConnectorError, match="bad"):
        make(h).get("item", "x")


def test_retry_then_success():
    calls = []

    def h(req):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": {"name": "x"}})

    sleeps = []
    assert make(h, sleep=sleeps.append).get("item", "x")["name"] == "x"
    assert len(calls) == 3
    assert sleeps == [0.5, 1.0]


def test_two_503_then_200_is_success():
    calls = []

    def h(req):
        calls.append(1)
        return (
            httpx.Response(503)
            if len(calls) < 2
            else httpx.Response(200, json={"data": {}})
        )

    make(h).get("item", "x")
    assert len(calls) == 2


def test_three_503_unavailable():
    calls = []

    def h(req):
        calls.append(1)
        return httpx.Response(503)

    with pytest.raises(Unavailable):
        make(h).get("item", "x")
    assert len(calls) == 3


def test_connect_error_retried_then_unavailable():
    calls = []

    def h(req):
        calls.append(1)
        raise httpx.ConnectError("down")

    with pytest.raises(Unavailable):
        make(h).list("item")
    assert len(calls) == 3


def test_create_draft_without_approval_sends_nothing():
    calls = []
    c = make(lambda r: calls.append(r) or httpx.Response(200, json={"data": {}}))
    with pytest.raises(WriteNotApproved):
        c.create_draft("outbound_shipment", {"customer": "C"})
    assert calls == []


def test_create_draft_strips_and_posts():
    seen = {}

    def h(req):
        seen["method"] = req.method
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"data": {"name": "DN-9", "docstatus": 0}})

    c = make(h, allowed_writes={"write:outbound_shipment"})
    out = c.create_draft(
        "outbound_shipment", {"customer": "C", "docstatus": 1, "name": "X"}
    )
    assert seen["method"] == "POST"
    assert seen["body"] == {"customer": "C"}
    assert out["_state"] == "draft"


def test_post_503_not_retried_but_connect_error_is():
    calls = []

    def h(req):
        calls.append(1)
        return httpx.Response(503)

    c = make(h, allowed_writes={"write:item"})
    with pytest.raises(Unavailable):
        c.create_draft("item", {})
    assert len(calls) == 1

    calls.clear()

    def h2(req):
        calls.append(1)
        raise httpx.ConnectError("down")

    c = make(h2, allowed_writes={"write:item"})
    with pytest.raises(Unavailable):
        c.create_draft("item", {})
    assert len(calls) == 3


def test_unknown_kind_names_known_kinds():
    c = make(lambda r: httpx.Response(200, json={"data": {}}))
    with pytest.raises(ConnectorError, match="outbound_shipment") as e:
        c.get("bogus", "x")
    assert not isinstance(e.value, NotFound)


def test_inspect():
    def h(req):
        p = req.url.path
        if p.endswith("get_versions"):
            return httpx.Response(
                200, json={"message": {"frappe": {"version": "15.1.0"}}}
            )
        if req.url.params["doctype"] == "Customer":
            return httpx.Response(404)
        return httpx.Response(
            200,
            json={
                "message": {
                    "docs": [{"fields": [{"fieldname": "a"}, {"fieldname": "b"}]}]
                }
            },
        )

    out = make(h).inspect()
    assert out["version"] == "15.1.0"
    assert out["kinds"]["item"] == {"doctype": "Item", "fields": ["a", "b"]}
    assert out["kinds"]["customer"]["fields"] == []
    assert "error" in out["kinds"]["customer"]


def test_inspect_version_unknown_on_failure():
    def h(req):
        if req.url.path.endswith("get_versions"):
            return httpx.Response(500)
        return httpx.Response(200, json={"message": {"docs": [{"fields": []}]}})

    assert make(h).inspect()["version"] == "unknown"


def test_from_env(monkeypatch):
    for v in ("ASB_ERP_URL", "ASB_ERP_API_KEY", "ASB_ERP_API_SECRET"):
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(ConnectorError, match="ASB_ERP_URL"):
        from_env()
    monkeypatch.setenv("ASB_ERP_URL", "http://x")
    monkeypatch.setenv("ASB_ERP_API_KEY", "k")
    with pytest.raises(ConnectorError, match="ASB_ERP_API_SECRET"):
        from_env()
    monkeypatch.setenv("ASB_ERP_API_SECRET", "s")
    assert isinstance(from_env(), ERPNextConnector)
    assert isinstance(ERPNextConnector.from_env(), ERPNextConnector)
