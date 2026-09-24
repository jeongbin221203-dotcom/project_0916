"""검색 임계값을 튜닝 데이터로 고릅니다. (평가 질문은 쓰지 않습니다)

    python -m scripts.faq_tune          임계값을 찾아 data/faq/faq_meta.json 에 적습니다
    python -m scripts.faq_tune --dry    찾기만 하고 적지 않습니다

튜닝 데이터
  양성  각 FAQ의 question_variants (표현이 다른 같은 질문) → 정답 FAQ id가 분명합니다.
  음성  아래 OUT_OF_SCOPE (지식베이스 밖 질문) → 어떤 FAQ도 바로 답하면 안 됩니다.

고르는 방법
  "틀린 FAQ를 바로 돌려주는 비율"을 MAX_WRONG 아래로 묶은 채,
  "맞는 FAQ를 바로 돌려주는 비율"이 가장 높은 조합을 고릅니다.
  통관·결제·수출통제처럼 틀리면 손해가 큰 분류는 임계값을 따로(더 높게) 둡니다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import faq_index  # noqa: E402

META_PATH = faq_index.META_PATH
# 틀린 FAQ를 그대로 돌려주는 일은 이만큼까지만 봐줍니다. 상담에서 오답은 비용·지연으로 갑니다.
MAX_WRONG = 0.02
# 지식베이스 밖 질문에 FAQ를 들이미는 일은 한 건도 봐주지 않습니다.
# ("부동산 취득세율"에 수출 FAQ를 돌려주면 그 뒤 답을 통째로 못 믿습니다)
MAX_FALSE_DIRECT = 0
# 근거 첨부는 조금 너그럽게. (바로 답하는 것과 달리 되돌릴 수 있는 실수입니다)
MAX_CONTEXT_FALSE = 2

# 지식베이스 밖 질문(음성 표본). 평가 세트와 겹치지 않게 여기서만 씁니다.
OUT_OF_SCOPE = [
    "점심 뭐 먹을까요", "파이썬 리스트 정렬하는 법 알려줘", "이 회사 주가 전망 어때요",
    "국내 부가가치세 신고 대행해 주나요", "직원 연차 계산 방법", "사무실 임대차 계약서 검토해줘",
    "해외 직구한 물건 반품하는 법", "비트코인 지금 사도 되나요", "영문 이력서 첨삭해 주세요",
    "엑셀에서 vlookup 쓰는 법", "법인세 절세 방법 알려줘", "우리 회사 로고 디자인해줘",
    "국내 택배 요금이 얼마인가요", "개인 해외여행 비자 필요한가요", "카드 연회비 면제되나요",
    "구내식당 식단표 알려줘", "노트북 추천해 주세요", "국내 특허 출원 절차가 궁금해요",
    "부동산 취득세율이 어떻게 되나요", "주민등록등본 인터넷 발급 방법",
]


PARAPHRASE_PATH = faq_index.DATA_DIR / "tuning" / "paraphrases.jsonl"


def tuning_pairs() -> list[tuple[str, str]]:
    """유사질문(FAQ에 딸린 것) + 실제 말투 패러프레이즈(따로 만든 튜닝 파일).

    유사질문만 쓰면 FAQ와 낱말이 겹쳐 임계값이 너무 후하게 잡힙니다. 실제 사용자는
    다른 낱말로 묻기 때문에, 말투를 흩은 튜닝 파일을 함께 씁니다. (평가 질문은 쓰지 않습니다)
    """

    rows = faq_index.load(force=True)["rows"]
    known = {row["id"] for row in rows}
    pairs = []
    for row in rows:
        for variant in row.get("question_variants") or []:
            pairs.append((variant, row["id"]))
    if PARAPHRASE_PATH.exists():
        for line in PARAPHRASE_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if item.get("gold_faq_id") in known:
                pairs.append((item["question"], item["gold_faq_id"]))
    return pairs


def _decide_with(question: str, limits: dict) -> tuple[str, str | None, float]:
    """임계값을 바꿔 가며 볼 수 있게, decide()와 같은 규칙을 값만 갈아끼워 돌립니다."""

    hits = faq_index.search(question, 5)
    if not hits:
        return "llm", None, 0.0
    best, score, covered, similarity = hits[0]
    second = hits[1][1] if len(hits) > 1 else 0.0
    if score < limits["context"]:
        return "llm", None, score
    high_risk = best.get("category") in faq_index.HIGH_RISK_CATEGORIES
    need = limits["direct_high_risk"] if high_risk else limits["direct"]
    if (score < need or (covered < limits["coverage"] and similarity < limits["similarity"])
            or len(set(faq_index.content_tokens(question))) < 2
            or score - second < limits["margin"]
            or best.get("freshness") == "실시간 확인 필요"
            or faq_index.condition_count(question) >= 2):
        return "faq_context", best["id"], score
    asked = faq_index.question_conditions(question)
    covered = faq_index._conditions_of(best)
    if asked["countries"] and not covered["all_countries"] and \
            not asked["countries"] & covered["countries"]:
        return "faq_context", best["id"], score
    if asked["terms"] and not covered["all_terms"] and not asked["terms"] & covered["terms"]:
        return "faq_context", best["id"], score
    return "faq_direct", best["id"], score


def evaluate_context(limits: dict, pairs, negatives) -> dict:
    """근거로 붙일지(faq_context) 판단의 품질. 양성은 붙어야 하고 음성은 안 붙어야 합니다."""

    attached = 0
    for question, gold in pairs:
        hits = faq_index.search(question, 5)
        if not hits:
            continue
        _, score, covered, similarity = hits[0]
        if score >= limits["context"] and (covered >= limits["context_coverage"]
                                           or similarity >= limits["context_similarity"]):
            attached += 1
    wrong = 0
    for question in negatives:
        hits = faq_index.search(question, 5)
        if not hits:
            continue
        _, score, covered, similarity = hits[0]
        if score >= limits["context"] and (covered >= limits["context_coverage"]
                                           or similarity >= limits["context_similarity"]):
            wrong += 1
    return {"attached": attached / max(1, len(pairs)),
            "attached_out_of_scope": wrong}


def evaluate(limits: dict, pairs, negatives) -> dict:
    right = wrong = 0
    for question, gold in pairs:
        route, chosen, _ = _decide_with(question, limits)
        if route == "faq_direct":
            if chosen == gold:
                right += 1
            else:
                wrong += 1
    false_direct = sum(1 for question in negatives
                       if _decide_with(question, limits)[0] == "faq_direct")
    total = max(1, len(pairs))
    return {"direct_right": right / total,
            # 두 실수를 섞어 재면 한쪽이 다른 쪽에 가려집니다. 따로 봅니다.
            "direct_wrong": wrong / total,
            "wrong_on_faq": wrong, "false_direct_out_of_scope": false_direct,
            "false_direct_rate": false_direct / max(1, len(negatives))}


def main() -> int:
    pairs = tuning_pairs()
    if not pairs:
        print("FAQ가 없습니다. 먼저 python -m scripts.faq_build 를 돌리세요.")
        return 1
    print(f"튜닝 표본: 양성 {len(pairs)}개(유사질문) · 음성 {len(OUT_OF_SCOPE)}개")

    best = None
    for direct in [round(0.30 + 0.02 * i, 2) for i in range(26)]:          # 0.30~0.80
        for extra in (0.0, 0.05, 0.10, 0.15):                              # 고위험 분류 가산
            for margin in (0.0, 0.03, 0.06, 0.10):
              for coverage in (0.4, 0.5, 0.6, 0.7):
               for similarity in (0.70, 0.75, 0.80, 0.85, 0.90):
                limits = {"direct": direct, "direct_high_risk": round(direct + extra, 2),
                          "margin": margin, "coverage": coverage, "similarity": similarity,
                          "context": 0.25}
                score = evaluate(limits, pairs, OUT_OF_SCOPE)
                if score["direct_wrong"] > MAX_WRONG:
                    continue
                if score["false_direct_out_of_scope"] > MAX_FALSE_DIRECT:
                    continue
                key = (score["direct_right"], -direct)
                if best is None or key > best[0]:
                    best = (key, limits, score)
    if best is None:
        print("조건을 만족하는 임계값이 없습니다. MAX_WRONG을 다시 보세요.")
        return 1

    _, limits, score = best

    # 근거로 붙이는 문턱도 같은 방식으로 고릅니다. (범위 밖 질문에는 한 건도 붙지 않게)
    best_context = None
    for coverage in (0.15, 0.20, 0.25, 0.30, 0.35, 0.40):
        for similarity in (0.35, 0.40, 0.45, 0.50, 0.55):
            trial = {**limits, "context_coverage": coverage, "context_similarity": similarity}
            outcome = evaluate_context(trial, pairs, OUT_OF_SCOPE)
            # 근거를 붙이는 것 자체는 위험하지 않습니다(AI가 걸러 답합니다). 다만 범위 밖
            # 질문에 자꾸 붙으면 토큰만 씁니다. 20건 중 2건까지만 봐줍니다.
            if outcome["attached_out_of_scope"] > MAX_CONTEXT_FALSE:
                continue
            if best_context is None or outcome["attached"] > best_context[0]["attached"]:
                best_context = (outcome, coverage, similarity)
    if best_context:
        outcome, coverage, similarity = best_context
        limits["context_coverage"] = coverage
        limits["context_similarity"] = similarity
        print(f"근거 첨부 문턱: 낱말 {coverage} · 뜻 {similarity} → "
              f"양성에 붙은 비율 {outcome['attached']:.1%} · 범위 밖에 붙은 건수 "
              f"{outcome['attached_out_of_scope']}")

    print(f"고른 임계값: {limits}")
    print(f"  맞는 FAQ 바로 답함 {score['direct_right']:.1%} · "
          f"FAQ 오선택 {score['wrong_on_faq']}건({score['direct_wrong']:.1%}) · "
          f"범위 밖 질문에 FAQ 들이밈 {score['false_direct_out_of_scope']}건")
    if "--dry" in sys.argv:
        return 0
    meta = json.loads(META_PATH.read_text(encoding="utf-8"))
    meta["thresholds"] = limits
    meta["tuning"] = {"positives": len(pairs), "negatives": len(OUT_OF_SCOPE),
                      "direct_right": round(score["direct_right"], 4),
                      "direct_wrong": round(score["direct_wrong"], 4),
                      "false_direct_out_of_scope": score["false_direct_out_of_scope"],
                      "max_wrong_allowed": MAX_WRONG,
                      "max_false_direct_allowed": MAX_FALSE_DIRECT}
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("faq_meta.json 에 적었습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
