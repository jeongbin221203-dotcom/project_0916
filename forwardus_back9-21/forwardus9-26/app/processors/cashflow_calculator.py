"""Cash flow calculation for a shipment's payment schedule."""

from __future__ import annotations

from datetime import date


def calculate_cash_flow(payments: list[dict]) -> dict:
    """Compute the running balance and peak working capital requirement.

    Each payment is ``{"label", "amount_krw", "due_date"}``; negative amounts
    are outflows. Same-day items are processed outflow-first (conservative).
    """

    ordered = sorted(payments, key=lambda item: (item["due_date"], item["amount_krw"] >= 0))
    balance = 0
    lowest = 0
    lowest_date: date | None = None
    timeline = []
    for item in ordered:
        balance += item["amount_krw"]
        if balance < lowest:
            lowest = balance
            lowest_date = item["due_date"]
        timeline.append({**item, "balance_krw": balance})

    total_in = sum(item["amount_krw"] for item in ordered if item["amount_krw"] > 0)
    total_out = -sum(item["amount_krw"] for item in ordered if item["amount_krw"] < 0)
    return {
        "timeline": timeline,
        "total_inflow_krw": total_in,
        "total_outflow_krw": total_out,
        "net_krw": total_in - total_out,
        "peak_funding_need_krw": -lowest,
        "peak_funding_date": lowest_date,
        "source": "calculated",
    }
