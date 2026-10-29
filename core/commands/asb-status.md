---
description: Show where a solution stands (stages, approvals, fix-loop rounds) and the next step
argument-hint: <solution-name>
---

Show the state of a solution. Arguments: $ARGUMENTS

1. If no name was given, list the folders in `solutions/` and ask which one.
2. Run `asb status <name>`.
3. Explain it briefly: which stages are done, which approvals are recorded (who, when; for design, the version and hash), and how many verify rounds are used out of 3.
4. Name the next step and the skill that handles it: requirements, discovery, design, build, verify or release. If the next step needs a human approval, say exactly which command they must run. Use `asb gate <name> <stage>` to confirm whether a stage may start.
