"""서류 발급처·나라별 규제기관 주소가 살아 있는지 두드려 봅니다.

왜 필요한가
  주소는 우리가 손으로 적어 둔 것입니다. 기관이 사이트를 개편하면 조용히 죽습니다.
  화면에는 링크가 그대로 보이니, 눌러 본 사람만 404를 만납니다.

무엇을 지키나
  - 읽기만 합니다. 아무것도 고치지 않습니다.
  - **차단당한 것과 죽은 것을 가려 적습니다.** 기관 사이트는 기계 접속을 막는
    곳이 많아, 403·타임아웃이 곧 "주소가 틀렸다"는 뜻이 아닙니다.
  - 같은 주소는 한 번만 두드립니다.

쓰는 법
    python scripts/check_doc_links.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.processors import document_issuers as D          # noqa: E402

BROWSER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
# 기계 접속을 막는 것으로 확인된 곳. 여기서 막히는 것은 주소 문제가 아닙니다.
KNOWN_BLOCKERS = ("fda.gov", "fcc.gov", "mfds.go.kr", "foodsafetykorea.go.kr",
                  "komdi.or.kr", "unipass.customs.go.kr")


def collect() -> list[tuple[str, str]]:
    rows = []
    for row in D.ISSUERS:
        if row.get("url"):
            rows.append((row["title"], row["url"]))
        for label, url in row.get("extra", []):
            rows.append((f"  └ {label}", url))
    for code, agencies in D.COUNTRY_AGENCIES.items():
        for agency in agencies:
            rows.append((f"[{code}] {agency['label']}", agency["url"]))
    return rows


def main() -> int:
    seen: set[str] = set()
    alive = blocked = dead = 0
    print(f"{'대상':<46}{'결과':<22}주소")
    print("-" * 110)
    for title, url in collect():
        if url in seen:
            continue
        seen.add(url)
        try:
            response = requests.get(url, timeout=20, allow_redirects=True, headers=BROWSER)
            ok = response.status_code < 400
            mark = "열립니다" if ok else f"HTTP {response.status_code}"
        except Exception as error:                            # noqa: BLE001
            ok, mark = False, type(error).__name__
        if ok:
            alive += 1
        elif any(host in url for host in KNOWN_BLOCKERS):
            blocked += 1
            mark = f"{mark} (기계 접속 차단)"
        else:
            dead += 1
            mark = f"★ {mark} — 사람이 확인해 주세요"
        print(f"{title[:44]:<46}{mark:<22}{url}")

    print("-" * 110)
    print(f"열립니다 {alive} · 차단(주소는 맞음) {blocked} · 확인 필요 {dead}")
    if dead:
        print("\n★ 표시된 것만 보세요. 브라우저로 열어 보고 주소가 바뀌었으면 "
              "app/processors/document_issuers.py 를 고칩니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
