"""FAQ에 적은 출처 URL이 실제로 살아 있는지 확인하고 확인일을 적습니다.

    python -m scripts.faq_sources_check            확인만 하고 결과를 보여 줍니다
    python -m scripts.faq_sources_check --write    살아 있는 URL에 checked_on(오늘)을 적습니다

왜 따로 두나
  FAQ를 쓴 사람(또는 모델)이 "확인했다"고 적는 것은 믿을 수 없습니다. 여기서 실제로
  받아 보고, 응답한 주소에만 확인일을 남깁니다. 200이 아니면 checked_on은 비워 둡니다.
  (기관 사이트는 봇을 막아 403·503을 주기도 합니다. 그 경우도 '확인 못 함'으로 둡니다)
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
FAQ_DIR = ROOT / "data" / "faq"
PARTS = FAQ_DIR / "parts"
TIMEOUT = 15
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ForwardUs-FAQ-check/1.0)"}


def urls_in(rows: list[dict]) -> list[str]:
    seen = []
    for row in rows:
        for source in row.get("sources") or []:
            url = str(source.get("url", "")).strip()
            if url and url not in seen:
                seen.append(url)
    return seen


def check(url: str) -> tuple[int | str, str]:
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True, verify=False,
                          headers=HEADERS) as client:
            response = client.get(url)
            return response.status_code, str(response.url)
    except Exception as error:                       # noqa: BLE001 - 망 사정도 '확인 못 함'
        return type(error).__name__, ""


def main() -> int:
    rows = []
    for path in sorted(PARTS.glob("*.jsonl")):
        rows += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                 if line.strip()]
    targets = urls_in(rows)
    print(f"확인할 주소 {len(targets)}개")

    results: dict[str, tuple] = {}
    tally: Counter = Counter()
    for url in targets:
        status, final = check(url)
        results[url] = (status, final)
        tally[str(status)] += 1
        mark = "OK " if status == 200 else "-- "
        print(f"{mark}{status} {url}")

    print("\n요약:", dict(tally))
    alive = {url for url, (status, _) in results.items() if status == 200}
    print(f"살아 있는 주소 {len(alive)}/{len(targets)}")

    if "--write" not in sys.argv:
        print("\n(확인일을 적으려면 --write)")
        return 0

    today = date.today().isoformat()
    changed = 0
    for path in sorted(PARTS.glob("*.jsonl")):
        lines = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            for source in row.get("sources") or []:
                url = str(source.get("url", "")).strip()
                if url in alive and source.get("checked_on") != today:
                    source["checked_on"] = today
                    changed += 1
            lines.append(json.dumps(row, ensure_ascii=False))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"확인일을 적은 출처 {changed}개 (오늘 {today})")
    print("이어서 python -m scripts.faq_build 를 돌려 지식베이스를 다시 만드세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
