# Report gate_register on gate_pass; filters: date_range, direction, state; columns: name, direction, vehicle_no, driver, gate_time, state
# AI-owned: never overwritten. Helper modules in reports/ must start with an underscore
# (e.g. reports/_helpers.py); any other <name>.py without a matching report is an orphan.
import datetime

from django.db.models import F
from rest_framework.exceptions import ValidationError


def _date(filters, key):
    raw = filters.get(key)
    if not raw:
        return None
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError:
        raise ValidationError({key: "Use a date like 2026-10-31."}) from None


def run(filters: dict) -> list[dict]:
    from entities.models import GatePass

    qs = GatePass.objects.all()
    date_from, date_to = _date(filters, "date_from"), _date(filters, "date_to")
    if date_from:
        qs = qs.filter(gate_time__date__gte=date_from)
    if date_to:
        qs = qs.filter(gate_time__date__lte=date_to)
    for key in ("direction", "state"):
        if filters.get(key):
            qs = qs.filter(**{key: filters[key]})
    qs = qs.order_by(F("gate_time").desc(nulls_last=True), "-id")
    return [
        {
            "name": gp.number,
            "direction": gp.direction,
            "vehicle_no": gp.vehicle_no,
            "driver": gp.driver,
            "gate_time": gp.gate_time.isoformat() if gp.gate_time else None,
            "state": gp.state,
        }
        for gp in qs
    ]
