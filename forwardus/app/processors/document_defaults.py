"""비워 둔 칸을 실무 관례대로 메웁니다.

두 가지를 다룹니다. 둘 다 "사람이 안 적었을 때만" 손을 대고, 적어 둔 값은
절대 덮지 않습니다.

1. 상업송장 ②Consignee ↔ ⑨Buyer
   실무에서 물건을 받는 곳과 대금을 내는 곳은 대개 같습니다. 같을 때
   한쪽을 비워 두면 서류에 `—`가 찍히는데, 세관과 은행은 그 빈칸을
   "다른 곳인데 안 적었다"로 읽습니다. 같으면 같다고 적어야 합니다.

2. 견적명 (Shipment.project_name)
   대시보드 목록에서 건을 알아보는 이름입니다. 안 적으면
   `도착국가_대표품목_날짜`로 지어 둡니다. ("미국_의류_20260923")
"""

from __future__ import annotations

import re
from datetime import date

SAME_AS_CONSIGNEE = "SAME AS CONSIGNEE"

# 지어 둔 이름인지 알아보는 표시. 사람이 적은 이름과 구별할 때 씁니다.
_AUTO_NAME = re.compile(r"^.+_.+_\d{8}$")
MAX_NAME = 200


def pair_parties(consignee: str, buyer: str) -> tuple[str, str]:
    """(Consignee, Buyer)를 서로 메웁니다. 한쪽만 적혀 있을 때만 움직입니다.

    Consignee만 적혀 있으면 Buyer 칸에 정확히 "SAME AS CONSIGNEE"를 넣습니다.
    Buyer만 적혀 있으면 Consignee 칸에 Buyer 상호를 그대로 옮깁니다.

    Consignee 쪽에는 "SAME AS BUYER" 같은 문구를 **절대 넣지 않습니다.**
    이 값은 서류에만 찍히는 게 아니라 Shipment의 Buyer 이름으로 저장돼
    대시보드 목록과 검색에 그대로 나옵니다. 목록에 문구가 줄줄이 뜨면 어느
    건인지 알 수 없습니다. 상호를 옮기면 서류에 찍히는 내용은 같고 목록도
    읽을 수 있습니다.

    Buyer 칸에 이미 "SAME AS CONSIGNEE"만 있고 Consignee가 비었으면 그대로
    둡니다. 누가 받는지 모르는 상태라, 그 문구를 상호 자리에 옮기면 받는 곳
    이름이 "SAME AS CONSIGNEE"인 서류가 나옵니다. 그 칸은 비워 두고 필수
    항목으로 다시 묻는 편이 맞습니다.
    """

    consignee = (consignee or "").strip()
    buyer = (buyer or "").strip()
    if consignee and not buyer:
        return consignee, SAME_AS_CONSIGNEE
    if buyer and not consignee and buyer.upper() != SAME_AS_CONSIGNEE:
        return buyer, buyer
    return consignee, buyer


def project_name(country: str, product: str, day: date | str | None = None) -> str:
    """`미국_의류_20260923`. 셋 중 있는 것만 밑줄로 잇습니다.

    country  도착국가 이름 (없으면 항구 코드라도)
    product  대표 품목명 (품목 첫 줄)
    day      기준 날짜. 없으면 오늘.
    """

    parts = [_clean_part(country), _clean_part(product), _day(day)]
    return "_".join(part for part in parts if part)[:MAX_NAME]


def is_auto_name(name: str) -> bool:
    """지어 둔 이름처럼 생겼는지. 사람이 적은 이름을 덮지 않으려고 봅니다."""

    return bool(_AUTO_NAME.match((name or "").strip()))


def _clean_part(value: str) -> str:
    """이름 한 토막. 밑줄로 잇기 때문에 사이 공백은 붙여 씁니다."""

    text = re.sub(r"\s+", " ", str(value or "").strip())
    # 괄호 안의 부호는 이름에서 뺍니다. "로스앤젤레스 (USLAX)" -> "로스앤젤레스"
    text = re.sub(r"\s*\([^)]*\)\s*$", "", text).strip()
    return text.replace(" ", "")[:60]


def _day(day: date | str | None) -> str:
    if isinstance(day, date):
        return day.strftime("%Y%m%d")
    digits = "".join(ch for ch in str(day or "") if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else date.today().strftime("%Y%m%d")
