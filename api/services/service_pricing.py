"""Totals for a startbyconnec service selection, grouped by billing cycle."""
from typing import Any

VALID_CYCLES = ("one_time", "monthly", "yearly")


def compute_totals(selections: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    totals: dict[str, dict[str, float]] = {}
    for sel in selections or []:
        cycle = sel.get("billing_cycle")
        if cycle not in VALID_CYCLES:
            cycle = "one_time"
        qty = max(1, int(sel.get("qty") or 1))
        price_min = float(sel.get("price_min") or 0.0)
        price_max_raw = sel.get("price_max")
        price_max = float(price_max_raw) if price_max_raw not in (None, "", 0) else price_min
        bucket = totals.setdefault(cycle, {"min": 0.0, "max": 0.0})
        bucket["min"] += price_min * qty
        bucket["max"] += max(price_min, price_max) * qty
    return totals
