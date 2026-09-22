"""한글 조사를 앞말에 맞춰 붙입니다.

나라 이름·항구 이름처럼 값이 바뀌는 말 뒤에 조사를 붙일 때 "독일(으)로"처럼
괄호로 얼버무리지 않으려고 씁니다. 받침이 있는지로 갈립니다.
"""

from __future__ import annotations

HANGUL_START, HANGUL_END = 0xAC00, 0xD7A3
JONGSEONG_COUNT = 28
RIEUL = 8  # 종성 ㄹ

# 받침이 없을 때 / 있을 때 짝
PARTICLES = {
    "은": ("는", "은"),
    "는": ("는", "은"),
    "이": ("가", "이"),
    "가": ("가", "이"),
    "을": ("를", "을"),
    "를": ("를", "을"),
    "와": ("와", "과"),
    "과": ("와", "과"),
    "로": ("로", "으로"),
    "으로": ("로", "으로"),
}


# 숫자·영문으로 끝나는 말도 사람은 한국어로 읽습니다. ("8" -> 팔, "L" -> 엘)
# 읽은 소리에 받침이 있는지로 조사를 정합니다.
# 값은 종성 번호입니다. 0이면 받침 없음, 8은 ㄹ입니다.
DIGIT_FINALS = {
    "0": 21,   # 영
    "1": 8,    # 일  (ㄹ)
    "2": 0,    # 이
    "3": 16,   # 삼  (ㅁ)
    "4": 0,    # 사
    "5": 0,    # 오
    "6": 1,    # 육  (ㄱ)
    "7": 8,    # 칠  (ㄹ)
    "8": 8,    # 팔  (ㄹ)
    "9": 0,    # 구
}
LETTER_FINALS = {
    "L": 8,    # 엘  (ㄹ)
    "M": 16,   # 엠  (ㅁ)
    "N": 4,    # 엔  (ㄴ)
    "R": 8,    # 알  (ㄹ)
}


def _final_consonant(word: str) -> int | None:
    """마지막 글자의 종성 번호. 판단할 수 없으면 None."""

    for ch in reversed(word or ""):
        if ch.isspace() or ch in "()[]{}-_.,/":
            continue
        if HANGUL_START <= ord(ch) <= HANGUL_END:
            return (ord(ch) - HANGUL_START) % JONGSEONG_COUNT
        if ch in DIGIT_FINALS:
            return DIGIT_FINALS[ch]
        upper = ch.upper()
        if "A" <= upper <= "Z":
            # 표에 없는 알파벳은 모두 모음으로 끝납니다. (A 에이, B 비, S 에스 ...)
            return LETTER_FINALS.get(upper, 0)
        return None
    return None


def particle(word: str, form: str) -> str:
    """앞말에 맞는 조사를 고릅니다. 판단할 수 없으면 "이(가)"처럼 둘 다 적습니다."""

    without, with_final = PARTICLES[form]
    final = _final_consonant(word)
    if final is None:
        return without if without == with_final else f"{without}({with_final})"
    if without == "로":
        # ㄹ 받침은 "서울로"처럼 "로"를 씁니다.
        return "로" if final in (0, RIEUL) else "으로"
    return with_final if final else without


def josa(word: str, form: str) -> str:
    """말과 조사를 붙여 돌려줍니다. ("독일", "로") -> "독일로\""""

    return f"{word}{particle(word, form)}"
