# Connector interface

A connector lets a generated solution reach an ERP in a platform-neutral way. Every
connector implements `asb.connector.Connector` and maps neutral kinds (for example
`outbound_shipment`) to the system's own document names in its `connector.yaml`.

| Operation | Notes |
|---|---|
| `inspect()` | Kinds available, their fields and state semantics, version, installed modules |
| `get(kind, id)` / `list(kind, filters, fields, limit)` | Read live data; never copied into the sidecar except the reference |
| `create_draft(kind, data)` | Only for operations listed as `write:<operation>` in the approved model |
| delete / submit / cancel | Not part of the contract |

Signatures:

- `inspect() -> dict`: `{"version": str, "kinds": {kind: {"document": <system document name>, "fields": [names], "error"?: str}}}`
- `get(kind: str, id: str) -> dict`
- `list(kind: str, filters: dict | None = None, fields: list[str] | None = None, limit: int = 50) -> list[dict]`
- `create_draft(kind: str, data: dict) -> dict`

## Errors

All derive from `ConnectorError`.

| Error | Meaning |
|---|---|
| `NotFound` | The document or kind does not exist |
| `Unavailable` | The system is unreachable or failed transiently (reads are retried first) |
| `AuthFailed` | Credentials are missing or rejected |
| `WriteNotApproved` | A write was attempted that the approved model does not allow |

## Credentials

Only from environment variables: `ASB_ERP_URL`, `ASB_ERP_API_KEY`, `ASB_ERP_API_SECRET`.

## Descriptor

`connector.yaml` keys: `name`, `entry` (importable package in the connector folder), `kinds`
(neutral kind to the system's document name).
