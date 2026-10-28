import datetime

import pytest
from entities.models import GatePass

# AT-05: The gate register can be filtered by direction and date range.
# covers: gate_register

UTC = datetime.timezone.utc


def _pass(number_hint, direction, day, hour=10, state="approved"):
    return GatePass.objects.create(
        direction=direction,
        vehicle_no=f"V {number_hint}",
        driver="d",
        gate_time=datetime.datetime(2026, 10, day, hour, 0, tzinfo=UTC),
        state=state,
    )


@pytest.fixture
def seeded(db):
    _pass(1, "outbound", 18)
    _pass(2, "inbound", 19, state="rejected")
    _pass(3, "outbound", 20, hour=8)
    _pass(4, "outbound", 20, hour=15, state="closed")
    GatePass.objects.create(direction="inbound", vehicle_no="V 5", driver="d")  # no time


def run(client, **params):
    resp = client.get("/api/reports/gate_register/", params)
    assert resp.status_code == 200, resp.content
    return resp.json()


@pytest.mark.at("AT-05")
def test_at_05(api, seeded):
    guard = api("security")
    everything = run(guard)
    assert everything["columns"] == [
        "name", "direction", "vehicle_no", "driver", "gate_time", "state",
    ]  # fmt: skip
    # newest gate time first; a pass without a gate time goes last
    assert [r["vehicle_no"] for r in everything["rows"]] == [
        "V 4", "V 3", "V 2", "V 1", "V 5",
    ]  # fmt: skip

    out = run(guard, direction="outbound")["rows"]
    assert {r["direction"] for r in out} == {"outbound"}
    assert len(out) == 3

    window = run(guard, date_from="2026-10-19", date_to="2026-10-20")["rows"]
    assert [r["vehicle_no"] for r in window] == ["V 4", "V 3", "V 2"]

    both = run(guard, direction="outbound", date_from="2026-10-20")["rows"]
    assert [r["vehicle_no"] for r in both] == ["V 4", "V 3"]
    assert [r["vehicle_no"] for r in run(guard, date_to="2026-10-18")["rows"]] == ["V 1"]


@pytest.mark.at("AT-05")
def test_at_05_state_filter_and_access(api, seeded):
    rejected = run(api("manager"), state="rejected")["rows"]
    assert [r["vehicle_no"] for r in rejected] == ["V 2"]
    assert api("store_user").get("/api/reports/gate_register/").status_code == 403
    bad = api("security").get("/api/reports/gate_register/", {"date_from": "soon"})
    assert bad.status_code == 400
