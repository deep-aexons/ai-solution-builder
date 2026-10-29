---
description: Start a new client solution (creates the folder and begins the requirements interview)
argument-hint: <solution-name> [--pack <pack>] [--connector <connector>]
---

Start a new AI Solution Builder solution. Arguments: $ARGUMENTS

1. The name must be lowercase with hyphens. If it is missing or invalid, ask for it.
2. If no pack was given, list the folders in `packs/` and ask which to use. If no connector was given, list `connectors/` and ask which one, or whether the solution needs none.
3. Run `asb new <name> --pack <pack> --connector <connector>` (omit `--connector` when none).
4. Run `asb status <name>` and show the stages.
5. Continue with the asb-requirements skill: interview the consultant one question at a time and write `requirements.md`.
