import os

import pytest
from asb_erpnext import from_env

pytestmark = [
    pytest.mark.live_erp,
    pytest.mark.skipif(not os.environ.get("ASB_ERP_URL"), reason="ASB_ERP_URL not set"),
]


def test_list_delivery_notes():
    rows = from_env().list("outbound_shipment", limit=3)
    assert isinstance(rows, list)
