"""계약 조항 **주제** 분류 — 규칙이 놓친 문장을 '확인 필요'로 띄웁니다.

왜 있나 (2026-10-03)
  조항 판정(contract_clauses.py)은 낱말 규칙이라 **처음 보는 표현**을 놓칩니다.
  공개 계약 데이터(CUAD·LEDGAR·SEC EDGAR 공급계약)로 만든 주제 분류기가
  규칙이 손대지 못한 문장을 골라 "이 문장이 준거법 조항일 수 있습니다"라고
  알립니다.

지키는 것
  - **주제만** 말합니다. 유리·불리(독소 여부)는 규칙이 정합니다. 배심재판
    포기는 주제가 '배심'이어도 우리에게 유리합니다.
  - **판정을 바꾸지 않습니다.** 빠진 필수조항은 빠진 채로 두고 "이 문장일
    수 있습니다"를 덧붙입니다. 정해진 판정이 분류기 때문에 흔들리면 안 됩니다.
  - 확신 문턱은 학습에 안 쓴 데이터에서 **정밀도 90%** 에 맞췄습니다
    (data/build_clause_topics.py). 문턱이 없는 주제는 쓰지 않습니다.
  - 모델 파일이 없으면 조용히 빈 답을 냅니다. 바깥 호출·새 패키지가 없습니다.
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path

MODEL_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "clause_topics.json"
MAX_CANDIDATES = 8
MAX_CHUNKS = 500
# 모든 주제에 공통인 최저선. (2026-10-03)
# 문턱은 시험 데이터(미국 기업 계약의 긴 문단)에서 정밀도 90% 로 맞췄는데, 짧은
# 무역 문장에서는 헐거웠습니다 — 차가 1.0 아래인 후보는 대개 틀렸습니다("sole
# representative" 를 '검사'로). 규칙에 없는 표현으로 맞게 띄운 것은 모두 1.44 이상.
MIN_MARGIN = 1.4

_WORD = re.compile(r"[a-z]{2,}")
_HANGUL = re.compile(r"[가-힣]+")
_HANGUL_CHAR = re.compile(r"[가-힣]")
_LATIN_CHAR = re.compile(r"[A-Za-z]")
STOP = set("the of and to in or by any such for be shall this as with on its is are at an "
           "that which from all other than under will may has have been not no it".split())


def tokens(text: str) -> set[str]:
    """영문 낱말·두 낱말 + 한글 두 글자. 숫자는 버립니다(금액·날짜는 주제가 아닙니다).

    **학습(data/build_clause_topics.py)도 이 함수를 씁니다.** 둘이 다르게 쪼개면
    가중치가 맞지 않습니다.
    """

    low = str(text).lower()
    words = [w for w in _WORD.findall(low) if w not in STOP]
    out = set(words)
    out.update(f"{a}_{b}" for a, b in zip(words, words[1:]))
    for run in _HANGUL.findall(low):
        out.update(run[i:i + 2] for i in range(len(run) - 1))
    return out


@lru_cache(maxsize=1)
def model() -> dict:
    try:
        return json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def score(text: str) -> list[tuple[float, str]]:
    """주제(와 '기타')마다 로그 점수. 높은 순.

    나이브 베이즈입니다 — 조항에 든 낱말마다 주제별 가중치를 더합니다. '기타'
    (주제와 무관한 조항)도 함께 겨룹니다. 가중치는 정수(×100)로 저장해 둡니다.
    """

    nb = model()
    table = nb.get("table") or {}
    toks = [t for t in tokens(text) if t in table]
    if not toks:
        return []
    # 로지스틱 회귀는 낱말 수로 나눠 학습했습니다(긴 조항이 점수를 독차지하지 않게).
    # 학습(build_clause_topics.score)과 **같은 계산**이어야 문턱이 맞습니다.
    scale = 1.0 / math.sqrt(len(toks)) if nb.get("norm") == "sqrt" else 1.0
    # 정수 그대로 더하고 마지막에 한 번만 바꿉니다 (32만 자 계약서가 4.7초 걸렸습니다)
    acc = [0] * len(nb["prior"])
    for t in toks:
        acc = [a + v for a, v in zip(acc, table[t])]
    sums = [(p + a * scale) / 100 for p, a in zip(nb["prior"], acc)]
    return sorted(zip(sums, nb["classes"]), reverse=True)


def classify(text: str) -> dict | None:
    """'기타'를 이기고, 2위와의 차가 그 주제의 문턱을 넘으면 그 주제. 아니면 None."""

    ranked = score(text)
    if len(ranked) < 2:
        return None
    (top, topic), (second, _) = ranked[0], ranked[1]
    if topic == "other":
        return None
    info = model()["topics"].get(topic) or {}
    threshold = info.get("threshold")
    margin = top - second
    if threshold is None or margin < max(threshold, MIN_MARGIN):
        return None
    # 정밀도는 **묶음 단위**로 맞췄습니다(준거법·관할·중재를 한 문단에 쓰는 일이
    # 흔해서). 그래서 이름도 묶음을 앞세웁니다 — "분쟁 해결: 관할 법원".
    family = info.get("family_title") or ""
    title = f"{family}: {info['title']}" if family else info["title"]
    return {"topic": topic, "title": title, "keys": list(info["keys"]),
            "score": round(margin, 2), "threshold": threshold}


# 조항 단위로 자릅니다. 학습 데이터가 조항(문단) 단위라 문장 하나보다 낫습니다.
_ARTICLE = re.compile(r"(?=(?:\bArticle\s+\d+|\bSection\s+\d+|\bClause\s+\d+|제\s*\d+\s*조"
                      r"|(?<![\d.])\d{1,2}\.\s+[A-Z]))")


def chunks(text: str) -> list[str]:
    body = re.sub(r"\s+", " ", str(text or ""))
    parts = [p.strip() for p in _ARTICLE.split(body) if p.strip()]
    out = []
    for part in parts:
        if len(part) <= 700:
            out.append(part)
            continue
        # 긴 조항은 문장 몇 개씩 묶습니다
        sentences = re.split(r"(?<=[.;])\s+", part)
        buf = ""
        for s in sentences:
            if len(buf) + len(s) > 600 and buf:
                out.append(buf.strip())
                buf = ""
            buf += " " + s
        if buf.strip():
            out.append(buf.strip())
    return [c for c in out if len(c) >= 40]


def candidates(text: str, judged: dict, categories: dict) -> list[dict]:
    """규칙이 그 **주제를 하나도 판정하지 못한** 조항만 냅니다.

    judged      analyze()["clauses"] — 규칙이 본 조항
    categories  {key: "must"|"gain"|"toxic"}

    주제의 조항 가운데 하나라도 규칙이 봤으면(있음·부족·독소) 그 주제는 넘어
    갑니다 — 규칙이 이미 말한 것을 분류기가 되풀이하면 소음입니다.
    """

    if not model():
        return []
    best: dict[str, dict] = {}
    # 조항 수 상한 — 아주 긴 문서(부록·약관 묶음)에서 응답이 늘어지지 않게.
    for chunk in chunks(text)[:MAX_CHUNKS]:
        # **국문 조항은 보지 않습니다.** 학습 자료가 거의 영문이라 국문을 엉뚱한
        # 주제로 붙였습니다. 국문은 규칙(contract_clauses)만으로 판정합니다.
        if len(_HANGUL_CHAR.findall(chunk)) > len(_LATIN_CHAR.findall(chunk)):
            continue
        found = classify(chunk)
        if not found:
            continue
        keys = found["keys"]
        if any(k in judged for k in keys):
            continue
        kind = "must" if any(categories.get(k) == "must" for k in keys) else "check"
        item = {**found, "kind": kind,
                "sentence": chunk if len(chunk) <= 300 else chunk[:297] + "…"}
        if found["topic"] not in best or item["score"] > best[found["topic"]]["score"]:
            best[found["topic"]] = item
    ranked = sorted(best.values(), key=lambda x: x["score"] - x["threshold"], reverse=True)
    return ranked[:MAX_CANDIDATES]
