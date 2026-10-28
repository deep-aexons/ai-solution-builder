import pytest

from tests._gp import act, create, seed

# AT-03: A gate pass line quantity above the referenced quantity is refused.
# covers: R2


@pytest.mark.at("AT-03")
def test_at_03(api, fake_erp):
    seed(fake_erp, "outbound_shipment", "DN-1")  # BOLT 10, NUT 4
    store = api("store_user")
    over = create(store, lines=[{"item": "BOLT", "quantity": "11"}])
    assert over.status_code == 400, over.content
    assert over.json()["rule"] == "R2"
    assert "BOLT" in over.json()["detail"]

    exact = create(store, lines=[{"item": "BOLT", "quantity": "10"}])
    assert exact.status_code == 201, exact.content


@pytest.mark.at("AT-03")
def test_at_03_lines_are_summed_per_item(api, fake_erp):
    seed(fake_erp, "outbound_shipment", "DN-1")
    store = api("store_user")
    split = [{"item": "BOLT", "quantity": "6"}, {"item": "BOLT", "quantity": "5"}]
    resp = create(store, lines=split)
    assert resp.status_code == 400
    assert "BOLT" in resp.json()["detail"]
    other = create(store, lines=[{"item": "WASHER", "quantity": "1"}])
    assert other.status_code == 400  # not on the document at all
    assert "WASHER" in other.json()["detail"]


@pytest.mark.at("AT-03")
def test_at_03_edit_and_submit_are_rechecked(api, fake_erp):
    seed(fake_erp, "outbound_shipment", "DN-1")
    store = api("store_user")
    pk = create(store).json()["id"]
    resp = store.patch(
        f"/api/gate_pass/{pk}/",
        {"lines": [{"item": "NUT", "quantity": "5"}]},
        format="json",
    )
    assert resp.status_code == 400
    assert "NUT" in resp.json()["detail"]
    assert act(store, pk, "submit").status_code == 200
