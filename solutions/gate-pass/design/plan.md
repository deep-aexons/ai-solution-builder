# Build plan: Gate Pass

1. `asb validate gate-pass` clean; approve the design (records version and hash).
2. `asb build gate-pass`: generates models, serializers, workflow engine, API, permission matrix, React UI, tests, and AI-owned stubs `rules/r1.py`, `rules/r2.py`, `reports/gate_register.py`.
3. Implement R1 (`rules/r1.py`): map the pass direction to the reference (outbound -> delivery_note -> outbound_shipment, inbound -> purchase_receipt -> inbound_receipt); read it through the connector; refuse unless `_state == "submitted"`. ERP outages propagate and become 503.
4. Implement R2 (`rules/r2.py`): per item, sum of pass quantities must not exceed the sum of the document's `items` quantities.
5. Implement the report (`reports/gate_register.py`): filters date_from/date_to, direction, state; ordered by gate time descending.
6. Write AT-01..AT-06 tests with `@pytest.mark.at(...)`, plus ERP failure tests (503 unavailable, cancelled document refused).
7. `asb check`, then `asb verify gate-pass` (max 3 fix rounds); commit the report.
8. Out of build scope: client approval, staging and go-live (stage 6).
