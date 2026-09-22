"""내부 HSK 품목표. 관세청 HS부호 단위별 품목명(공공데이터포털)을 굳혀 둔 것입니다.

data/build_hsk.py가 만든 data/mock/hsk_codes.json을 읽습니다. 쓰는 곳은 셋입니다.

    1. 관세청 HS부호검색이 멈췄을 때 품명·부호로 찾기 (source="internal")
    2. AI가 낸 10자리가 실제로 있는지, 없으면 같은 소호 아래 어떤 세번이 있는지
    3. "기타"·"승용자동차용" 같은 끝단 이름에 상위 호·소호 이름을 붙여 뜻 풀기

기준일이 지난 자료일 수 있으므로 결과에는 늘 base_date를 함께 싣습니다.
파일이 없으면 available()이 False이고, 부르는 쪽은 예전 방식으로 돌아갑니다.
"""

from __future__ import annotations

from datetime import date

from app.collectors.base_client import load_mock

MAX_RESULTS = 12
MIN_KOREAN_LENGTH = 2       # 관세청 검색과 같은 기준입니다.
MIN_ENGLISH_LENGTH = 3
# 상위 단위 부호 길이. 5·7·9자리는 소호·세분류 중간 단계입니다.
LEVEL_LENGTHS = (2, 4, 5, 6, 7, 8, 9)


def _catalog() -> dict | None:
    try:
        data = load_mock("hsk_codes")
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("codes") else None


def available() -> bool:
    return _catalog() is not None


def info(today: date | None = None) -> dict:
    """출처·기준일과 갱신이 필요한지. HSK는 매년 1월 1일 개정되므로 기준일이 올해
    1월 1일보다 앞서면 stale입니다. (2027-01-01에는 HS2027로 크게 바뀝니다)"""

    catalog = _catalog() or {}
    result = {key: catalog.get(key, "") for key in ("source", "provider", "license", "url", "base_date")}
    try:
        base = date.fromisoformat(result["base_date"])
    except ValueError:
        base = None
    result["stale"] = base is None or base < date((today or date.today()).year, 1, 1)
    return result


def _format(code: str) -> str:
    return f"{code[:4]}.{code[4:6]}-{code[6:]}"


def _row(catalog: dict, code: str) -> dict:
    korean, english = catalog["codes"][code]
    return {"code": _format(code), "name": korean, "name_en": english,
            "path": path(code), "base_date": catalog.get("base_date", "")}


def _digits(code: str) -> str:
    return "".join(ch for ch in str(code or "") if ch.isdigit())


def lookup(code: str) -> dict | None:
    """10자리가 품목표에 있으면 그 행, 없으면 None."""

    catalog = _catalog()
    digits = _digits(code)
    if not catalog or digits not in catalog["codes"]:
        return None
    return _row(catalog, digits)


def children(prefix: str, limit: int | None = None) -> list[dict]:
    """부호 앞자리(예: 소호 6자리) 아래의 10자리 세번들."""

    catalog = _catalog()
    digits = _digits(prefix)
    if not catalog or not digits:
        return []
    codes = sorted(code for code in catalog["codes"] if code.startswith(digits))
    return [_row(catalog, code) for code in codes[:limit]]


def path(code: str) -> list[str]:
    """상위 단위 한글 이름을 류→호→소호 순서로. "기타"만으로 모르는 뜻을 풀어 줍니다."""

    catalog = _catalog()
    digits = _digits(code)
    if not catalog:
        return []
    levels = catalog.get("levels") or {}
    return [levels[digits[:n]][0] for n in LEVEL_LENGTHS
            if n < len(digits) and digits[:n] in levels and levels[digits[:n]][0]]


def level_name(code: str) -> str | None:
    """류(2)·호(4)·소호(6) 부호의 한글 이름. 품목표에 없는 부호면 None.

    품목표가 없으면 ""입니다. (있는지 없는지 확인할 수 없으니 막지 않습니다)
    """

    catalog = _catalog()
    digits = _digits(code)
    if not catalog:
        return ""
    levels = catalog.get("levels") or {}
    if digits in levels:
        return levels[digits][0] or ""
    if digits in catalog["codes"]:
        return catalog["codes"][digits][0]
    return None


def context(code: str) -> dict:
    """AI 적합도 검토에 넘길 상위 분류 이름. (호 4자리, 그 아래 단계들)"""

    catalog = _catalog()
    digits = _digits(code)
    if not catalog:
        return {"heading": "", "subheading": ""}
    levels = catalog.get("levels") or {}
    heading = (levels.get(digits[:4]) or ["", ""])[0]
    below = [levels[digits[:n]][0] for n in (5, 6, 7, 8, 9)
             if n < len(digits) and digits[:n] in levels]
    return {"heading": heading, "subheading": " > ".join(name for name in below if name)}


def search(query: str, limit: int = MAX_RESULTS) -> list[dict] | None:
    """품명이나 10자리 부호로 찾습니다. 품목표가 없으면 None.

    끝단 이름에 없어도 상위 호·소호 이름에 있으면 찾습니다. ("잼" → 2007.99-9000 기타)
    끝단 이름에 들어 있는 것을 먼저, 그다음 상위 이름, 영문 순서로 보여 줍니다.
    """

    catalog = _catalog()
    if catalog is None:
        return None
    text = (query or "").strip()
    digits = text.replace(".", "").replace("-", "").replace(" ", "")
    if digits.isdigit():
        return [_row(catalog, digits)] if digits in catalog["codes"] else []
    korean = any("가" <= ch <= "힣" for ch in text)
    if len(text) < (MIN_KOREAN_LENGTH if korean else MIN_ENGLISH_LENGTH):
        return []

    words = [_plain(word) for word in text.split() if word.strip()]
    levels = catalog.get("levels") or {}
    scored = []
    for code, (name, english) in catalog["codes"].items():
        leaf = _plain(name)
        above = _plain(" ".join(levels[code[:n]][0] for n in LEVEL_LENGTHS if code[:n] in levels))
        english = english.lower()
        if all(word in leaf for word in words):
            rank = 0
        elif all(word in leaf or word in above for word in words):
            rank = 1
        elif not korean and all(word in english for word in words):
            rank = 2
        else:
            continue
        scored.append((rank, code))
    scored.sort()
    return [_row(catalog, code) for _, code in scored[:limit]]


def _plain(text: str) -> str:
    """띄어쓰기·가운뎃점 차이로 못 찾는 일이 없게 맞춥니다. ("과실 젤리" = "과실젤리")"""

    return (text or "").lower().replace(" ", "").replace("ㆍ", "").replace("·", "")
