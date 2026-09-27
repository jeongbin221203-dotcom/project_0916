"""내부 HSK 품목표. 관세청 HS부호 단위별 품목명(공공데이터포털)을 굳혀 둔 것입니다.

data/build_hsk.py가 만든 data/mock/hsk_codes.json을 읽습니다. 쓰는 곳은 셋입니다.

    1. 관세청 HS부호검색이 멈췄을 때 품명·부호로 찾기 (source="internal")
    2. AI가 낸 10자리가 실제로 있는지, 없으면 같은 소호 아래 어떤 세번이 있는지
    3. "기타"·"승용자동차용" 같은 끝단 이름에 상위 호·소호 이름을 붙여 뜻 풀기

기준일이 지난 자료일 수 있으므로 결과에는 늘 base_date를 함께 싣습니다.
파일이 없으면 available()이 False이고, 부르는 쪽은 예전 방식으로 돌아갑니다.
"""

from __future__ import annotations

import re
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

    # 일상어 사전을 **먼저** 봅니다.
    #
    # 예전에는 "한 건도 못 찾았을 때만" 봤습니다. 그런데 "사탕"은 사탕무·사탕수수가,
    # "와인"은 와인딩 기계가 먼저 걸려 한 건이 나오니, 사전이 아예 안 쓰였습니다.
    # 사전은 **사람이 확인해 둔 말**이고 걸려 나온 것은 우연입니다. 확인해 둔
    # 쪽을 앞에 놓고, 우연히 걸린 것은 뒤에 붙입니다.
    # (한 글자 말 "쌀"·"김"도 길이 문턱 앞에서 봐야 합니다) (2026-09-26)
    # 수출 상위 품목은 **호로 바로 갑니다.** 이름 맞히기보다 확실합니다.
    # ('반도체' → 8542·8541. 이름으로 찾으면 2807 황산이 먼저 나왔습니다)
    rows: list[dict] = _by_heading(catalog, _plain(text), limit)

    hint = EVERYDAY.get(_plain(text), ())
    for word in hint:
        rows += [row for row in _match(catalog, _words_of(word), True, limit)
                 if row not in rows]

    if len(text) < (MIN_KOREAN_LENGTH if korean else MIN_ENGLISH_LENGTH):
        return rows[:limit]

    # 물어보듯 적는 말을 걷어냅니다.
    #
    # _match 는 **모든 낱말**이 맞아야 합니다. 그래서 "칫솔 hs코드"라고 적으면
    # '칫솔'은 맞는데 'hs코드'가 품목표에 없어 통째로 아무것도 안 나왔습니다.
    # 무역을 모르는 분일수록 이렇게 적습니다. 226개 낱말에 말버릇을 얹어 보니
    # 132가지가 그랬습니다. 걷어낸 뒤 남는 말이 없으면 원래대로 봅니다.
    # (2026-09-26)
    raw = [_plain(word) for word in text.split() if word.strip()]
    words = [word for word in raw if not _is_noise(word)] or raw
    rows += _look(catalog, words, korean, limit, rows, text)
    if rows:
        return rows[:limit]

    # 조사를 떼고 한 번 더 봅니다.
    #
    # "양파는 몇 번이에요"는 '양파는'으로 갈립니다. 품목표에는 '양파'뿐이라
    # 아무것도 안 나왔습니다. 무역을 모르는 분일수록 이렇게 적습니다.
    # **한 건도 못 찾았을 때만** 떼어 봅니다. 먼저 떼면 '고구마'의 '마'처럼
    # 진짜 이름의 끝글자를 잘라 엉뚱한 것이 걸립니다. (2026-09-26)
    bare = [_strip_particle(word) for word in words]
    if bare != words:
        rows += _look(catalog, bare, korean, limit, rows, text)
    return rows[:limit]


# 낱말 끝에 붙는 조사. 긴 것부터 봅니다.
PARTICLES = ("으로는", "에서는", "으로", "에서", "라는", "이라", "은", "는", "이", "가",
             "을", "를", "의", "도", "만", "와", "과", "로", "에")
MIN_BARE = 2          # 떼고 나서 이만큼은 남아야 합니다


def _strip_particle(word: str) -> str:
    for particle in PARTICLES:
        if not word.endswith(particle):
            continue
        bare = word[: -len(particle)]
        # 한 글자만 남는 것은 사전에 적어 둔 말일 때만 인정합니다.
        # ("게는" → "게" 는 되고, "가위" 의 "가" 를 떼는 일은 없습니다)
        if len(bare) >= MIN_BARE or bare in EVERYDAY:
            return bare
    return word


_HEADINGS_PLAIN: dict[str, tuple] = {}


def _headings_plain() -> dict:
    """찾을 때 쓰는 모양(_plain)으로 한 번만 만들어 둡니다.

    표의 열쇠는 사람이 읽기 쉽게 "LED" 처럼 적어 두는데, _plain 은 소문자로
    바꿉니다. 그대로 두면 대문자로 적어 둔 것이 영영 안 걸립니다.
    """

    if not _HEADINGS_PLAIN:
        _HEADINGS_PLAIN.update({_plain(name): heads for name, heads in HEADINGS.items()})
    return _HEADINGS_PLAIN


def _by_heading(catalog, word: str, limit: int) -> list[dict]:
    """이름이 상위 수출품목 표에 있으면 그 호의 부호를 앞에 놓습니다.

    호 안에서는 **이름이 '기타'뿐인 줄을 뒤로** 미룹니다. 맨 위에 "기타"가
    뜨면 사람은 그게 무엇인지 알 수가 없습니다.
    """

    # 표의 열쇠도 _plain 을 거친 모양으로 맞춥니다. 안 그러면 "LED" 처럼
    # 대문자로 적어 둔 것이 영영 안 걸립니다. (_plain 은 소문자로 바꿉니다)
    heads = _headings_plain().get(word)
    if not heads:
        return []
    rows = []
    for head in heads:
        under = [code for code in catalog["codes"] if code.startswith(head)]
        under.sort(key=lambda code: (_plain(catalog["codes"][code][0]) in GENERIC, code))
        rows += [_row(catalog, code) for code in under[:limit]]
    return rows[:limit]


def _words_of(term: str) -> list[str]:
    """사전이 가리키는 말을 낱말로 나눕니다.

    **붙여서 찾으면 안 됩니다.** "새의 알"을 "새의알"로 붙이면 품목표의
    "새의 알"과 안 맞습니다. 사전에 두 낱말짜리를 적어 두고도 한 건도 안
    나오던 까닭입니다. (2026-09-26)
    """

    return [_plain(part) for part in str(term).split() if part.strip()]


def _look(catalog, words, korean, limit, seen, text) -> list[dict]:
    """일상어 사전을 먼저 보고, 그다음 품목표에서 찾습니다."""

    found: list[dict] = []
    # 낱말 하나로 줄었으면 일상어 사전을 한 번 더 봅니다. ("칫솔 hs코드" → "칫솔")
    if len(words) == 1 and words[0] != _plain(text):
        for word in EVERYDAY.get(words[0], ()):
            found += [row for row in _match(catalog, _words_of(word), True, limit)
                      if row not in seen and row not in found]
    found += [row for row in _match(catalog, words, korean, limit)
              if row not in seen and row not in found]
    return found


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
        # "선글라스용"처럼 **그 물건에 쓰는 부속·재료** 줄은 한 등급 뒤로 보냅니다.
        # 등급 안에서만 뒤로 밀면, 상위 이름으로 걸린 본품(rank 1)보다 여전히
        # 앞에 섭니다. "선글라스"를 찾는 사람은 선글라스용 유리를 찾는 것이
        # 아닙니다. (2026-09-26)
        for_use = _for_use(words, leaf)
        rank = min(rank + for_use, 2)
        scored.append((rank,
                       1 if _plain(name) in GENERIC else 0,
                       for_use,
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
# 품목이 아니라 **묻는 말**입니다. 찾을 때 이 낱말은 빼고 봅니다.
# (_plain 을 거친 모양 — 띄어쓰기·기호가 지워진 상태로 비교합니다)

# --- 수출 상위 품목 → HS 호(4자리) ------------------------------------------------
#
# 왜 이름 맞히기로는 모자라나
#   우리나라 수출 상위 품목 196개로 재 보니, 이름만 맞춰서는 **맨 위가 바로 맞는
#   것이 47%**였고 31개는 한 건도 못 찾았습니다. '반도체'를 치면 2807(황산)이
#   먼저 나왔고, '노트북'은 4820(공책)이 나왔습니다. 그 부호로 신고하면
#   품목분류가 통째로 틀립니다.
#
#   품목표의 이름은 법령 문장이라 사람이 부르는 말과 다릅니다.
#   8542는 "전자집적회로"이지 "반도체"가 아니고, 8471은 "자동자료처리기계"이지
#   "컴퓨터"가 아닙니다. 그래서 **사람이 부르는 이름을 호에 직접 이어 둡니다.**
#
#   호(4자리)까지만 잇습니다. 그 아래 세분(6·10자리)은 규격·재질로 갈리므로
#   우리가 정하면 안 됩니다. 사람이 그 호 안에서 고릅니다.
#
#   여기 적은 호는 모두 품목표의 호 이름과 맞는지 하나씩 확인했습니다.
#   (2026-09-26)
HEADINGS = {
    "반도체": ('8541', '8542'),
    "메모리반도체": ('8542',),
    "집적회로": ('8542',),
    "웨이퍼": ('3818', '8542'),
    "다이오드": ('8541',),
    "트랜지스터": ('8541',),
    "인쇄회로기판": ('8534',),
    "커넥터": ('8536',),
    "콘덴서": ('8532',),
    "저항기": ('8533',),
    "변압기": ('8504',),
    "전동기": ('8501',),
    "발전기": ('8501', '8502'),
    "축전지": ('8507',),
    "이차전지": ('8507',),
    "리튬이온배터리": ('8507',),
    "전선": ('8544',),
    "광케이블": ('8544', '9001'),
    "반도체장비": ('8486',),
    "공작기계": ('8457', '8458', '8459', '8460'),
    "펌프": ('8413',),
    "압축기": ('8414',),
    "베어링": ('8482',),
    "밸브": ('8481',),
    "기어": ('8483',),
    "냉장고": ('8418',),
    "세탁기": ('8450',),
    "에어컨": ('8415',),
    "전자레인지": ('8516',),
    "청소기": ('8508',),
    "건조기": ('8421', '8451'),
    "보일러": ('8402', '8403'),
    "굴착기": ('8429',),
    "지게차": ('8427',),
    "크레인": ('8426',),
    "농기계": ('8432', '8433'),
    "인쇄기": ('8443',),
    "휴대폰": ('8517',),
    "스마트폰": ('8517',),
    "무선통신기기": ('8517',),
    "컴퓨터": ('8471',),
    "노트북": ('8471',),
    "모니터": ('8528',),
    "텔레비전": ('8528',),
    "디스플레이": ('8524', '9013'),
    "카메라": ('8525', '9006'),
    "프린터": ('8443',),
    "스피커": ('8518',),
    "이어폰": ('8518',),
    "마이크": ('8518',),
    "라우터": ('8517',),
    "자동차": ('8703',),
    "승용차": ('8703',),
    "화물차": ('8704',),
    "버스": ('8702',),
    "자동차부품": ('8708',),
    "타이어": ('4011',),
    "엔진": ('8407', '8408'),
    "변속기": ('8708',),
    "브레이크": ('8708',),
    "에어백": ('8708',),
    "오토바이": ('8711',),
    "자전거": ('8712',),
    "선박": ('8901', '8904', '8905', '8906'),
    "항공기부품": ('8807',),
    "철도차량": ('8603', '8605', '8606'),
    "휘발유": ('2710',),
    "경유": ('2710',),
    "등유": ('2710',),
    "윤활유": ('2710',),
    "나프타": ('2710',),
    "합성수지": ('3901', '3902', '3903', '3907'),
    "폴리에틸렌": ('3901',),
    "폴리프로필렌": ('3902',),
    "폴리스티렌": ('3903',),
    "폴리에스터": ('3907', '5402'),
    "에틸렌": ('2901',),
    "프로필렌": ('2901',),
    "벤젠": ('2902',),
    "톨루엔": ('2902',),
    "자일렌": ('2902',),
    "메탄올": ('2905',),
    "암모니아": ('2814',),
    "황산": ('2807',),
    "가성소다": ('2815',),
    "비료": ('3102', '3105'),
    "농약": ('3808',),
    "도료": ('3208', '3209'),
    "접착제": ('3506',),
    "계면활성제": ('3402',),
    "고무": ('4001', '4002'),
    "합성고무": ('4002',),
    "철강판": ('7208', '7209', '7210'),
    "열연강판": ('7208',),
    "냉연강판": ('7209',),
    "도금강판": ('7210',),
    "스테인리스": ('7219', '7220'),
    "철강관": ('7304', '7306'),
    "형강": ('7216',),
    "선재": ('7213',),
    "철근": ('7214',),
    "알루미늄": ('7601', '7606'),
    "구리": ('7403', '7408'),
    "아연": ('7901',),
    "니켈": ('7502',),
    "주석": ('8001',),
    "납": ('7801',),
    "섬유": ('5407', '5512', '6006'),
    "직물": ('5407', '5208'),
    "원단": ('5407', '5208'),
    "의류": ('6103', '6104', '6203', '6204'),
    "티셔츠": ('6109',),
    "셔츠": ('6205', '6206'),
    "바지": ('6203', '6204'),
    "재킷": ('6201', '6202', '6203'),
    "코트": ('6201', '6202'),
    "양말": ('6115',),
    "장갑": ('6116', '4203'),
    "모자": ('6505',),
    "신발": ('6403', '6404'),
    "가방": ('4202',),
    "지갑": ('4202',),
    "라면": ('1902',),
    "김": ('1212', '2008'),
    "인삼": ('1211', '1302'),
    "김치": ('2005',),
    "소주": ('2208',),
    "맥주": ('2203',),
    "담배": ('2402', '2403'),
    "커피": ('0901', '2101'),
    "설탕": ('1701',),
    "밀가루": ('1101',),
    "과자": ('1905',),
    "음료": ('2202',),
    "우유": ('0401',),
    "분유": ('0402',),
    "참치": ('0303', '1604'),
    "오징어": ('0307',),
    "굴": ('0307',),
    "딸기": ('0810',),
    "포도": ('0806',),
    "배": ('0808',),
    "사과": ('0808',),
    "파프리카": ('0709',),
    "버섯": ('0709', '0712'),
    "화장품": ('3304',),
    "기초화장품": ('3304',),
    "색조화장품": ('3304',),
    "마스크팩": ('3304',),
    "샴푸": ('3305',),
    "치약": ('3306',),
    "비누": ('3401',),
    "향수": ('3303',),
    "의약품": ('3003', '3004'),
    "백신": ('3002',),
    "진단키트": ('3822',),
    "의료기기": ('9018',),
    "주사기": ('9018',),
    "콘택트렌즈": ('9001',),
    "안경": ('9003', '9004'),
    "가구": ('9403',),
    "의자": ('9401',),
    "침대": ('9403',),
    "완구": ('9503',),
    "악기": ('9202', '9205', '9207'),
    "시계": ('9101', '9102'),
    "보석": ('7113',),
    "금": ('7108',),
    "은": ('7106',),
    "종이": ('4802', '4810'),
    "골판지": ('4808', '4819'),
    "인쇄물": ('4901', '4911'),
    "플라스틱용기": ('3923',),
    "유리": ('7005', '7007'),
    "타일": ('6907',),
    "시멘트": ('2523',),
    "목재": ('4407', '4412'),
    "합판": ('4412',),
    "페인트": ('3208', '3209'),
    "전구": ('8539',),
    "LED": ('8541', '9405'),
    "조명": ('9405',),
    "공구": ('8204', '8205', '8207'),
    "용접기": ('8515',),
    "금형": ('8480',),
    "나사": ('7318',),
    "스프링": ('7320',),
    "필터": ('8421',),
    "센서": ('9031', '9032'),
    "계측기": ('9030', '9031'),
    "전기차": ('8703',),
    "수소차": ('8703',),
    "태양광": ('8541',),
    "풍력": ('8502', '8412'),
    "케이블": ('8544',),
    "커피믹스": ('2101',),
}


QUERY_NOISE = {
    "hs", "hs코드", "hscode", "hs코드는", "hs번호", "code", "코드", "코드는", "코드가",
    "세번", "세번은", "번호", "번호는", "번호가", "몇번", "몇번이에요", "몇번인가요",
    "몇", "번", "수출", "수출하려는데", "수출할때", "수출하는데", "수입", "수입하려는데",
    "알려줘", "알려주세요", "찾아줘", "찾아주세요", "검색", "조회", "뭐야", "뭔가요",
    "무엇인가요", "어떻게", "어떤가요", "입니다", "인가요", "이에요", "예요",
    "품목", "품목번호", "관세", "관세율", "hsk",
}

# 묻는 말끝. "양파는 몇 번이에요" 의 '번이에요' 처럼 어미가 붙어 오면
# 위 목록으로는 못 거릅니다. 모양으로 봅니다. (2026-09-26)
QUERY_TAIL = re.compile(
    r"^(몇)?(번|번호|코드|세번)?(이|인|입|예)?(에요|예요|가요|인가요|입니까|니까|야|니|요)$")


def _is_noise(word: str) -> bool:
    return word in QUERY_NOISE or bool(QUERY_TAIL.match(word))

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
    "조미김": ("해초",),
    "랩탑": ("휴대용 자동자료처리기계",),
    "노트북컴퓨터": ("휴대용 자동자료처리기계",),
    "전기자전거": ("자전거",),
    # --- 2026-09-26 추가 ---------------------------------------------------
    # 무역을 모르는 분이 아는 말로 찾을 수 있어야 합니다. 일상어 64개로 재어
    # 보니 13개가 **한 건도 안 나왔습니다**(속옷·구두·쌀·김·사탕·와인…).
    # 품목표는 "팬티·브리프", "멥쌀", "설탕과자"처럼 적혀 있기 때문입니다.
    # 아래는 모두 품목표에서 실제로 찾아지는지 확인한 말입니다.
    "속옷": ("브리프", "팬티"),
    "내의": ("브리프", "팬티"),
    "구두": ("바깥 바닥",),
    "신발": ("바깥 바닥",),
    "안경테": ("고글",),
    "시계": ("회중시계",),
    "손목시계": ("회중시계",),
    "소파": ("의자",),
    "배터리": ("축전지", "일차전지"),
    "건전지": ("일차전지",),
    "사탕": ("설탕과자",),
    "캔디": ("설탕과자",),
    "와인": ("포도주",),
    "쌀": ("멥쌀", "현미"),
    "김": ("해초",),
    "우산": ("산류",),
    "지갑": ("핸드백",),
    "장갑": ("장갑류",),
    "인형": ("완구",),
    "노트북컴퓨터": ("휴대용 자동자료처리기계",),
    "모자": ("헤어네트", "운동모"),
    "벨트": ("코트류",),
    "수건": ("토일렛린넨", "베드린넨"),
    "타월": ("토일렛린넨",),
    "베개": ("매트리스 서포트", "침낭"),
    "이불": ("매트리스 서포트",),
    "선글라스": ("고글", "시력교정용 안경"),
    "화장품": ("기초화장용", "메이크업용 제품류"),
    "스킨": ("기초화장용",),
    "로션": ("기초화장용",),

    # 2차 확대 — 일상어 226개로 확인해 48개가 아무것도 못 찾았습니다.
    # 무역을 모르는 분이 아는 말로 찾을 수 있어야 합니다. 여기 있는 말은
    # 모두 품목표에서 실제로 찾아지는지 하나씩 확인했습니다. (2026-09-26)
    # 먹을 것
    "밀": ("밀과 메슬린",),
    "콩": ("대두",),
    "무": ("순무",),
    "배": ("마르멜로",),
    "감": ("단감",),
    "귤": ("감귤류", "만다린"),
    "소고기": ("쇠고기",),
    "쇠고기": ("쇠고기",),
    "닭고기": ("가금", "육과 설육"),
    "오리고기": ("오리",),
    "계란": ("새의 알",),
    "달걀": ("새의 알",),
    "게": ("갑각류",),
    "참치": ("다랑어",),
    "빵": ("빵·파이",),
    "생수": ("광천수", "탄산수"),
    "마요네즈": ("소스",),
    "케첩": ("소스",),
    # 씻고 바르는 것
    "바디워시": ("비누", "유기계면활성제품"),
    "물티슈": ("부직포", "화장지"),
    "생리대": ("위생타월",),
    "섬유유연제": ("조제세제", "유연제"),
    "표백제": ("표백", "과산화"),
    "방향제": ("조제향료", "탈취"),
    # 입는 것
    "옷": ("의류", "슈트"),
    "원피스": ("드레스",),
    "스웨터": ("풀오버", "카디건"),
    "목도리": ("스카프", "머플러"),
    "슬리퍼": ("실내화", "신발류"),
    "카펫": ("양탄자", "바닥깔개"),
    # 집에 두는 것
    "선풍기": ("송풍기",),
    "전자레인지": ("마이크로웨이브", "오븐"),
    "믹서기": ("분쇄기", "믹서"),
    "가습기": ("가습", "공기조절"),
    "제습기": ("제습", "공기조절"),
    "스피커": ("확성기",),
    "옷장": ("침실용 가구",),
    "책장": ("사무실용 가구",),
    "공책": ("연습장",),
    "노트": ("연습장",),
    "풀": ("접착제", "글루"),
    "비닐봉지": ("봉지", "포장용"),
    # 몸에 쓰는 것
    "영양제": ("비타민",),
    "체온계": ("온도계",),
    # 만드는 데 쓰는 것
    "철": ("철강", "선철"),
    "못": ("스테이플",),
    "철사": ("와이어",),
    "약": ("의약품",),
    "헬멧": ("헬멧", "안전모"),
    # 영어로 적는 분도 있습니다. 품목표 영문란에 없는 흔한 말만 담습니다.
    "socks": ("양말",),
    "sock": ("양말",),
    "toothbrush": ("칫솔",),
    "toothpaste": ("치약",),
    "instantnoodle": ("면류",),
    "ramen": ("면류",),
    "ramyun": ("면류",),
    "오토바이": ("모터사이클",),
    "바이크": ("모터사이클",),
    "휠체어": ("장애인용 차량", "신체장애자용"),
    "공": ("볼", "운동용구"),
    "축구공": ("볼", "운동용구"),
    "농구공": ("볼", "운동용구"),
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


def by_prefix(digits: str, limit: int = MAX_RESULTS) -> list[dict]:
    """앞자리로 시작하는 줄들. 6자리 HS를 넣었을 때 한국 세번 후보를 보여 줍니다.

    사람은 나라 공통인 6자리만 알고 오는 일이 많습니다. 우리 신고는 10자리라
    "그 6자리 아래에 이런 것들이 있습니다"를 보여 줘야 고를 수 있습니다.
    """

    catalog = _catalog()
    head = "".join(ch for ch in str(digits or "") if ch.isdigit())
    if catalog is None or not head:
        return []
    found = [code for code in catalog["codes"] if code.startswith(head)]
    found.sort()
    return [_row(catalog, code) for code in found[:limit]]


def heading_name(digits: str) -> str:
    """그 자리의 상위 이름. 없으면 빈 글자입니다. ("4004" -> 고무 웨이스트…)"""

    catalog = _catalog()
    head = "".join(ch for ch in str(digits or "") if ch.isdigit())
    if catalog is None or not head:
        return ""
    levels = catalog.get("levels") or {}
    for size in (10, 9, 8, 7, 6, 5, 4, 2):
        key = head[:size]
        if len(key) == size and key in levels:
            return levels[key][0]
    return ""
