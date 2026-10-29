---
description: For the HUMAN approver - review what is being approved and record the approval
argument-hint: <solution-name> <requirements|design|client|golive>
---

Approvals are decisions for a person. This command is for the human to run or confirm; the assistant never records an approval on its own and never runs `asb approve` itself (the hook blocks it). Arguments: $ARGUMENTS

1. If the name or kind is missing, ask for it. Kinds: requirements, design, client, golive.
2. Run `asb status <name>` and show what is about to be approved:
   - requirements: summarise `requirements.md`, including its open questions.
   - design: summarise `design/solution.yaml`, `acceptance.md`, `design-review.md`; give the solution version and the SHA-256 of `design/solution.yaml` (`sha256sum solutions/<name>/design/solution.yaml`). The approval binds to this exact hash; any later edit invalidates it.
   - client or golive: summarise `verify-report.md`, `review.md` and the UAT, backup and rollback checklist status.
3. Ask: "Approve <kind> for <name> as <person's name>?" and wait for an explicit yes from the human. Anything else, or silence, is a no.
4. After the explicit yes, give the human the command to run in their own terminal, with their name filled in:
   `asb approve <name> <kind> --by "<their name>"`
   If they have not run it, do not treat the stage as approved. Then run `asb status <name>` to confirm it was recorded.
