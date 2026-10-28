# Acceptance tests: Gate Pass

| ID | Covers | Role | Given / When / Then |
|---|---|---|---|
| AT-01 | R1 | store_user | **Given** an outward pass referencing a Delivery Note that is still a draft in the ERP **When** the store user submits it **Then** it is refused (400) with "outbound_shipment <id> not found or not submitted" and stays in draft. A submitted note is accepted. |
| AT-02 | workflow (submit, approve) | store_user, security | **Given** a pass in pending_security **When** a store_user tries to approve **Then** 403 and state unchanged; **When** security approves **Then** the state is approved and a transition log row is written. |
| AT-03 | R2 | store_user | **Given** a reference document with 10 of item BOLT **When** the pass lists 11 of BOLT (or 6 + 5 on two lines) **Then** the submit is refused (400) naming the item. Exactly 10 is accepted. |
| AT-04 | workflow:reject | security | **Given** a pending pass **When** security rejects without a reason **Then** 400 and the pass stays pending; **When** a reason is given **Then** the state is rejected and the reason is stored. |
| AT-05 | gate_register report | security, manager | **Given** passes of both directions on different dates **When** the register is run with direction and date range filters **Then** only matching passes are returned, newest gate time first. |
| AT-06 | permissions | manager | **Given** a manager **When** they read passes **Then** 200; **When** they create, edit, delete or transition **Then** 403. |

Rule/transition coverage: R1 -> AT-01, R2 -> AT-03, submit/approve -> AT-02, reject -> AT-04, close -> AT-02 (verified by the generated workflow matrix), gate_register -> AT-05, roles -> AT-06 (plus the generated permission matrix).
