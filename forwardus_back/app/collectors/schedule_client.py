"""Carrier schedule provider.

No live schedule API is connected yet, so results come from data/mock and
are always marked ``source = mock``.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.collectors.base_client import fail, load_mock, ok


def fetch_schedules(
    *,
    transport_mode: str,
    sea_mode: str | None,
    origin: dict,
    destination: dict,
    departure_date: date,
    metrics: dict,
) -> dict:
    """Return normalized schedules departing on or after ``departure_date``."""

    # TODO: call the live provider via base_client.request_json when SCHEDULE_API_KEY is configured.

    service = "AIR" if transport_mode == "AIR" else (sea_mode or "FCL")
    try:
        templates = load_mock("schedules")[service]
    except (OSError, ValueError, KeyError):
        return fail("MOCK_DATA_ERROR", "mock")

    region = destination.get("region", "asia")
    items = []
    for template in templates:
        transit = template["transit_days"].get(region)
        if transit is None:
            continue
        # Weekly service: first sailing on/after the requested date.
        offset = (template["weekday"] - departure_date.weekday()) % 7
        for week in range(2):
            etd = departure_date + timedelta(days=offset + week * 7)
            eta = etd + timedelta(days=transit)
            rate = template["rate_usd"][region]
            if service == "FCL":
                freight = rate * metrics["container_quantity"]
                basis = f"{metrics['container_quantity']} × {metrics['container_type']}"
            elif service == "LCL":
                freight = max(rate * metrics["billable_revenue_ton"], template["minimum_usd"])
                basis = f"{metrics['billable_revenue_ton']:.2f} R/T"
            else:
                freight = max(rate * metrics["chargeable_weight_kg"], template["minimum_usd"])
                basis = f"{metrics['chargeable_weight_kg']:,.0f} kg C.W."
            items.append({
                "schedule_id": f"{template['code']}-{etd.isoformat()}",
                "carrier": template["carrier"],
                "vessel_or_flight": template["vessel_or_flight"],
                "service": template["service"],
                "etd": etd.isoformat(),
                "eta": eta.isoformat(),
                "transit_days": transit,
                "direct": template["direct"],
                "freight_usd": round(freight, 2),
                "freight_basis": basis,
                "reliability": template["reliability"],
                "origin_code": origin["code"],
                "destination_code": destination["code"],
                "source": "mock",
            })
    return ok(items, "mock")
