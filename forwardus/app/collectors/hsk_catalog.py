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
# 찾을 때 볼 상위 이름. **류(2자리)는 뺍니다.**
#
# 류 제목은 그 류에 들어가는 물건을 죽 늘어놓은 목록입니다.
#   제42류 "가죽제품, 마구, 여행용구ㆍ핸드백과 …"
#   제85류 "전기기기와 그 부분품, 녹음기ㆍ… 텔레비전의 …"
# 그래서 "핸드백"으로 찾으면 제42류 **전부**가 걸려, 4201의 "끈"이 맨 앞에
# 나왔습니다. 호(4자리) 아래만 봅니다. 보여 주는 경로(path)는 그대로입니다.
# (2026-09-26)
MATCH_LEVELS = (4, 5, 6, 7, 8, 9)


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
    rows = _match(catalog, words, korean, limit)
    if rows:
        return rows
    # 못 찾았으면 일상어 사전을 한 번 봅니다. ("양주" → 위스키·브랜디·보드카)
    for word in EVERYDAY.get(_plain(text), ()):
        rows += [row for row in _match(catalog, [_plain(word)], True, limit)
                 if row not in rows]
    return rows[:limit]


def _match(catalog, words, korean, limit) -> list[dict]:
    levels = catalog.get("levels") or {}
    scored = []
    for code, (name, english) in catalog["codes"].items():
        leaf, leaf_spaced = _plain(name), _spaced(name)
        above_text = " ".join(levels[code[:n]][0] for n in MATCH_LEVELS if code[:n] in levels)
        above, above_spaced = _plain(above_text), _spaced(above_text)
        english = english.lower()
        if all(_hit(word, leaf_spaced, leaf) for word in words):
            rank = 0
        elif all(_hit(word, leaf_spaced, leaf) or _hit(word, above_spaced, above)
                 for word in words):
            rank = 1
        elif not korean and all(word in english for word in words):
            rank = 2
        else:
            continue
        # 같은 등급 안의 순서.
        #  - 이름이 "기타"뿐인 줄은 뒤로 미룹니다. 먼저 보여 줘도 알 수가 없습니다.
        #  - "냉장고용"처럼 **그 물건에 쓰는 부속·재료** 줄은 본품보다 뒤로 보냅니다.
        #    "냉장고"를 찾는 사람은 냉장고용 온도조절기를 찾는 것이 아닙니다.
        #  - 찾는 말이 **한 낱말로** 들어 있는 줄이 먼저입니다.
        #    "인스턴트 커피"가 "커피크리머"보다 앞입니다.
        #  - 이름에서 직접 찾은 줄(rank 0)은 **이름이 짧은 것**이 먼저입니다.
        #    "맥주"로 찾으면 "맥주보리"보다 "맥주"가 먼저 나와야 합니다.
        #  - 상위 이름으로 걸린 줄(rank 1)은 이름 길이가 뜻이 없습니다
        #    (죄다 "기타"·"끈"입니다). 품목표 차례대로 둡니다.
        scored.append((rank,
                       1 if _plain(name) in GENERIC else 0,
                       _for_use(words, leaf),
                       _glued(words, leaf_spaced),
                       len(name) if rank == 0 else 0, code))
    scored.sort()
    return _spread(catalog, [row[-1] for row in scored], limit)


def _for_use(words, leaf: str) -> int:
    """이름이 '<찾는 말>용'뿐인가. 그 물건에 **쓰는** 부속·재료 줄입니다."""

    return 1 if any(leaf == word + "용" for word in words) else 0


def _glued(words, spaced: str) -> int:
    """찾는 말이 다른 글자에 붙어 있는가. 한 낱말로 서 있으면 0."""

    for word in words:
        at = spaced.find(word)
        while at >= 0:
            before = spaced[at - 1] if at else " "
            after = spaced[at + len(word):at + len(word) + 1] or " "
            if not (before.isalnum() or "가" <= before <= "힣") and                not (after.isalnum() or "가" <= after <= "힣"):
                return 0
            at = spaced.find(word, at + 1)
    return 1


def _spread(catalog, codes: list[str], limit: int) -> list[dict]:
    """한 호(號)가 결과를 다 차지하지 않게 폅니다.

    "텔레비전"을 찾으면 8524(평판디스플레이 모듈) 줄만 여섯이 나오고, 정작
    텔레비전 수신기기(8528)는 밀려나 안 보였습니다. 호마다 두 줄까지만
    먼저 보여 주고, 자리가 남으면 나머지로 채웁니다. (2026-09-26)
    """

    PER_HEADING = 2
    picked, spare, seen = [], [], {}
    for code in codes:
        head = code[:4]
        if seen.get(head, 0) < PER_HEADING:
            seen[head] = seen.get(head, 0) + 1
            picked.append(code)
        else:
            spare.append(code)
        if len(picked) >= limit:
            break
    picked += spare[:max(0, limit - len(picked))]
    return [_row(catalog, code) for code in picked[:limit]]


# 이름만 봐서는 무엇인지 알 수 없는 줄. 찾은 것 맨 앞에 두면 도움이 안 됩니다.
GENERIC = {"기타", "그밖의것", "그밖의물품", "그밖의것들"}


# 띄어쓰기를 지운 자리에서 찾아도 되는 가장 짧은 길이.
#
# 사람은 "과실젤리"처럼 띄어쓰기를 빼먹습니다. 그래서 지운 자리에서도 찾습니다.
# 그런데 짧은 말은 **서로 다른 두 낱말이 붙은 자리**에 우연히 걸립니다.
#   "소주"  → "채소 주스" → "채소주스"  ← 채소 주스가 소주로 나왔습니다
#   "신발"  → "신발용이나 가죽용 광택제"
# 네 글자부터는 그런 우연이 거의 없습니다. 짧은 말은 띄어쓰기를 지키게 합니다.
LOOSE_MIN = 4


def _hit(word: str, spaced: str, plain: str) -> bool:
    """찾는 말이 이름 안에 있는가. 짧은 말은 띄어쓰기를 넘지 않습니다."""

    if word in spaced:
        return True
    return len(word) >= LOOSE_MIN and word in plain


# 사람이 쓰는 말과 품목표에 적힌 말이 다릅니다. 품목표는 "위스키"라고 적지
# "양주"라고 적지 않습니다. 못 찾았을 때만 이 말로 바꿔 한 번 더 찾습니다.
#
# **분류를 정해 주는 표가 아닙니다.** 찾는 말만 바꿉니다. 어느 호에 들어가는지는
# 그대로 품목표가 정합니다. 여기 있는 말은 모두 품목표에서 실제로 찾아지는지
# 확인한 것입니다. (2026-09-26)
EVERYDAY = {
    "양주": ("위스키", "브랜디", "보드카"),
    "막걸리": ("탁주",),
    "핸드폰": ("스마트폰",),
    "휴대폰": ("스마트폰",),
    "휴대전화": ("스마트폰",),
    "티비": ("텔레비전",),
    "티브이": ("텔레비전",),
    "에어컨": ("공기조절기",),
    "냉방기": ("공기조절기",),
    "운동화": ("스포츠용 신발류",),
    "장난감": ("완구",),
    "기초화장품": ("기초화장용",),
    "스킨로션": ("기초화장용",),
    "조미김": ("해초",),
    "랩탑": ("휴대용 자동자료처리기계",),
    "노트북컴퓨터": ("휴대용 자동자료처리기계",),
    "전기자전거": ("자전거",),
}


# 가운뎃점은 **나열 구분자**입니다. 앞뒤는 서로 다른 항목이라 한 단어로 붙이면 안 됩니다.
# 지워 버렸더니 3401.11 약용비누의 "케이크 모양ㆍ주형 모양"이 "모양주형"이 되어,
# **"양주"로 검색하면 비누가 나왔습니다.** 띄어쓰기는 사람이 빼먹을 수 있으니
# 그대로 지우고, 가운뎃점 자리에는 넘을 수 없는 칸막이를 둡니다. (2026-09-26)
BREAK = ""


def _plain(text: str) -> str:
    """띄어쓰기 차이로 못 찾는 일이 없게 맞춥니다. ("과실 젤리" = "과실젤리")

    가운뎃점·쉼표는 칸막이로 바꿉니다. 찾는 말에는 이 글자가 없으므로,
    나열된 두 항목에 걸친 우연한 일치가 생기지 않습니다.
    """

    return _spaced(text).replace(" ", "")


def _spaced(text: str) -> str:
    """가운뎃점만 칸막이로 바꾸고 **띄어쓰기는 그대로 둡니다.**"""

    text = (text or "").lower()
    for mark in ("ㆍ", "·", ",", "，", ";", "/"):
        text = text.replace(mark, BREAK)
    return text
