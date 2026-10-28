# Process map: Gate Pass

```mermaid
flowchart TD
    A[Store user: create gate pass<br/>direction, vehicle, driver, lines] --> B{Direction}
    B -- outbound --> C[Reference a Delivery Note]
    B -- inbound --> D[Reference a Purchase Receipt]
    C --> E[Store user: submit]
    D --> E
    E --> F[[ERP read: document must be submitted - R1<br/>line quantities within document - R2]]
    F -- refused --> A
    F -- ok --> G[State: pending_security]
    G --> H{Security decision}
    H -- approve --> I[State: approved]
    H -- reject with reason --> J[State: rejected - final]
    I --> K[Security: close once vehicle has passed]
    K --> L[State: closed - final]
    M[Manager: read-only, gate register, export] -.-> G
    M -.-> I
    N[Security / manager: gate register<br/>date range, direction, state] -.-> L
```

Who acts: **store_user** creates, edits own draft, submits. **security** approves, rejects (reason required), closes.
**manager** reads and exports only. The ERP is only read (Delivery Note, Purchase Receipt); nothing is written back.
The rules R1 and R2 run only while the pass is a draft (create, edit, submit); the app re-reads the ERP each time. Once the pass is pending with security the ERP is no longer consulted, so approve, reject and close always work.
