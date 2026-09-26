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

# **기계로는 가릴 수 없는 곳.** 주소가 맞는지 아닌지 여기서는 알 수 없습니다.
#
# 2026-09-26에 60초를 주고 다시 두드려도 같았습니다.
#   403 / 412  봇 차단 코드입니다. 사람이 브라우저로 열면 대개 열립니다.
#   타임아웃    이 컴퓨터에서 길이 안 닿습니다. 나라·망에 따라 다를 수 있습니다.
#
# "열립니다"로 세지 않습니다. 확인한 적이 없으니까요.
# "죽었습니다"로도 세지 않습니다. 그렇게 단정할 근거가 없으니까요.
# 사람이 한 번 열어 보고, 열리면 이 목록에서 빼 주세요.
UNVERIFIABLE = {
    "cpsc.gov": "HTTP 403 봇 차단",
    "echa.europa.eu": "HTTP 403 봇 차단",
    "customs.gov.cn": "HTTP 412 봇 차단",
    "most.gov.vn": "연결 시간 초과",
    "acma.gov.au": "응답 시간 초과",
    "agriculture.gov.au": "연결 끊김",
    "canada.ca": "응답 시간 초과",
}


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
    alive = blocked = dead = unknown = 0
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

        why = next((note for host, note in UNVERIFIABLE.items() if host in url), "")
        if ok:
            alive += 1
        elif any(host in url for host in KNOWN_BLOCKERS):
            blocked += 1
            mark = f"{mark} (기계 접속 차단)"
        elif why:
            unknown += 1
            mark = f"사람이 봐야 함 · {why}"
        else:
            dead += 1
            mark = f"★ {mark} — 주소가 바뀐 것 같습니다"
        print(f"{title[:44]:<46}{mark:<22}{url}")

    print("-" * 110)
    print(f"열립니다 {alive} · 차단(주소는 맞음) {blocked} · "
          f"사람이 봐야 함 {unknown} · 주소 의심 {dead}")
    if dead:
        print()
        print("★ 표시된 것만 보세요. 브라우저로 열어 보고 주소가 바뀌었으면")
        print("  app/processors/document_issuers.py 를 고칩니다.")
    if unknown:
        print()
        print(f"※ '사람이 봐야 함' {unknown}곳은 기계 접속을 막거나 이 컴퓨터에서")
        print("  길이 안 닿는 곳입니다. 맞는지 틀렸는지 여기서는 알 수 없습니다.")
        print("  브라우저로 열어 보시고, 열리면 이 파일의 UNVERIFIABLE 에서 빼 주세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
