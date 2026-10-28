# AI-owned helper shared by R1 and R2: resolve the ERP document a gate pass refers to.
from decimal import Decimal, InvalidOperation

from rules import RuleViolation

# direction -> (external name stored on the pass, neutral connector kind)
REFERENCES = {
    "outbound": ("delivery_note", "outbound_shipment"),
    "inbound": ("purchase_receipt", "inbound_receipt"),
}


def reference_for(obj):
    """(external name, neutral kind, document id) for the pass's direction."""
    try:
        external, kind = REFERENCES[obj.direction]
    except KeyError:
        raise RuleViolation(f"unknown direction {obj.direction!r}") from None
    given_kind = getattr(obj, f"{external}_kind")
    if given_kind != external:
        raise RuleViolation(
            f"{obj.direction} gate pass must reference a {external.replace('_', ' ')}"
        )
    doc_id = getattr(obj, f"{external}_id")
    if not doc_id:
        raise RuleViolation(f"{kind} reference is required for {obj.direction} passes")
    return external, kind, doc_id


def load_reference(obj, erp):
    """The referenced document, only if it exists and is submitted in the ERP.

    NotFound becomes a RuleViolation; any other ConnectorError (Unavailable,
    AuthFailed, ...) propagates and the API answers 503.
    """
    from asb.connector import NotFound

    _, kind, doc_id = reference_for(obj)
    try:
        doc = erp.get(kind, doc_id)
    except NotFound:
        raise RuleViolation(f"{kind} {doc_id} not found or not submitted") from None
    if doc.get("_state") != "submitted":
        raise RuleViolation(f"{kind} {doc_id} not found or not submitted")
    return kind, doc_id, doc


def to_decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(0)
