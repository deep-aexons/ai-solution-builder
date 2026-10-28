# Requirements: Gate Pass

## Goal

Every vehicle that takes goods out of, or brings goods into, the premises must carry a
gate pass that security has checked against the matching ERP document. Today this is a
paper book at the gate. We want a small module where the store raises the pass, security
approves or rejects it at the gate, and management can see a register of all movements.

## In the client's words

- Store and security staff record goods and vehicles entering and leaving.
- A pass for goods **going out** is raised against a **submitted Delivery Note**.
- A pass for goods **coming in** is raised against a **submitted Purchase Receipt**.
- Security **approves or rejects** the pass at the gate. A rejection must say why.
- The quantities on the pass **cannot be more than** the quantities on the document.
- There is a **gate register** report: by date, direction (out / in) and state.
- The manager can look at everything and export it, but cannot change anything.

## Users and roles

| Role | Who | What they do |
|---|---|---|
| store_user | Store clerks | Create a pass, edit their own draft, submit it to security |
| security | Gate security staff | Approve or reject a pending pass, close an approved pass once the vehicle has passed, run the gate register |
| manager | Plant / logistics manager | Read all passes and the gate register, export; read-only |

## Current process and pain points

- Paper gate book; no link to the ERP document, so a pass can be written against a
  delivery note that was never submitted, or for more than was delivered.
- No quick way to see how many vehicles passed on a given day or which passes were refused.

## Volumes

About 40 passes per day (outward and inward together), 2 to 8 item lines per pass.
Under 15 000 passes per year. A handful of concurrent users.

## Must have

1. Create, edit (own draft only) and submit a gate pass with vehicle number, driver, gate time, direction and item lines.
2. Reference to the ERP Delivery Note (outward) or Purchase Receipt (inward); it must be submitted in the ERP.
3. Item quantities on the pass must not exceed the quantities on the referenced document.
4. Security approves or rejects; rejection needs a reason; approved passes are closed when the vehicle has left or entered.
5. Role-based access: store_user, security, manager as above; manager is read-only.
6. Gate register report with date range, direction and state filters.
7. The ERP is only read; the module never writes to it.

## Nice to have

- Export of the register to a spreadsheet for the manager (read and export permission is granted; a dedicated export screen is not required).

## Open questions

1. Should one pass be allowed to cover only part of a delivery note, and may several passes share one delivery note? (Assumed yes; the quantity rule is checked per pass, not cumulatively.)
2. Is the cumulative total across all passes for the same document required later? (Out of scope for this version.)
3. Who may close a pass: security only (assumed)?
4. Should the vehicle number format be restricted? (Assumed upper-case letters, digits, space and hyphen.)
