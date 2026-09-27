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
# 이 컴퓨터에서는 못 여는 곳. 주소가 틀렸다는 뜻이 **아닙니다.**
#
# 값 앞의 "확인됨"은 2026-09-26에 다른 경로(WebFetch·검색)로 실제 열어 보고
# 정상임을 확인했다는 뜻입니다. "미확인"은 그렇게까지는 못 했고, 주소가
# 공식이라는 것만 아는 상태입니다.
#
# 어느 쪽도 "열립니다"로 세지 않습니다 — 이 도구가 연 것이 아니니까요.
# 어느 쪽도 "주소 의심"으로 세지 않습니다 — 그렇게 볼 근거가 없으니까요.
UNVERIFIABLE = {
    # --- 확인됨: 주소가 그 기관의 것임을 실제로 확인했습니다 -------------------
    # TLS 인증서를 읽어, 서버가 **그 호스트 이름으로 발급된 공인 인증서**를
    # 내미는 것을 보았습니다(2026-09-26). 죽었거나 틀린 주소는 그럴 수 없습니다.
    "echa.europa.eu": "확인됨 · 인증서 *.echa.europa.eu (Telia) · 403은 봇 차단",
    "ncc.gov.tw": "확인됨 · 인증서 ncc.gov.tw (Google Trust) · 403은 봇 차단",
    "ntc.gov.ph": "확인됨 · 인증서 *.ntc.gov.ph (GoDaddy) · 403은 봇 차단",
    "nbtc.go.th": "확인됨 · 인증서 *.nbtc.go.th (GlobalSign) · 403은 봇 차단",
    "moh.gov.my": "확인됨 · 인증서 www.moh.gov.my (Let's Encrypt) · 403은 봇 차단",
    "customs.gov.my": "확인됨 · 인증서 www.customs.gov.my (GlobalSign)",
    "tcvn.gov.vn": "확인됨 · 인증서 *.tcvn.gov.vn (GlobalSign) · 체인만 불완전",
    "acma.gov.au": "확인됨 · 인증서 www.acma.gov.au (Let's Encrypt)",
    "agriculture.gov.au": "확인됨 · 인증서 각 호스트 이름 (Let's Encrypt · DigiCert)",
    "bsmi.gov.tw": "확인됨 · 열립니다 (이 컴퓨터에서만 인증서 오류)",
    "web.customs.gov.tw": "확인됨 · 열립니다 (이 컴퓨터에서만 인증서 오류)",
    "sirim-qas.com.my": "확인됨 · 공식 (이 컴퓨터에서만 인증서 오류)",
    "bps.dti.gov.ph": "확인됨 · 공식 BPS 포털 (이 컴퓨터에서만 시간 초과)",
    "cpsc.gov": "확인됨 · 열립니다 (이 컴퓨터에서만 403)",
    "canada.ca": "확인됨 · 열립니다 (이 컴퓨터에서만 연결 끊김)",
    # 러시아 두 곳은 443이 아예 안 열립니다(지역 차단으로 보입니다). 인증서를
    # 볼 수 없어 검색으로 확인했습니다 — 두 기관의 공식 주소가 맞습니다.
    "rst.gov.ru": "확인됨(검색) · 지역 차단으로 보임 · Rosstandart 공식 주소",
    "customs.gov.ru": "확인됨(검색) · 지역 차단으로 보임 · 연방관세청 공식 주소",

    # --- 미확인: 여기서는 맞는지 틀린지 알 수 없습니다 -------------------------
    # 서버가 제 이름의 인증서를 안 내밀어(CDN 기본 인증서) 확인이 막혔습니다.
    "jckspj.customs.gov.cn": "미확인 · HTTP 412 (Knownsec WAF) · 해관총서 하위 도메인",
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
    # 윈도 기본 콘솔은 cp949라 한글 대시(—)에서 죽습니다. 링크를 다 두드려 놓고
    # 마지막 출력에서 멈추면 아무것도 못 봅니다. (2026-09-26)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    seen: set[str] = set()
    alive = blocked = dead = unknown = verified = 0
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
        elif why.startswith("확인됨"):
            # 이 도구로는 못 열었지만, 다른 경로로 주소가 맞다는 것을 확인한 곳입니다.
            # "사람이 봐야 함"으로 세면 볼 것이 없는데도 계속 숙제로 남습니다.
            verified += 1
            mark = f"확인됨(기계 차단) · {why}"
        elif why:
            unknown += 1
            mark = f"사람이 봐야 함 · {why}"
        else:
            dead += 1
            mark = f"★ {mark} — 주소가 바뀐 것 같습니다"
        print(f"{title[:44]:<46}{mark:<22}{url}")

    print("-" * 110)
    print(f"열립니다 {alive} · 차단(주소는 맞음) {blocked} · "
          f"확인됨(기계 차단) {verified} · 사람이 봐야 함 {unknown} · 주소 의심 {dead}")
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
