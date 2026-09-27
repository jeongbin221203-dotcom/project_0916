"""Shipment, route, and buyer KPIs aggregated from stored Shipments."""

from __future__ import annotations

from collections import defaultdict

from app.processors import cargo_calculator
from app.services import shipment_service

EXCLUDED_STATUSES = {"draft", "cancelled"}
# Statuses where the delay outcome is known (the cargo has arrived).
ARRIVED_STATUSES = {"arrived", "delivered", "closed"}


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _freight_krw(shipment) -> int:
    return sum(cost.krw_amount for cost in shipment.costs if cost.category == "Freight")


def build_dashboard(viewer) -> dict:
    """보는 사람의 Shipment로 집계합니다. 마스터는 모든 사용자의 것을 봅니다."""

    history = shipment_service.list_shipments(viewer=viewer)
    shipments = [s for s in history if s.status not in EXCLUDED_STATUSES]

    tracked = [s for s in shipments if s.status in ARRIVED_STATUSES or s.delay_days > 0]
    delayed = [s for s in tracked if s.delay_days > 0]
    total_cost = sum(s.total_cost_krw for s in shipments)

    # CBM단가와 KG단가는 같은 화물을 두 방식으로 나눈 값입니다. 그래서 둘의 비는
    # 곧 "1CBM이 몇 kg인가"가 됩니다. 이 값이 말이 안 되면 단가 둘 다 못 믿습니다.
    odd = [s for s in shipments
           if cargo_calculator.density_suspect(sum(c.total_cbm for c in s.cargos),
                                               sum(c.total_weight_kg for c in s.cargos))]

    # **못 믿을 건은 단가 평균에서 뺍니다.** (2026-09-26)
    #
    # 50×50×50cm 상자가 2,400kg으로 적힌 건이 섞여 있었습니다. 그런 건 하나가
    # 분모(부피)를 거의 안 늘리면서 분자(비용)는 그대로 더해, CBM단가를 통째로
    # 끌어올립니다. 실제로 1CBM = 2,224kg이라는 불가능한 값이 나왔습니다.
    #
    # 값을 우리가 고치지는 않습니다. 무엇이 맞는지는 적은 사람이 압니다.
    # 다만 **평균에서는 빼고, 뺐다는 사실을 화면에 적습니다.** 섞어서 평균을
    # 내면 아무도 그 숫자를 못 씁니다.
    sound = [s for s in shipments if s not in odd]
    total_cbm = sum(c.total_cbm for s in sound for c in s.cargos)
    total_kg = sum(c.total_weight_kg for s in sound for c in s.cargos)
    sound_cost = sum(s.total_cost_krw for s in sound)

    kpi = {
        "total_shipments": len(shipments),
        "total_freight_krw": sum(_freight_krw(s) for s in shipments),
        "total_logistics_krw": total_cost,
        "avg_cost_per_cbm": sound_cost / total_cbm if total_cbm else None,
        "avg_cost_per_kg": sound_cost / total_kg if total_kg else None,
        # 단가를 낸 모집단. 화면이 "N건 중 M건으로 냈습니다"라고 적습니다.
        "unit_cost_base": len(sound),
        "odd_density_count": len(odd),
        "odd_density_ids": [s.shipment_id for s in odd[:5]],
        "avg_transit_days": _avg([s.transit_days for s in shipments if s.transit_days]),
        "delay_rate": len(delayed) / len(tracked) * 100 if tracked else None,
        "delay_sample": len(tracked),
        # No customs hold event exists yet; reported as unavailable rather than 0 %.
        "customs_hold_rate": None,
    }

    routes: dict[tuple, list] = defaultdict(list)
    buyers: dict[str, list] = defaultdict(list)
    for s in shipments:
        routes[(s.origin_code, s.destination_code, s.mode_label)].append(s)
        if s.buyer:
            buyers[s.buyer.name].append(s)

    route_rows = []
    for (origin, destination, mode), items in routes.items():
        route_tracked = [s for s in items if s.status in ARRIVED_STATUSES or s.delay_days > 0]
        route_rows.append({
            "route": f"{origin} → {destination}",
            "mode": mode,
            "count": len(items),
            "avg_freight_krw": _avg([_freight_krw(s) for s in items]),
            "avg_transit_days": _avg([s.transit_days for s in items if s.transit_days]),
            "delay_rate": (sum(1 for s in route_tracked if s.delay_days > 0) / len(route_tracked) * 100)
            if route_tracked else None,
        })
    route_rows.sort(key=lambda row: -row["count"])

    buyer_rows = []
    for name, items in buyers.items():
        latest = max(items, key=lambda s: s.created_at)
        buyer_rows.append({
            "buyer": name,
            "count": len(items),
            "avg_cost_krw": _avg([s.total_cost_krw for s in items]),
            "avg_transit_days": _avg([s.transit_days for s in items if s.transit_days]),
            "latest_shipment": latest,
        })
    buyer_rows.sort(key=lambda row: -row["count"])

    max_route_count = max((row["count"] for row in route_rows), default=0)
    return {
        "kpi": kpi,
        "routes": route_rows,
        "max_route_count": max_route_count,
        "buyers": buyer_rows,
        "history": history,
    }
