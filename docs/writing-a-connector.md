# Writing a connector

A connector lets a generated solution (and `asb discover`) reach a business system without the core knowing which one. The example is `connectors/erpnext/`; the neutral contract is `connectors/interface.md` and `core/tool/asb/connector.py`.

## Layout

```
connectors/<name>/
  connector.yaml
  <entry>/          importable package: __init__.py, client code, mapping.yaml
  knowledge/        notes about the system (used by sub-project 2)
```

## `connector.yaml`

```yaml
name: erpnext
entry: asb_erpnext        # importable package in this folder
kinds:                    # neutral kind -> the system's own document name
  outbound_shipment: Delivery Note
  inbound_receipt: Purchase Receipt
```

Kinds are snake_case (`^[a-z][a-z0-9_]*$`). Models and skills use the neutral kind, never the system's document name.

## The protocol

Implement `asb.connector.Connector` (a `typing.Protocol`):

| Method | Contract |
|---|---|
| `inspect() -> dict` | `{"version": str, "kinds": {kind: {"document": <system name>, "fields": [names], "error"?: str}}}`. Discovery builds `discovery.md` from this; a kind with `error` or no fields becomes a gap |
| `get(kind, id) -> dict` | One record. Raise `NotFound` if absent |
| `list(kind, filters=None, fields=None, limit=50) -> list[dict]` | Live read |
| `create_draft(kind, data) -> dict` | Create a draft only, and only for operations in `allowed_writes` |

There is deliberately **no delete, submit or cancel**, and none may be added. Records carry a neutral `_state` (for example `draft`, `submitted`, `cancelled`) when the system has document states, mapped in the connector's `mapping.yaml`.

Errors (all subclasses of `ConnectorError`, from `asb.connector`): `NotFound`, `Unavailable` (unreachable or transient; retry reads first), `AuthFailed` (missing or rejected credentials), `WriteNotApproved` (a write the model does not allow). Do not leak raw system errors, URLs with credentials, or secrets in messages.

## `from_env`

The package must export a module-level `from_env(allowed_writes=frozenset())` returning a connector. `asb discover` calls it with an empty set (discovery never writes); generated apps call it with the operations the approved model lists as `write:<operation>`.

- Credentials come only from the environment: `ASB_ERP_URL`, `ASB_ERP_API_KEY`, `ASB_ERP_API_SECRET`. A missing variable raises `ConnectorError` naming it (never its value).
- A write is refused with `WriteNotApproved` unless its operation is in `allowed_writes`.

## Vendoring constraints

The pack copies `asb/connector.py` and your whole package into the generated app (`app/backend/vendor/`). So the package may import only:

- the standard library,
- `httpx`,
- `yaml` (PyYAML),
- `asb.connector`.

Nothing else: not other `asb` modules, not pydantic, not the pack. Load data files (such as `mapping.yaml`) relative to the package with `Path(__file__)`.

## Mapping

Keep system-specific knowledge in `mapping.yaml`: the kind to document map and state semantics (in ERPNext, `docstatus` 0, 1, 2 become `draft`, `submitted`, `cancelled`). The client code reads it; rules written against the connector use only neutral kinds and `_state`.

## Checklist

1. `connector.yaml` and package present; `from_env` exported.
2. Only the four protocol methods, no delete/submit/cancel.
3. Reads retried on transient failure, writes never retried blindly.
4. Credentials only from the environment; no secrets in logs, reprs or errors.
5. Imports limited as above.
6. Tests with a mock transport (see `tests/erpnext/`); a live test marked `live_erp` and skipped unless `ASB_ERP_URL` is set.
