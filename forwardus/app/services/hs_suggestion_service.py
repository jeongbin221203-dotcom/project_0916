"""Broaden product searches and compare observed API043 product-line counts."""
from __future__ import annotations

import re
import math
from concurrent.futures import ThreadPoolExecutor

from flask import current_app

from app.collectors import (customs_extra_client, customs_client, hs_ai_client, hs_open_client,
                            hsk_catalog, tariff_client)
from app.processors import fta_guide

# Real HSK rows: live customs API, or customs' published table when the API is down.
LIVE_SOURCES = ("api", "internal")
# Most frequent HSK tails; used only when the internal table is missing.
HSK_TAILS = ("0000", "1000", "2000", "9000", "1010", "9010")
SIBLING_LIMIT = 8
MATCH_ORDER = {"high": 0, "medium": 1, "unknown": 2, "low": 3}
MATCH_LABELS = {"high": "적합도 높음", "medium": "조건 확인 필요", "unknown": "적합도 미확인", "low": "관련성 낮음"}


def keywords(query: str) -> list[str]:
    """Small deterministic fallback; retain the original phrase separately."""
    words = re.findall(r"[가-힣A-Za-z]{2,}", query)
    stop = {"마시는", "먹는", "바르는", "제품", "상품", "프리미엄", "고급", "용", "the", "with"}
    terms = [word for word in words if word.lower() not in stop]
    return list(dict.fromkeys(term for term in terms if term != query))[:3]


def _code(value):
    return re.sub(r"[.\-\s]", "", value)


def _hypothesis_groups(hypotheses: dict[str, str], fetch) -> list[list[dict]]:
    """AI가 낸 10자리를 확인합니다. 한 부호당 한 묶음입니다.

    AI는 HS6는 맞히고 끝 4자리를 지어내는 일이 잦습니다(딸기잼 2007999090).
    그러면 같은 소호 아래 실제 세번으로 바꿔 후보에 넣고, 맞는지는 AI 검토가 가립니다.
    내부 품목표가 있으면 관세청을 부르지 않고, 없으면 관세청에 묻습니다.
    """

    def tagged(rows, term, reason):
        return [{**row, "matched_terms": [term], "hypothesis": reason} for row in rows]

    def sibling_reason(code):
        return f"AI가 제안한 HS {code[:4]}.{code[4:6]} 소호의 세번"

    if hsk_catalog.available():
        groups = []
        for code, reason in hypotheses.items():
            row = hsk_catalog.lookup(code)
            groups.append(tagged([row], code, reason) if row else
                          tagged(hsk_catalog.children(code[:6], SIBLING_LIMIT), code, sibling_reason(code)))
        return groups

    def exact(code, response):
        if not response.get("success") or response.get("source") != "api":
            return []
        return [row for row in response.get("data") or [] if _code(row["code"]) == code]

    codes = list(hypotheses)
    with ThreadPoolExecutor(max_workers=5) as executor:
        responses = list(executor.map(fetch, codes))
    groups, missing = [], []
    for code, response in zip(codes, responses):
        rows = exact(code, response)
        if rows:
            groups.append(tagged(rows, code, hypotheses[code]))
        else:
            missing.append(code)
    # 품목표가 없으면 흔한 끝자리를 관세청에 물어 실제로 있는 것만 남깁니다.
    parents = list(dict.fromkeys(code[:6] for code in missing))[:3]
    probes = [parent + tail for parent in parents for tail in HSK_TAILS if parent + tail not in hypotheses]
    with ThreadPoolExecutor(max_workers=5) as executor:
        responses = list(executor.map(fetch, probes))
    for code, response in zip(probes, responses):
        rows = exact(code, response)
        if rows:
            groups.append(tagged(rows, code, sibling_reason(code)))
    return groups


def search(query: str, country: str = "", order: str = "frequency") -> dict:
    """AI generalizes all text inputs; customs data (API018 or its published table) decides existence."""
    text = (query or "").strip()[:200]
    if not text:
        return {"success": True, "source": "api", "data": []}
    numeric = _code(text).isdigit()
    app = current_app._get_current_object()

    def initial_search():
        with app.app_context():
            return customs_client.search_hs_codes(text)

    def analyze():
        with app.app_context():
            return hs_ai_client.analyze(text)

    with ThreadPoolExecutor(max_workers=2) as executor:
        found_future = executor.submit(initial_search)
        analysis_future = executor.submit(analyze) if not numeric else None
        found = found_future.result()
        analysis = analysis_future.result() if analysis_future else {
            "available": False, "message": "HS부호 직접 조회", "search_terms": [], "hypotheses": []}
    hypotheses = {row["code"]: row["reason"] for row in analysis.get("hypotheses", [])}
    words = [] if numeric else [term for term in dict.fromkeys(
        analysis.get("search_terms") or keywords(text)) if term != text][:4]

    def fetch(term):
        with app.app_context():
            return customs_client.search_hs_codes(term)

    with ThreadPoolExecutor(max_workers=5) as executor:
        word_responses = list(executor.map(fetch, words))
    code_groups = _hypothesis_groups(hypotheses, fetch)
    terms = [text, *hypotheses, *words]
    searched_as = " · ".join(terms[1:])
    groups, failures = [], []
    for term, response in [(text, found), *zip(words, word_responses)]:
        if not response.get("success") or response.get("source") not in LIVE_SOURCES:
            failures.append(term)
            continue
        groups.append([{**row, "matched_terms": [term], "hypothesis": hypotheses.get(_code(row["code"]), "")}
                       for row in response["data"] if re.fullmatch(r"[0-9]{10}", _code(row["code"]))])
    # Keep the original query first, then AI codes, then AI words (as before).
    groups[1:1] = code_groups
    # Round robin prevents a broad first keyword from crowding out other interpretations.
    merged = {}
    for index in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if index >= len(group):
                continue
            row = group[index]
            code = _code(row["code"])
            if code in merged:
                merged[code]["matched_terms"] = list(dict.fromkeys(merged[code]["matched_terms"] + row["matched_terms"]))
            elif len(merged) < 16:
                merged[code] = row
    rows = list(merged.values())
    if hsk_catalog.available():
        # 관세청 API 행에도 상위 분류 경로를 붙입니다. ("기타"의 뜻을 화면에서 풀어 줌)
        for row in rows:
            row.setdefault("path", hsk_catalog.path(row["code"]))
    review ={"available": False, "message": analysis.get("message", ""), "assessments": {}}
    if rows and not numeric and analysis.get("available"):
        catalog = hsk_catalog.available()
        for row in rows:
            row["hs_context"] = (hsk_catalog.context(row["code"]) if catalog
                                 else hs_open_client.heading_names(row["code"]))
        review = hs_ai_client.review(text, analysis, rows)
    for row in rows:
        row["relevance"] = review["assessments"].get(_code(row["code"]), {
            "match": "unknown", "reason": "적합도를 확인하지 못했습니다.", "missing_details": []})
    rows.sort(key=lambda row: MATCH_ORDER[row["relevance"]["match"]])
    offline = found.get("source") == "internal"
    result = {"success": True, "source": "internal" if offline else "api", "data": rows,
              "ai_analysis": analysis, **({"offline_note": found.get("offline_note", ""),
                                            "base_date": found.get("base_date", "")} if offline else {}),
              "ai_review": {k: v for k, v in review.items() if k != "assessments"},
              "search_terms": terms, "original_query": text,
              "searched_as": searched_as, "search_failures": failures}
    if not rows:
        # Preserve explicit outage provenance; never dress mock rows as live candidates.
        if found.get("source") == "mock" or not found.get("success"):
            result.update({k: found[k] for k in ("success", "source", "data", "message") if k in found})
        return result
    return compare(result, text, terms, country=country, order=order)


def _tariff(hs6: str, country: str) -> dict:
    unknown = {"available": False, "rate": None, "country": country, "comparable": False}
    if not country:
        return {**unknown, "message": "도착국 선택 후 관세 비교 가능"}
    reporter = tariff_client.reporter_for(country, fta_guide.blocs().get("EU", ()))
    if not reporter:
        return {**unknown, "message": "도착국 세율 조회 미지원"}
    response = tariff_client.fetch_wits(reporter, tariff_client.WORLD, hs6, timeout=8)
    if not response["success"]:
        return {**unknown, "message": response["message"]}
    data = response.get("data") or {}
    rate = data.get("rate")
    if not isinstance(rate, (int, float)) or not math.isfinite(rate) or rate < 0 or not data.get("year"):
        return {**unknown, "message": "비교 가능한 종가세율 자료 없음"}
    return {**unknown, "available": True, "rate": rate, "year": data["year"],
            "min": data.get("min"), "max": data.get("max"), "hs6": hs6,
            "label": "도착국 MFN · HS6 평균", "source": "WITS / UNCTAD TRAINS",
            "message": "참고 평균세율이며 FTA·추가관세·확정 세액을 의미하지 않습니다."}


def rank(rows: list[dict], order: str) -> list[dict]:
    """Relevance gates all ordering; missing data is never treated as zero tax."""
    def key(row):
        relevance = MATCH_ORDER.get(row.get("relevance", {}).get("match", "unknown"), 2)
        nav = row.get("navigation", {})
        count = nav.get("count") if nav.get("available") else None
        tax = row.get("tariff", {})
        rate = tax.get("rate") if tax.get("comparable") else None
        frequency = (count is None, -(count or 0))
        duty = (rate is None, rate if rate is not None else 0)
        return (relevance, *(duty + frequency if order == "tariff" else frequency + duty), row["code"])
    result = sorted(rows, key=key)
    for index, row in enumerate(result, 1):
        relevance = row.get("relevance", {}).get("match", "unknown")
        row["priority"] = index
        row["relevance_label"] = MATCH_LABELS.get(relevance, MATCH_LABELS["unknown"])
    return result


def compare(found: dict, query: str, terms: list[str], *, country: str = "", order: str = "frequency") -> dict:
    """Never interpret a provider's top-name list as total trade statistics."""
    if not found.get("success") or found.get("source") not in LIVE_SOURCES or not found.get("data"):
        return found
    rows = [dict(row) for row in found["data"]]
    country = country.strip().upper()
    order = order if order in ("frequency", "tariff") else "frequency"
    candidates = [row for row in rows if len(re.sub(r"\D", "", row["code"])) == 10][:6]
    app = current_app._get_current_object()

    def fetch(row):
        with app.app_context():
            return customs_extra_client.hs_navigation(row["code"])

    def tax(hs6):
        with app.app_context():
            return _tariff(hs6, country)

    with ThreadPoolExecutor(max_workers=6) as executor:
        navigation_futures = [executor.submit(fetch, row) for row in candidates]
        tariff_futures = {code: executor.submit(tax, code) for code in dict.fromkeys(
            _code(row["code"])[:6] for row in candidates)}
        results = [future.result() for future in navigation_futures]
        tariffs = {code: future.result() for code, future in tariff_futures.items()}
    years = {item["year"] for item in tariffs.values() if item["available"]}
    for row in candidates:
        row["tariff"] = dict(tariffs[_code(row["code"])[:6]])
        row["tariff"]["comparable"] = row["tariff"]["available"] and len(years) == 1
    complete = True
    for row, result in zip(candidates, results):
        if not result["success"]:
            complete = False
            row["navigation"] = {"available": False, "message": result["message"]}
            continue
        names = result["data"]
        if not names:
            complete = False
            row["navigation"] = {"available": False, "message": "내비게이션 집계 결과 없음"}
            continue
        row["navigation"] = {
            "available": True, "count": sum(item["count"] for item in names),
            "names": sorted(names, key=lambda item: -item["count"])[:3],
            "returned_names": len(names), "share": None, "gap_pp": None,
        }
    total = sum(row.get("navigation", {}).get("count", 0) for row in candidates)
    if complete and total:
        shares = sorted((row["navigation"]["count"] / total * 100 for row in candidates), reverse=True)
        for row in candidates:
            nav = row["navigation"]
            share = nav["count"] / total * 100
            nav["share"] = round(share, 1)
            nav["gap_pp"] = round(shares[0] - share, 1)
    compared_codes = {row["code"] for row in candidates}
    rows = rank(candidates + [row for row in rows if row["code"] not in compared_codes], order)
    return {**found, "data": rows, "search_terms": terms, "original_query": query,
            "ranking": {"order": order, "country": country,
                        "label": "적합도 → 관세 낮은 순 → 건수 많은 순" if order == "tariff"
                                 else "적합도 → 건수 많은 순 → 관세 낮은 순",
                        "tariff_note": "관세 비교는 동일 도착국·동일 연도의 MFN HS6 평균세율 기준입니다. "
                                       "FTA 자격·추가관세를 반영한 확정 세율은 별도 확인이 필요합니다.",
                        "mixed_years": len(years) > 1},
            "navigation_summary": {
                "compared": len(candidates), "total": total if complete else None,
                "complete": complete, "source": "관세청 HS CODE 내비게이션 · API043",
                "note": "최대 6개 후보의 API 반환 품목명 목록(일부 상위 품명)의 품목란 건수 합계 기준입니다. "
                        "각 HS의 다른 상품도 포함하며, 전체 신고비율이나 입력 상품의 분류 확률이 아닙니다. "
                        "집계기간·수출입 구분·전체 모집단은 API에서 제공하지 않습니다. "
                        "일부 후보 조회 실패 시 비중·%p 비교를 표시하지 않습니다.",
            }}
