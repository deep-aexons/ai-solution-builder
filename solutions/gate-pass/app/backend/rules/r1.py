# R1: The referenced delivery note or purchase receipt must be submitted in the ERP.
# AI-owned: never overwritten. Helper modules in rules/ must start with an underscore
# (e.g. rules/_helpers.py); any other r<N>.py without a matching rule is an orphan.
from rules._ref import load_reference


def check(obj, erp) -> None:
    """Refuse a pass whose ERP reference is missing, draft or cancelled."""
    load_reference(obj, erp)
