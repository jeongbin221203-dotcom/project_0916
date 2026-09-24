"""수출 실무 FAQ 지식베이스 검색.

되풀이되는 질문(“FOB랑 CIF 차이가 뭔가요”)은 물어볼 때마다 AI를 부를 이유가 없습니다.
사람이 적어 둔 답을 찾아 바로 돌려주고, 새롭거나 조건이 섞인 질문만 AI에게 넘깁니다.

무엇으로 찾나
  BM25(낱말) + 문자 2-gram(띄어쓰기·조사·오탈자에 강함)을 더해 점수를 냅니다.
  임베딩 모델을 두지 않은 것은, 이 프로젝트에 벡터 저장소가 없고 질문이 짧아
  한국어 표기 흔들림이 의미 차이보다 크기 때문입니다. (README의 판단 근거 참고)

언제 바로 답하나 (decide())
  - 점수가 임계값을 넘고, 2등과 충분히 벌어져 있고,
  - 질문에 담긴 조건(나라·Incoterms·결제조건·HS·품목)이 FAQ가 다루는 범위와 어긋나지 않고,
  - 조건이 두 가지 이상 얽힌 질문이 아니고,
  - 그 FAQ가 실시간 확인이 필요한 내용이 아닐 때.
  하나라도 어긋나면 FAQ를 근거로 붙여 AI에게 넘깁니다(RAG). 위험한 단정을 막는 자리입니다.

임계값은 여기서 정하지 않고 scripts/faq_tune.py 가 튜닝 데이터로 고른 값을
data/faq/faq_meta.json 에 적어 둡니다. 평가용 질문은 튜닝에 쓰지 않습니다.
"""

from __future__ import annotations

import json
import math
import re
import threading
from collections import Counter
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "faq"
FAQ_PATH = DATA_DIR / "faq.jsonl"
META_PATH = DATA_DIR / "faq_meta.json"
VECTOR_PATH = DATA_DIR / "faq_vectors.json"
# 뜻으로 찾은 점수와 낱말로 찾은 점수를 섞는 비율. 벡터가 없으면 낱말만 씁니다.
VECTOR_MIX = 0.5

# 검색에 쓰는 무게. 질문·유사질문이 가장 중요하고, 본문은 보조입니다.
FIELD_WEIGHTS = {"question": 3.0, "variants": 2.5, "keywords": 2.0,
                 "short_answer": 1.0, "category": 0.5}
BM25_K1 = 1.5
BM25_B = 0.75
# 낱말 점수와 문자 2-gram 점수를 섞는 비율. 2-gram은 "인코텀즈가모야"처럼
# 띄어쓰기가 무너진 질문을 살립니다.
NGRAM_MIX = 0.45

# 같은 말의 다른 표기. 검색 전에 하나로 맞춥니다.
SYNONYMS = {
    "인코텀즈": "incoterms", "인코텀스": "incoterms", "엘씨": "lc", "엘시": "lc",
    "신용장": "lc 신용장", "티티": "tt", "비엘": "bl", "선하증권": "bl 선하증권",
    "씨아이에프": "cif", "에프오비": "fob", "디디피": "ddp", "엑스워크": "exw",
    "에이치에스": "hs", "에이치에스코드": "hs", "품목분류": "hs 품목분류",
    "씨오": "co 원산지증명서", "원산지증명": "co 원산지증명서",
    "포워더": "포워딩 포워더", "네고": "매입 네고", "컷오프": "cut off 컷오프",
    "부킹": "booking 부킹", "적하보험": "적하보험 보험",
}

# 질문에 붙은 조건을 알아보는 말. FAQ가 다루는 범위와 어긋나면 바로 답하지 않습니다.
COUNTRY_WORDS = {
    "미국": "US", "미주": "US", "usa": "US", "us": "US", "중국": "CN", "중국향": "CN",
    "일본": "JP", "베트남": "VN", "인도네시아": "ID", "인도": "IN", "태국": "TH",
    "유럽": "EU", "eu": "EU", "독일": "EU", "프랑스": "EU", "네덜란드": "EU", "이탈리아": "EU",
    "영국": "GB", "러시아": "RU", "uae": "AE", "두바이": "AE", "사우디": "SA",
    "호주": "AU", "멕시코": "MX", "브라질": "BR", "캐나다": "CA", "대만": "TW",
    "필리핀": "PH", "말레이시아": "MY", "싱가포르": "SG", "튀르키예": "TR", "터키": "TR",
}
INCOTERMS_WORDS = ("exw", "fca", "fas", "fob", "cfr", "cif", "cpt", "cip", "dap", "dpu", "ddp")
PAYMENT_WORDS = ("l/c", "lc", "신용장", "t/t", "tt", "송금", "d/p", "d/a", "usance",
                 "at sight", "일람불", "유산스", "오에이", "open account", "선수금", "잔금")
ITEM_HINT = re.compile(r"(화장품|식품|의료기기|기계|부품|의류|전자|농산물|수산물|화학|배터리|"
                       r"반도체|자동차|가구|완구|주류|건강기능식품|위험물|냉동|냉장)")
HS_HINT = re.compile(r"\b\d{4}[.\-]?\d{2}\b")

# 질문의 "뜻을 담은 낱말"을 셀 때 빼는 말. 이런 말만 겹쳐서 점수가 오르면 안 됩니다.
STOPWORDS = {"어떻게", "무엇", "뭔가요", "뭐예요", "뭐야", "인가요", "하나요", "되나요", "알려줘",
             "알려주세요", "방법", "경우", "우리", "저희", "회사", "해야", "하는", "때문", "관련",
             "그리고", "그런데", "있나요", "있어요", "없나요", "어디", "언제", "누가", "왜",
             "얼마", "가능", "질문", "궁금", "설명", "정리", "요약", "추천", "차이", "필요"}

_lock = threading.Lock()
_state: dict = {}


# --- 글자 다듬기 -------------------------------------------------------------------

def normalize(text: str) -> str:
    """검색·캐시 열쇠로 쓰는 표준형. 띄어쓰기·기호·표기 흔들림을 지웁니다."""

    lowered = str(text or "").lower().strip()
    for word, replacement in SYNONYMS.items():
        lowered = lowered.replace(word, replacement)
    lowered = re.sub(r"[^0-9a-z가-힣\s/]", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _tokens(text: str) -> list[str]:
    words = [word for word in normalize(text).split() if len(word) > 1 or word.isdigit()]
    # 한국어는 조사가 붙어 낱말이 잘 안 맞습니다. 앞 2~4글자도 함께 봅니다.
    stems = [word[:4] for word in words if len(word) > 4]
    return words + stems


def content_tokens(text: str) -> list[str]:
    """뜻을 담은 낱말만. 이 가운데 얼마나 FAQ에 들어 있는지가 coverage입니다."""

    return [token for token in _tokens(text)
            if token not in STOPWORDS and len(token) > 1
            and not any(token.startswith(stop[:2]) and token in STOPWORDS for stop in STOPWORDS)]


def _bigrams(text: str) -> list[str]:
    flat = normalize(text).replace(" ", "")
    return [flat[i:i + 2] for i in range(len(flat) - 1)]


# --- 색인 -------------------------------------------------------------------------

def _doc_text(faq: dict) -> dict:
    return {"question": faq.get("question", ""),
            "variants": " ".join(faq.get("question_variants") or []),
            "keywords": " ".join(faq.get("keywords") or []),
            "short_answer": faq.get("short_answer", ""),
            "category": faq.get("category", "")}


def _build(rows: list[dict]) -> dict:
    docs = []
    for faq in rows:
        fields = _doc_text(faq)
        counts: Counter = Counter()
        grams: Counter = Counter()
        for name, weight in FIELD_WEIGHTS.items():
            text = fields.get(name, "")
            for token in _tokens(text):
                counts[token] += weight
            for gram in _bigrams(text):
                grams[gram] += weight
        docs.append({"faq": faq, "tf": counts, "len": sum(counts.values()),
                     "gram": grams, "gram_len": sum(grams.values()),
                     "conditions": _conditions_of(faq)})

    def df_of(key: str) -> Counter:
        df: Counter = Counter()
        for doc in docs:
            for token in doc[key]:
                df[token] += 1
        return df

    total = max(1, len(docs))
    return {"docs": docs, "df": df_of("tf"), "gram_df": df_of("gram"),
            "avg_len": sum(doc["len"] for doc in docs) / total,
            "avg_gram": sum(doc["gram_len"] for doc in docs) / total,
            "total": total}


def _idf(df: int, total: int) -> float:
    return math.log(1 + (total - df + 0.5) / (df + 0.5))


def _bm25(query_tokens: list[str], doc: dict, index: dict, *, gram: bool) -> float:
    tf_key, len_key = ("gram", "gram_len") if gram else ("tf", "len")
    df_map = index["gram_df"] if gram else index["df"]
    avg = index["avg_gram"] if gram else index["avg_len"]
    score = 0.0
    for token in set(query_tokens):
        freq = doc[tf_key].get(token, 0)
        if not freq:
            continue
        idf = _idf(df_map.get(token, 0), index["total"])
        norm = freq * (BM25_K1 + 1) / (
            freq + BM25_K1 * (1 - BM25_B + BM25_B * doc[len_key] / max(1.0, avg)))
        score += idf * norm
    return score


# --- 조건 견주기 -------------------------------------------------------------------

def _conditions_of(faq: dict) -> dict:
    """FAQ가 다루는 조건. applicability가 '전체'면 무엇과도 어긋나지 않습니다."""

    applicability = faq.get("applicability") or {}
    text = " ".join([faq.get("question", ""), " ".join(faq.get("keywords") or []),
                     " ".join(str(value) for values in applicability.values()
                              for value in (values if isinstance(values, list) else [values]))])
    return {"countries": _countries_in(text) if not _is_all(applicability.get("countries")) else set(),
            "all_countries": _is_all(applicability.get("countries")),
            "terms": {word for word in INCOTERMS_WORDS if word in normalize(text).split()},
            "all_terms": _is_all(applicability.get("terms"))}


def _is_all(values) -> bool:
    if not values:
        return True
    return any(str(value).strip() in ("전체", "모든 국가", "모든 품목", "모든 조건", "all")
               for value in values)


def _countries_in(text: str) -> set:
    lowered = normalize(text)
    found = set()
    for word, code in COUNTRY_WORDS.items():
        if re.search(rf"(?<![0-9a-z가-힣]){re.escape(word)}", lowered):
            found.add(code)
    return found


def question_conditions(question: str) -> dict:
    """질문에 붙은 조건. 이게 FAQ와 어긋나면 바로 답하지 않습니다."""

    lowered = normalize(question)
    words = set(lowered.split())
    return {"countries": _countries_in(question),
            "terms": {word for word in INCOTERMS_WORDS if word in words},
            "payments": {word for word in PAYMENT_WORDS if word in lowered},
            "items": set(ITEM_HINT.findall(question)),
            "hs": set(HS_HINT.findall(question))}


def condition_count(question: str) -> int:
    """서로 다른 종류의 조건이 몇 가지 얽혀 있는지. 2개 이상이면 개별 상담으로 봅니다."""

    found = question_conditions(question)
    return sum(1 for key in ("countries", "terms", "payments", "items", "hs") if found[key])


# --- 검색 -------------------------------------------------------------------------

def load(force: bool = False) -> dict:
    """FAQ와 색인을 한 번만 읽습니다. (파일이 없으면 빈 색인)"""

    with _lock:
        if _state and not force:
            return _state
        rows: list[dict] = []
        if FAQ_PATH.exists():
            for line in FAQ_PATH.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        meta = json.loads(META_PATH.read_text(encoding="utf-8")) if META_PATH.exists() else {}
        vectors = {}
        if VECTOR_PATH.exists():
            saved = json.loads(VECTOR_PATH.read_text(encoding="utf-8"))
            # 지식베이스가 바뀌었는데 벡터가 그대로면 쓰지 않습니다. 엉뚱한 FAQ를 찾습니다.
            if saved.get("kb_version") == str(meta.get("kb_version", "")):
                vectors = saved.get("vectors") or {}
        _state.clear()
        _state.update(rows=rows, index=_build(rows), meta=meta, vectors=vectors,
                      by_id={row["id"]: row for row in rows})
        search.cache_clear()
        _query_vector.cache_clear()
        return _state


def kb_version() -> str:
    return str(load().get("meta", {}).get("kb_version", "0"))


def thresholds() -> dict:
    """튜닝으로 고른 값. 없으면 보수적인 기본값(바로 답하는 일이 드물게)."""

    meta = load().get("meta", {}).get("thresholds", {})
    return {"direct": float(meta.get("direct", 0.62)),
            "direct_high_risk": float(meta.get("direct_high_risk", 0.72)),
            "margin": float(meta.get("margin", 0.08)),
            "coverage": float(meta.get("coverage", 0.5)),
            "similarity": float(meta.get("similarity", 0.75)),
            "context_coverage": float(meta.get("context_coverage", 0.35)),
            "context_similarity": float(meta.get("context_similarity", 0.55)),
            "context": float(meta.get("context", 0.30))}


HIGH_RISK_CATEGORIES = ("HS 코드·수출신고·통관", "원산지·FTA·인증·수출통제",
                        "결제·신용장·대금 회수")


@lru_cache(maxsize=1024)
def _query_vector(question: str) -> tuple:
    """질문 한 줄을 벡터로. 실패하면 빈 값이고, 그러면 낱말 검색만 씁니다.

    같은 질문을 또 물으면 캐시에서 꺼내므로 임베딩을 다시 부르지 않습니다.
    """

    from app.collectors import ai_client

    if not load().get("vectors") or not ai_client.available():
        return ()
    result = ai_client.embed([question], timeout=8)
    if not result["success"] or not result["data"]:
        return ()
    return tuple(result["data"][0])


def _cosine(left, right) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    # 임베딩은 길이가 1에 가깝게 나오지만, 모델이 바뀔 수 있으니 그대로 나눠 둡니다.
    size_left = math.sqrt(sum(a * a for a in left)) or 1.0
    size_right = math.sqrt(sum(b * b for b in right)) or 1.0
    return dot / (size_left * size_right)


@lru_cache(maxsize=2048)
def search(question: str, k: int = 5) -> tuple:
    """점수 높은 FAQ k개. ((faq, score), ...) 꼴이고 점수는 0~1 언저리로 맞춥니다."""

    index = load()["index"]
    if not index["docs"]:
        return ()
    tokens = _tokens(question)
    grams = _bigrams(question)
    if not tokens and not grams:
        return ()
    content = content_tokens(question)
    vectors = load().get("vectors") or {}
    query_vector = _query_vector(question) if vectors else ()
    scored = []
    for doc in index["docs"]:
        word_score = _bm25(tokens, doc, index, gram=False)
        gram_score = _bm25(grams, doc, index, gram=True)
        # 질문 길이에 따라 점수 폭이 달라져 임계값을 못 씁니다. 길이로 나눠 0~1로 폅니다.
        scale = max(1.0, len(set(tokens)) * 1.6 + len(set(grams)) * 0.25)
        score = ((1 - NGRAM_MIX) * word_score + NGRAM_MIX * gram_score) / scale
        # 점수만 보면 "노트북 추천해 주세요" 같은 남의 질문도 어딘가에 붙습니다.
        # 질문의 뜻을 담은 낱말이 그 FAQ에 실제로 들어 있는지를 따로 셉니다.
        # 흔한 낱말(수출·신고)보다 드문 낱말(노트북·취득세)이 안 맞는 것이 더 중요하므로
        # 낱말마다 idf로 무게를 답니다. 그래야 "말투만 다른 같은 질문"은 살고,
        # "주제가 아예 다른 질문"은 걸립니다.
        weights = {token: _idf(index["df"].get(token, 0), index["total"]) for token in set(content)}
        total_weight = sum(weights.values()) or 1.0
        covered = sum(weight for token, weight in weights.items()
                      if doc["tf"].get(token)) / total_weight
        # 뜻으로 찾은 점수. 낱말이 하나도 안 겹쳐도 같은 이야기면 여기서 살아납니다.
        # 낱말 겹침(covered)과 섞지 않고 따로 둡니다. 섞으면 "비슷해 보이는 남의 질문"이
        # 낱말 겹침 검사를 통째로 건너뛰어, 엉뚱한 FAQ를 자신 있게 돌려주게 됩니다.
        similarity = 0.0
        if query_vector and doc["faq"]["id"] in vectors:
            similarity = _cosine(query_vector, vectors[doc["faq"]["id"]])
            score = (1 - VECTOR_MIX) * score + VECTOR_MIX * similarity * 3.0
        scored.append((doc["faq"], score, covered, similarity))
    scored.sort(key=lambda row: -row[1])
    return tuple((faq, round(score, 4), round(covered, 4), round(similarity, 4))
                 for faq, score, covered, similarity in scored[:k])


def decide(question: str, k: int = 5) -> dict:
    """이 질문을 어떻게 다룰지 정합니다.

    route
      faq_direct  적어 둔 답을 그대로 돌려줍니다. (AI를 부르지 않습니다)
      faq_context 근거로 붙여 AI에게 넘깁니다. (조건이 얽혔거나 확신이 모자랄 때)
      llm         FAQ를 붙이지 않고 평소대로 AI에게 넘깁니다.
    """

    hits = search(question, k)
    limits = thresholds()
    result = {"route": "llm", "faq": None, "score": 0.0, "coverage": 0.0, "similarity": 0.0,
              "candidates": hits, "reasons": [], "kb_version": kb_version()}
    if not hits:
        result["reasons"].append("맞는 FAQ 없음")
        return result

    best, score, covered, similarity = hits[0]
    second = hits[1][1] if len(hits) > 1 else 0.0
    result.update(faq=best, score=score, coverage=covered, similarity=similarity)
    # 근거로 붙일 가치가 있는지. 점수만 보면 "점심 뭐 먹을까요"도 어딘가에 붙습니다.
    # 낱말이 어느 정도 겹치거나 뜻이 가까워야 AI에게 근거로 넘깁니다.
    if score < limits["context"] or (covered < limits["context_coverage"]
                                     and similarity < limits["context_similarity"]):
        result["reasons"].append(
            f"근거로 쓰기에 멀다(점수 {score:.2f} · 낱말 {covered:.0%} · 뜻 {similarity:.2f})")
        return result

    # 바로 답하지 못할 이유를 모두 모읍니다. 하나라도 있으면 AI에게 넘깁니다.
    # (먼저 걸린 것만 돌려주면 "왜 안 됐는지"를 평가에서 읽을 수 없습니다)
    high_risk = best.get("category") in HIGH_RISK_CATEGORIES
    need = limits["direct_high_risk"] if high_risk else limits["direct"]
    if score < need:
        result["reasons"].append(f"바로 답하기에는 점수 부족({score:.2f}<{need:.2f})")
    # "FOB?" 처럼 한 낱말만 던진 질문은 무엇을 묻는지 갈립니다(정의? 위험 이전? FCA와 차이?).
    # 점수는 높게 나오지만 고른 FAQ가 물은 것과 다를 수 있어, 바로 답하지 않고 AI로 넘깁니다.
    if len(set(content_tokens(question))) < 2:
        result["reasons"].append("낱말 하나뿐인 질문이라 무엇을 묻는지 갈림")

    # 낱말이 겹치거나(같은 말로 물었거나), 뜻이 아주 가깝거나(다른 말로 같은 걸 물었거나).
    # 둘 다 아니면 바로 답하지 않습니다.
    if covered < limits["coverage"] and similarity < limits["similarity"]:
        result["reasons"].append(
            f"질문이 이 FAQ와 충분히 겹치지 않음(낱말 {covered:.0%} · 뜻 {similarity:.2f})")
    if score - second < limits["margin"]:
        result["reasons"].append("2등 FAQ와 점수가 붙어 있음")
    if best.get("freshness") == "실시간 확인 필요":
        result["reasons"].append("실시간 확인이 필요한 내용")
    if condition_count(question) >= 2:
        result["reasons"].append("조건이 두 가지 이상 얽힌 질문")

    asked = question_conditions(question)
    covered = _conditions_of(best)
    if asked["countries"] and not covered["all_countries"] and             not asked["countries"] & covered["countries"]:
        result["reasons"].append("질문의 나라를 이 FAQ가 다루지 않음")
    if asked["terms"] and not covered["all_terms"] and not asked["terms"] & covered["terms"]:
        result["reasons"].append("질문의 Incoterms 조건을 이 FAQ가 다루지 않음")

    result["route"] = "faq_context" if result["reasons"] else "faq_direct"
    return result


def answer_text(faq: dict) -> str:
    """FAQ를 상담 답변 모양으로 폅니다. (결론 → 처리 → 주의 → 출처)"""

    parts = [faq.get("short_answer", "").strip(), "", faq.get("detailed_answer", "").strip()]
    cautions = faq.get("cautions") or []
    if cautions:
        parts += ["", "**주의할 점**"] + [f"- {line}" for line in cautions]
    needed = faq.get("required_context") or []
    if needed:
        parts += ["", "**더 정확히 보려면 알려 주세요**"] + [f"- {line}" for line in needed]
    sources = faq.get("sources") or []
    if sources:
        parts += ["", "**출처**"] + [
            f"- {row.get('name', '')} {row.get('url', '')}".rstrip() for row in sources]
    parts += ["", f"_ForwardUs FAQ {faq.get('id', '')} · {faq.get('freshness', '')} · "
                  f"{faq.get('review_status', '')}. 나라·품목·계약 조건에 따라 달라질 수 있어 "
                  f"최종 확인은 관세사·세관·은행에 하세요._"]
    return "\n".join(parts).strip()


def sources_of(faq: dict) -> list[str]:
    return [row.get("name", "") for row in (faq.get("sources") or []) if row.get("name")]
