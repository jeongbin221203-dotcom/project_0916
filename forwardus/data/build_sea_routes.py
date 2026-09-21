"""국내 무역항 → 전 세계 항구의 실제 해상 항로 거리를 미리 계산합니다.

거리는 searoute의 해상 항로망(marnet)에서 최단 항로를 찾아 구합니다.
육지를 피해 실제 항로를 따라가므로 대권거리와 달리 수에즈·파나마 운하나
희망봉 우회까지 반영됩니다. 지나는 길목(운하 등)도 함께 기록해 두었다가
대기 일수를 더하는 데 씁니다.

    python data/build_sea_routes.py

결과: data/mock/sea_routes.json
"""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import searoute
from searoute.utils import distance

from build_locations import KOREA_TRADE_PORTS

OUT_PATH = Path(__file__).resolve().parent / "mock" / "sea_routes.json"
LOCATIONS_PATH = Path(__file__).resolve().parent / "mock" / "locations.json"

# 소요일에 영향을 주는 길목만 남깁니다 (운하 통항 대기 등).
TRACKED_PASSAGES = {"suez", "panama", "malacca", "gibraltar", "south_africa",
                    "bosporus", "dardanelles", "ormuz", "babalmandab"}


def load_ports() -> tuple[list[dict], list[dict]]:
    """좌표가 있는 국내 무역항과 전 세계 항구를 나눠서 돌려줍니다."""

    items = json.loads(LOCATIONS_PATH.read_text(encoding="utf-8"))
    items = items if isinstance(items, list) else items["items"]
    ports = [i for i in items if i["kind"] == "port" and i["lat"] is not None]
    origins = [p for p in ports if p["code"] in KOREA_TRADE_PORTS]
    destinations = [p for p in ports if p["country_code"] != "KR"]
    return origins, destinations


def build() -> dict:
    marnet = searoute.get_graphs()[0]
    restrictions = set(marnet.restrictions)

    def weight(u, v, data):
        # 북극항로처럼 정기 운항이 없는 구간은 제외합니다.
        return float("inf") if data.get("passage") in restrictions else data.get("weight")

    origins, destinations = load_ports()
    # 항구마다 항로망에서 가장 가까운 지점을 찾아 둡니다.
    snapped = {p["code"]: marnet.kdtree.query((p["lon"], p["lat"])) for p in origins + destinations}

    routes: dict[str, dict[str, list]] = {}
    for origin in origins:
        source = snapped[origin["code"]]
        lengths, paths = nx.single_source_dijkstra(marnet, source, weight=weight)
        # 마지막 구간(항로망 지점 → 선석)은 직선으로 더합니다.
        last_mile = distance(source, (origin["lon"], origin["lat"]))

        legs: dict[str, list] = {}
        for port in destinations:
            target = snapped[port["code"]]
            if target not in lengths:
                continue
            km = lengths[target] + last_mile + distance(target, (port["lon"], port["lat"]))
            path = paths[target]
            passages = sorted({marnet[u][v].get("passage") for u, v in zip(path, path[1:])}
                              & TRACKED_PASSAGES)
            legs[port["code"]] = [round(km), passages] if passages else [round(km)]
        routes[origin["code"]] = legs
        print(f"  {origin['name']}({origin['code']}): {len(legs):,}개 항구")

    return {"source": "searoute marnet (EMODnet 기반 해상 항로망)", "routes": routes}


def main() -> None:
    data = build()
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    total = sum(len(v) for v in data["routes"].values())
    print(f"{OUT_PATH}: 출발 항구 {len(data['routes'])}곳 · 구간 {total:,}개"
          f" · {OUT_PATH.stat().st_size / 1_048_576:.1f}MB")


if __name__ == "__main__":
    main()
