# R2: Pass quantities cannot exceed the quantities on the referenced document.
# AI-owned: never overwritten. Helper modules in rules/ must start with an underscore
# (e.g. rules/_helpers.py); any other r<N>.py without a matching rule is an orphan.
from collections import defaultdict

from rules import RuleViolation
from rules._ref import load_reference, to_decimal


def check(obj, erp) -> None:
    """Per item, pass quantity must not exceed the quantity on the ERP document."""
    kind, doc_id, doc = load_reference(obj, erp)
    allowed = defaultdict(lambda: to_decimal(0))
    for row in doc.get("items") or []:
        allowed[row.get("item_code")] += to_decimal(row.get("qty"))
    wanted = defaultdict(lambda: to_decimal(0))
    for line in obj.lines.all():
        wanted[line.item] += line.quantity
    for item, qty in wanted.items():
        if qty > allowed[item]:
            raise RuleViolation(
                f"item {item}: pass quantity {qty.normalize():f} exceeds "
                f"{allowed[item].normalize():f} on {kind} {doc_id}"
            )
