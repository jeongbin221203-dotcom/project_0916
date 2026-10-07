"""위치 자료에 빠진 **세계 주요 항구**를 더하고, 그 항구까지의 해상 항로를 미리 계산합니다.

    python data/build_extras.py

결과: data/mock/locations_extra.json · data/mock/sea_routes_extra.json
(원자료를 만드는 build_locations.py / build_sea_routes.py 는 건드리지 않습니다 — 다시 만들어도 이 두 파일이 유지되고,
앱이 읽을 때 합쳐 씁니다. 코드는 실제 UN/LOCODE 입니다.)

전 국가 점검에서 고텐부르크·오르후스·오슬로·헬싱키·카르타헤나·과야킬·콜카타·테마·두알라·살랄라·반다르아바스 같은 큰 항구가
목록에 없었습니다. 좌표는 항구 위치 근사값(소수 둘째 자리)이며 항로 거리 계산에만 쓰입니다.
"""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import searoute
from searoute.utils import distance

from build_locations import KOREA_TRADE_PORTS
from build_sea_routes import TRACKED_PASSAGES

HERE = Path(__file__).resolve().parent
LOCATIONS = HERE / "mock" / "locations.json"
OUT_LOCATIONS = HERE / "mock" / "locations_extra.json"
OUT_ROUTES = HERE / "mock" / "sea_routes_extra.json"

# (UN/LOCODE, 한글 이름, 영문 이름, 위도, 경도)
EXTRA_PORTS = {
    "SE": [("SEGOT", "예테보리항", "Gothenburg", 57.70, 11.92)],
    "DK": [("DKAAR", "오르후스항", "Aarhus", 56.15, 10.22)],
    "NO": [("NOOSL", "오슬로항", "Oslo", 59.90, 10.73)],
    "FI": [("FIHEL", "헬싱키항", "Helsinki", 60.16, 24.96)],
    "GE": [("GEPTI", "포티항", "Poti", 42.15, 41.67)],
    "GB": [("GBLGP", "런던게이트웨이항", "London Gateway", 51.50, 0.48)],
    "CO": [("COCTG", "카르타헤나항", "Cartagena", 10.40, -75.52)],
    "EC": [("ECGYE", "과야킬항", "Guayaquil", -2.28, -79.91)],
    "PA": [("PACTB", "크리스토발항", "Cristobal", 9.35, -79.91)],
    "CN": [("CNNSA", "난사항", "Nansha", 22.75, 113.60)],
    "VN": [("VNHPH", "하이퐁항", "Haiphong", 20.85, 106.70)],
    "MM": [("MMRGN", "양곤항", "Yangon", 16.77, 96.17)],
    "MY": [("MYPGU", "파시르구당항", "Pasir Gudang", 1.46, 103.90)],
    "IN": [("INBOM", "뭄바이항", "Mumbai", 18.95, 72.84), ("INCOK", "코치항", "Kochi", 9.97, 76.27),
           ("INPAV", "피파와브항", "Pipavav", 20.92, 71.51), ("INCCU", "콜카타항", "Kolkata", 22.54, 88.31), ("INVTZ", "비샤카파트남항", "Visakhapatnam", 17.69, 83.29),
           ("INTUT", "투티코린항", "Tuticorin", 8.76, 78.19)],
    "AE": [("AEDXB", "두바이항(라시드)", "Dubai", 25.28, 55.28), ("AESHJ", "샤르자항", "Sharjah", 25.36, 55.39)],
    "OM": [("OMSLL", "살랄라항", "Salalah", 16.94, 54.01)],
    "KW": [("KWSWK", "슈와이크항", "Shuwaikh", 29.36, 47.93)],
    "QA": [("QAHMD", "하마드항", "Hamad", 25.00, 51.62)],
    "IR": [("IRBND", "반다르아바스항", "Bandar Abbas", 27.14, 56.22)],
    "LB": [("LBBEY", "베이루트항", "Beirut", 33.90, 35.52)],
    "NG": [("NGAPP", "아파파항", "Apapa", 6.44, 3.36), ("NGTIN", "틴칸아일랜드항", "Tin Can Island", 6.43, 3.33)],
    "GH": [("GHTEM", "테마항", "Tema", 5.63, 0.02)],
    "CM": [("CMDLA", "두알라항", "Douala", 4.05, 9.69)],
}


def _country_info(items: list[dict], code: str) -> dict:
    row = next(item for item in items if item["country_code"] == code)
    return {key: row[key] for key in ("country", "country_en", "country_code", "region")}


def build() -> tuple[list[dict], dict]:
    items = json.loads(LOCATIONS.read_text(encoding="utf-8"))
    items = items if isinstance(items, list) else items["items"]
    have = {item["code"] for item in items}

    extras: list[dict] = []
    for country, rows in EXTRA_PORTS.items():
        info = _country_info(items, country)
        for code, name, name_en, lat, lon in rows:
            if code in have:
                continue
            extras.append({
                "code": code, "name": name, "name_en": name_en, "city": name_en, "city_en": name_en, **info,
                "kind": "port", "status": "AF", "harbor_size": "L", "lat": lat, "lon": lon,
                "sea_direct": None, "sea_transfer_via": [], "direct_from_korea": None, "direct_from": [],
                "flight_minutes": {}, "cargo_hub": False, "korean_air_cargo": False, "transfer_via": [],
                "gateway_only": False, "port_class": None, "note": "", "size_rank": None,
                "cargo_volume_mt": None, "is_terminal": False, "port_group": code, "major": True,
            })

    marnet = searoute.get_graphs()[0]
    restrictions = set(marnet.restrictions)

    def weight(u, v, data):
        return float("inf") if data.get("passage") in restrictions else data.get("weight")

    origins = [i for i in items if i["kind"] == "port" and i["lat"] is not None and i["code"] in KOREA_TRADE_PORTS]
    snapped = {p["code"]: marnet.kdtree.query((p["lon"], p["lat"])) for p in origins + extras}
    routes: dict[str, dict] = {}
    for origin in origins:
        source = snapped[origin["code"]]
        lengths, paths = nx.single_source_dijkstra(marnet, source, weight=weight)
        last_mile = distance(source, (origin["lon"], origin["lat"]))
        legs = {}
        for port in extras:
            target = snapped[port["code"]]
            if target not in lengths:
                continue
            km = lengths[target] + last_mile + distance(target, (port["lon"], port["lat"]))
            passages = sorted({marnet[u][v].get("passage") for u, v in zip(paths[target], paths[target][1:])}
                              & TRACKED_PASSAGES)
            legs[port["code"]] = [round(km), passages] if passages else [round(km)]
        routes[origin["code"]] = legs
    return extras, {"source": "searoute marnet (data/build_extras.py)", "routes": routes}


def main() -> None:
    extras, routes = build()
    OUT_LOCATIONS.write_text(json.dumps(extras, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT_ROUTES.write_text(json.dumps(routes, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    total = sum(len(v) for v in routes["routes"].values())
    print(f"항구 {len(extras)}곳 · 항로 {total}개")


if __name__ == "__main__":
    main()
