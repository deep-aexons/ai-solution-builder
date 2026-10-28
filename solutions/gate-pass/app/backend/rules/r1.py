# R1: The referenced delivery note or purchase receipt must be submitted in the ERP.
# AI-owned: never overwritten. Helper modules in rules/ must start with an underscore
# (e.g. rules/_helpers.py); any other r<N>.py without a matching rule is an orphan.
from rules._ref import load_reference


def check(obj, erp) -> None:
    """Refuse a pass whose ERP reference is missing, draft or cancelled.

    Only while the pass is a draft (create, edit, submit): once it is with security
    the ERP is not consulted, so a pass can always be rejected or closed.
    """
    if obj.state != "draft":
        return
    load_reference(obj, erp)
