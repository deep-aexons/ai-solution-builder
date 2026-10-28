# ERPNext connector knowledge

- Auth: `Authorization: token <api_key>:<api_secret>`; credentials come from `ASB_ERP_URL`, `ASB_ERP_API_KEY`, `ASB_ERP_API_SECRET`.
- Kinds map to doctypes in `asb_erpnext/mapping.yaml`; records gain `_state` from `docstatus` (0 draft, 1 submitted, 2 cancelled). Child rows (`items`) are kept.
- Reads: `/api/resource/<Doctype>` (list, with `filters`, `fields`, `limit_page_length`) and `/api/resource/<Doctype>/<name>`.
- Writes: `create_draft` only, and only when `write:<kind>` is approved. Submit, cancel and delete are intentionally absent.
- GET retries 3 attempts (429/5xx/connect/timeouts, 0.5s then 1s backoff); POST retries only on connect errors.
