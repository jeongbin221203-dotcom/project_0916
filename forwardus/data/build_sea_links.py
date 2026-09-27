"""국내 무역항별로 실제 항로가 이어진 나라 목록을 뽑습니다.

searoute 항만 데이터의 `to_cty`는 실제 운항 기록에서 모은 연결 국가 목록입니다.
예전에는 도착항만 보고 "한국 직기항"을 판정했는데, 그러면 광양항처럼 멕시코
항로가 없는 항구에서도 직기항이라고 나옵니다. 출발항이 그 나라와 이어져
있는지를 함께 봐야 합니다.

    python data/build_sea_links.py

결과: data/mock/sea_links.json
"""

from __future__ import annotations

import json
from pathlib import Path

import searoute

from build_locations import KOREA_TRADE_PORTS

OUT_PATH = Path(__file__).resolve().parent / "mock" / "sea_links.json"


def build() -> dict:
    ports = searoute.get_graphs()[1]
    network = {data["port"]: data for _, data in ports.nodes(data=True) if data.get("port")}

    origins = {}
    for code in KOREA_TRADE_PORTS:
        data = network.get(code)
        if not data:
            continue
        origins[code] = sorted(set(data.get("to_cty") or []) - {"KR"})

    # 그 나라와 이어진 국내 항구. "광양에는 없지만 부산에는 있습니다"를 알리는 데 씁니다.
    by_country: dict[str, list[str]] = {}
    for code, countries in origins.items():
        for country in countries:
            by_country.setdefault(country, []).append(code)

    return {
        "source": "searoute 항만 네트워크 (실제 운항 기록 기반 연결 국가)",
        "note": "국가 단위 연결입니다. 특정 선사가 그 구간에 정기선을 넣는지는 선사에 확인해야 합니다.",
        "origins": origins,
        "by_country": {k: sorted(v) for k, v in sorted(by_country.items())},
    }


if __name__ == "__main__":
    result = build()
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"국내 항구 {len(result['origins'])}곳 · 나라 {len(result['by_country'])}개 -> {OUT_PATH}")
