"""SEC EDGAR 에서 공급·구매·유통 계약서 원문을 받아 data/raw/contracts/edgar/ 에 둡니다.

왜 있나 (2026-10-03)
  CUAD·LEDGAR 는 라이선스·대출·고용 계약 위주라 **무역 주제**(검사·인도·소유권
  이전·포장·상계·연체 이자)가 드뭅니다. 상장사가 공시한 실제 공급계약서에는
  이런 조항이 그대로 들어 있습니다.

지키는 것
  - 미국 정부 공개 자료입니다. SEC 공정 접근 정책을 따릅니다 — 식별 가능한
    User-Agent, 초당 10건 미만(여기서는 4건 이하).
    https://www.sec.gov/os/accessing-edgar-data
  - 원문은 data/raw/ 아래에만 둡니다(.gitignore). 저장소에는 build_clause_topics.py
    가 만든 낱말 가중치만 들어갑니다.

쓰는 법
  python data/collect_edgar_contracts.py [최대 건수, 기본 800]
"""

from __future__ import annotations

import html
import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "contracts" / "edgar"
UA = "FORWARDUS clause-research (forwardus.onrender.com)"
SEARCH = "https://efts.sec.gov/LATEST/search-index"
PAUSE = 0.3

# 매매·공급 계약만 고릅니다. 무역 조항이 든 것을 앞에 둡니다.
QUERIES = [
    '"supply agreement" "incoterms"',
    '"purchase agreement" "incoterms"',
    '"distribution agreement" "incoterms"',
    '"manufacturing agreement" "incoterms"',
    '"supply agreement" "risk of loss" "inspection"',
    '"purchase agreement" "letter of credit" "shipment"',
    '"sales agreement" "shipment" "force majeure"',
    '"supply agreement" "packaging" "shipping"',
    '"distribution agreement" "title and risk of loss"',
]


def _text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw).replace("\xa0", " ")
    raw = re.sub(r"[ \t]+", " ", raw)
    return re.sub(r"\n\s*\n+", "\n\n", raw).strip()


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 800
    OUT.mkdir(parents=True, exist_ok=True)
    seen = {p.stem for p in OUT.glob("*.txt")}
    got = 0
    with httpx.Client(headers={"User-Agent": UA}, timeout=60, follow_redirects=True) as client:
        for query in QUERIES:
            for start in range(0, 1000, 100):
                params = {"q": query, "forms": "10-K,10-Q,8-K,S-1,10-K405,10-Q/A,8-K/A,S-1/A",
                          "from": start}
                try:
                    hits = client.get(SEARCH, params=params).json()["hits"]["hits"]
                except Exception as exc:  # noqa: BLE001 — 한 번 실패해도 다음으로
                    print("  검색 실패", query, start, exc)
                    break
                time.sleep(PAUSE)
                if not hits:
                    break
                for hit in hits:
                    src = hit["_source"]
                    if not str(src.get("file_type", "")).upper().startswith("EX-10"):
                        continue
                    adsh, filename = hit["_id"].split(":", 1)
                    key = f"{adsh}_{Path(filename).stem}"
                    if key in seen:
                        continue
                    cik = str(int(src["ciks"][0]))
                    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh.replace('-', '')}/{filename}"
                    try:
                        resp = client.get(url)
                    except Exception as exc:  # noqa: BLE001
                        print("  받기 실패", url, exc)
                        continue
                    time.sleep(PAUSE)
                    if resp.status_code != 200:
                        continue
                    body = _text(resp.text)
                    if len(body) < 3000:
                        continue
                    (OUT / f"{key}.txt").write_text(body, encoding="utf-8")
                    (OUT / f"{key}.json").write_text(json.dumps(
                        {"url": url, "query": query, "company": src.get("display_names", [""])[0],
                         "date": src.get("file_date")}, ensure_ascii=False), encoding="utf-8")
                    seen.add(key)
                    got += 1
                    if got % 50 == 0:
                        print(f"  {got}건")
                    if got >= limit:
                        print(f"받은 계약서 {got}건 → {OUT}")
                        return 0
    print(f"받은 계약서 {got}건 → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
