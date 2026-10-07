"""계약서 조항 점검 — 이 건에 필요한 조항을 짚고, 올린 계약서를 읽어 판정합니다.

무엇을 하나
  1. 점검표   이 건(인코텀즈·결제조건)에 걸리는 필수·이익·독소 조항을 냅니다.
  2. 판정     올린 계약서를 읽어 **빠진 필수조항**과 **들어 있는 독소조항**을 찾습니다.
  3. 문안     고른 조항의 영문 문안과 한글 설명을 한 벌로 내보냅니다.

지키는 것
  - **법률 자문이 아닙니다.** 어느 답에도 그 말을 붙입니다.
  - 판정은 **글자를 찾은 결과**입니다. 찾았다/못 찾았다만 말하고,
    "이 조항이 유효하다"거나 "이 계약은 안전하다"고는 말하지 않습니다.
  - AI를 쓰지 않습니다. 키가 없어도 그대로 돕니다. (글자로만 찾습니다)
  - 올린 파일은 **저장하지 않습니다.** 읽고 판정만 합니다.
"""

from __future__ import annotations

import re

from app.processors import clause_topics, contract_clauses
from app.services import ServiceError

MAX_TEXT = 400_000
DISCLAIMER = ("법률 자문이 아닙니다. 여기 문안은 출발점이고, 최종 계약서는 "
              "변호사 검토를 받으세요.")

# ── 거래에 맞춘 판정 (전문가 점검 2026-10-04) ─────────────────────────────────
# 도착국을 알 때, 목록에 없는 나라에서는 독소로 단정하지 않는 조항.
COUNTRY_ONLY = {"ddp_no_ior"}
# 이 계약에 **그 거래가 있을 때만** 권하는 이익조항. 어떤 계약에도 같은 13~16개를
# 권하니, T/T 계약에 신용장 조항을 권해 신뢰를 잃었습니다.
_LC = r"letter\s+of\s+credit|documentary\s+credit|\bL/?C\b|신용장"
_MAKE = (r"\b(?:moulds?|molds?|tooling|dies|jigs?|drawings?|designs?|artwork|OEM|ODM|prototypes?|"
         r"develop(?:ment|ed)?|custom(?:ized|ised|-made)?)\b|금형|도면|설계|디자인|개발|주문\s*제작|시제품")
# 재수출을 이미 막아 둔 계약서 — 넣으라는 주의를 띄우지 않습니다(3회차).
_REEXPORT_SET = re.compile(r"(?:shall|may)\s+not\s+(?:\w+\s+){0,3}?re-?(?:export|sell)|\bend[- ]use(?:r)?\s+"
                           r"(?:certificate|statement|declaration|undertaking)|재수출[^.]{0,30}(?:금지|제한|하여서는"
                           r"\s*아니|할\s*수\s*없)", re.I)
# 2회차: 'exclusive jurisdiction' 의 exclusiv · CIETAC 'Commission' · 'PSI agency' 로 엉뚱한
# 조항을 권해, 거래를 가리키는 말에 묶었습니다.
GAIN_NEEDS = {
    "lc_deadline": _LC,
    "lc_conformity": _LC,
    "deemed_acceptance": r"\bcommissioning\b|\binstallation\b|acceptance\s+(?:test|certificate)|시운전|설치|검수",
    "min_order": r"exclusive\s+(?:distribut|agen|right|suppl|purchas|sale|dealer)|독점\s*(?:공급|판매|대리|수입)|총판",
    "agency_protection": r"\b(?:sales|commercial|exclusive|sole)\s+agen(?:t|cy)\b|\bdistribut(?:or|ion)\s+agreement|"
                         r"\bappoints?\b[^.]{0,40}\b(?:agent|distributor)|대리점|총판",
    # 금형·도면·개발이 없는 원자재 매매에 금형 소유권·도면 보증·금형 인수를 권했습니다(3회차).
    "ip": _MAKE,
    "buyer_design_ip": _MAKE,
    "exit_buyback": _MAKE,
}
_ICC_C = re.compile(r"(?:\bICC|institute\s+cargo\s+clauses?)\s*\(?\s*C\s*\)?", re.I)


_GAB_EUL = re.compile(r"(?<![가-힣])[갑을](?:은|는|이|가|의|에게)\s")


def _party_ab_unknown(body: str) -> bool:
    """Party A/B 로만 부르는데 매도인·매수인을 못 정한 계약서."""

    return (len(re.findall(r"\bParty\s+[AB]\b", body)) >= 2
            and len(re.findall(r"\b(?:seller|buyer)\b", body, re.I)) < 2)


def _side_shown(body: str, analysis: dict) -> dict | None:
    """화면에 '우리 쪽을 … 로 읽었습니다'로 보일 값. Supplier·Customer 계약서도 밝힙니다."""

    if analysis.get("side"):
        return analysis["side"]
    roles = analysis.get("roles") or {}
    if roles:
        return {"label": roles.get("Seller", "Seller"), "name": "",
                "other_label": roles.get("Buyer", "Buyer"), "other_name": ""}
    return None


_CJK = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
_READABLE = re.compile(r"[A-Za-z가-힣]")
_CONTRACTISH = re.compile(r"\b(?:contract|agreement|terms\s+and\s+conditions|purchase\s+order|seller|buyer|"
                          r"supplier|party\s+[AB])\b|계약|매도인|매수인|(?<![가-힣])[갑을](?:은|는|이|가)\s", re.I)
_INCOTERMS = re.compile(r"\b(EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP)\b")


def _language_note(text: str) -> str:
    """중국어·일본어 계약서는 판정하지 못합니다 — '독소 0개'로 안심시켰습니다(사용성 4회차)."""

    cjk, readable = len(_CJK.findall(text)), len(_READABLE.findall(text))
    if cjk > readable:
        raise ServiceError("중국어·일본어 계약서는 아직 판정하지 못합니다 — 이대로 보면 위험한 조항을 '없다'고 "
                           "잘못 알려 드리게 됩니다. 영문본이나 국문본을 올려 주세요.", "UNSUPPORTED_LANG")
    if cjk >= 100:
        return "중국어·일본어로만 적힌 부분은 읽지 못합니다 — 그 부분의 조항은 판정에 들어가지 않았습니다."
    return ""


def _terms_in(text: str) -> str:
    """본문에 가장 많이 나온 인코텀즈(같으면 먼저 나온 것)."""

    found = _INCOTERMS.findall(text)
    if not found:
        return ""
    return max(dict.fromkeys(found), key=found.count)


def _mark_same_evidence(rows: list[dict]) -> list[dict]:
    """같은 문장이 두 독소의 근거면 뒤의 것에 same_as(앞 조항 제목)를 답니다 — 지연배상 한
    문장이 '무제한 손해배상'과 '상한 없는 지연배상금'에 똑같이 두 번 나왔습니다(사용성 3회차)."""

    seen: dict[str, str] = {}
    for row in rows:
        evidence = row.get("evidence") or ""
        row["same_as"] = seen.get(evidence, "") if evidence else ""
        if evidence and evidence not in seen:
            seen[evidence] = row["title"]
    return rows


def _relevant(key: str, body: str) -> bool:
    need = GAIN_NEEDS.get(key)
    return not need or bool(re.search(need, body, re.I))


def _judge_by_deal(analysis: dict, body: str, incoterms: str) -> None:
    """인코텀즈에 따라 달라지는 판정. CIP 인데 ICC(C) 로 부보하면 보험은 '부족'입니다."""

    insurance = analysis["clauses"].get("insurance")
    if (incoterms or "").upper() == "CIP" and insurance and insurance["status"] == "present" \
            and _ICC_C.search(body):
        insurance.update(status="weak", reason="CIP 인데 **ICC(C)** 로 부보합니다 — 2020판 CIP 는 "
                                               "ICC(A) 가 기본입니다. 바이어와 따로 합의하지 않았다면 "
                                               "ICC(A) 로 바꾸세요.")


def _readable(text: str) -> str:
    """조항 설명 속 **내부 이름**(buyer_set_off 등)을 화면 이름으로.

    조항 설명이 서로를 가리킬 때 key 를 그대로 적어 두어, 화면에 "독소조항
    buyer_set_off 의 반대편입니다"가 나왔습니다. 8곳이었습니다. 하나씩 고치면
    새 문구에서 또 생기므로, 내보내는 길목에서 바꿉니다. (2026-10-03)
    """

    def name(m: re.Match) -> str:
        row = contract_clauses.by_key(m.group("short") or m.group("long"))
        return f"‘{row['title']}’" if row else m.group(0)

    # 밑줄 없는 key(ip)는 '…조항 ip' 꼴일 때만 바꿉니다. 바로 뒤의 "(최소 주문…)" 같은
    # 덧붙인 이름은 지웁니다 — "‘최소 주문…’(최소 주문…)" 처럼 두 번 나왔습니다.
    # 그리고 "‘…’ 를" 의 띄어쓰기를 붙입니다. (전문가 점검 2026-10-04)
    out = re.sub(r"(?:(?<=조항 )(?P<short>[a-z]+(?:_[a-z]+)*)|\b(?P<long>[a-z]+(?:_[a-z]+)+))\b"
                 r"(?:\s*\([^)]*\))?", name, str(text or ""))
    return re.sub(r"’ (?=(?:을|를|은|는|이|가|의|와|과|에|로|으로)(?:\s|$))", "’", out)


def checklist(incoterms: str = "", present: set[str] | None = None,
              country: str = "", analysis: dict | None = None) -> dict:
    """이 건에 걸리는 조항 점검표.

    present를 주면(올린 계약서에서 보인 조항) 줄마다 있음/없음을 함께 답니다.

    country(도착국 2자리)를 주면 그 나라에 **특히 흔한** 조항에 for_country 를
    달고, 독소 묶음에서 앞으로 올립니다. 계약서를 올리기 전에도 "중국으로
    보내시는군요 — 이 셋을 특히 보세요"를 말할 수 있습니다. (2026-10-02)

    **찾는 일에는 나라를 쓰지 않습니다.** 도착국을 몰라도 다 찾아야 하고,
    중국 중재 조항은 어디로 보내든 독소입니다.
    """

    present = present or set()
    # analysis(analyze 결과)를 주면 줄마다 판정(status)·근거 문장·까닭을 답니다.
    # 가공계약에만 있는 조항(context)은 그 문서가 가공계약일 때만 냅니다. (2026-10-02)
    judged = (analysis or {}).get("clauses", {})
    contexts = (analysis or {}).get("context", set())
    tags = contract_clauses.groups_for(country)
    out: dict[str, list[dict]] = {"must": [], "gain": [], "toxic": []}
    for row in contract_clauses.CLAUSES:
        if not contract_clauses.applies_to(row, incoterms):
            continue
        if row["context"] and row["key"] not in contexts:
            continue
        seen = judged.get(row["key"]) or {}
        _, group_id, group_label = contract_clauses.toxic_group(row["key"])
        out[row["category"]].append({
            "key": row["key"], "title": row["title"], "why": _readable(row["why"]),
            "risk": _readable(row["risk"]), "text_ko": _readable(row["text_ko"]),
            "fix": _readable(row["fix"]),
            "present": row["key"] in present,
            "status": seen.get("status") or ("present" if row["key"] in present else "absent"),
            "evidence": seen.get("evidence", ""),
            "reason": seen.get("reason", ""),
            "countries": list(row["countries"]),
            # DDP 가 아닌 거래에 'DDP 수입자' 배지를 달지 않습니다 — 판정 뒤 도착국 칸과 맞춥니다(3회차).
            "for_country": bool(tags & set(row["countries"]))
                           and not (row["key"] == "ddp_no_ior" and (incoterms or "").upper() not in ("", "DDP")),
            "group": group_id, "group_label": group_label,
        })
    if tags:
        # 그 나라 것을 앞으로. 그 안에서는 원래 순서를 지킵니다(sort 는 안정적입니다).
        for category in out:
            out[category].sort(key=lambda item: not item["for_country"])
    # 독소조항은 묶음 순서로 — 묶음 안에서는 위의 순서(도착국 먼저)를 지킵니다.
    out["toxic"].sort(key=lambda item: contract_clauses.toxic_group(item["key"])[0])
    return out


_LONG_RUN = re.compile(r"(\S){11,}")


def _guard_text(body: str) -> str:
    """병적인 글(같은 글자·같은 토막의 반복)을 분석 전에 걸러냅니다.

    4KB 의 "1111…" 하나가 정규식 폭증으로 14초, 8KB 면 70초 동안 서버 전체를 멈췄습니다(전수 점검 4회차 —
    파이썬 re 는 GIL 을 놓지 않아 같은 프로세스의 모든 요청이 섰습니다). 진짜 계약서는 같은 글자가 12번
    이상 이어지는 곳이 밑줄·점선뿐이고, 압축하면 20~40% 로 줄지 몇 %로 줄지 않습니다.
    """

    body = _LONG_RUN.sub(lambda m: m.group(1) * 12, body)
    if len(body) > 5000:
        import zlib
        raw = body.encode("utf-8", errors="ignore")
        if len(zlib.compress(raw, 1)) / max(1, len(raw)) < 0.04:
            raise ServiceError("같은 글자·문장이 되풀이되는 글이라 계약서로 읽을 수 없습니다. "
                               "계약서 본문이나 파일을 넣어 주세요.", "NOT_CONTRACT")
    return body


def review(text: str, incoterms: str = "", country: str = "") -> dict:
    """올린 계약서 판정.

    missing  빠진 필수조항 — 넣어야 합니다
    toxic    들어 있는 독소조항 — 지우거나 고쳐야 합니다
    gain     아직 없는 이익조항 — 챙기면 우리가 덜 잃습니다
    present  보이는 조항 전부
    """

    body = str(text or "")
    if not body.strip():
        raise ServiceError("읽을 글이 없습니다. 계약서 파일이나 글을 넣어 주세요.",
                           "VALIDATION_ERROR")
    full_length = len(body)
    body = _guard_text(body[:MAX_TEXT])
    analysis = contract_clauses.analyze(body[:MAX_TEXT])
    if analysis.get("empty"):
        # 못 읽은 것을 '필수조항이 전부 빠졌다'고 하면 안 됩니다.
        raise ServiceError("쪽 번호·머리글만 읽혔고 계약서 본문을 찾지 못했습니다. 스캔본이면 "
                           "글자가 있는 PDF로 다시 저장하거나, 본문을 붙여 넣어 주세요.",
                           "UNREADABLE")
    head = body[:MAX_TEXT]
    lang_note = _language_note(head)
    if not analysis["clauses"] and not _CONTRACTISH.search(head):
        # "hello" · 견적 문의 글에 '빠진 필수 13개'를 냈습니다(사용성 4회차).
        raise ServiceError("계약서로 보이지 않습니다 — 결제·선적·준거법 같은 계약 조항을 하나도 찾지 못했습니다. "
                           "계약서 본문이나 파일을 넣어 주세요.", "NOT_CONTRACT")
    country = (country or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", country):
        country = ""
    # 인코텀즈를 '모름'으로 두면 계약서의 CIF 를 보고도 보험 누락을 안 짚었습니다(사용성 4회차) —
    # 본문에서 읽어 쓰고, 고른 값과 다르면 알립니다.
    chosen = (incoterms or "").strip().upper()
    in_doc = _terms_in(head)
    incoterms = chosen or in_doc
    _judge_by_deal(analysis, body[:MAX_TEXT], incoterms)
    found ={key for key, row in analysis["clauses"].items() if row["status"] == "present"}
    rows = checklist(incoterms, found, country, analysis)
    # 도착국에서 문제가 안 되는 나라별 독소 — 독일 DDP 는 EORI·간접대리인으로 수입자가
    # 될 수 있습니다(전문가 점검 2026-10-04). 도착국을 모르면 그대로 짚습니다.
    tags = contract_clauses.groups_for(country)
    if tags:
        rows["toxic"] = [row for row in rows["toxic"]
                         if not (row["key"] in COUNTRY_ONLY and row["countries"]
                                 and not tags & set(row["countries"]))]
    # 이 계약에 맞지 않는 이익조항은 권하지 않습니다 — T/T 계약에 신용장 조항, 일반
    # 매매에 대리점 보호법, 비독점에 최소 주문, 소비재에 시운전 간주 인수.
    rows["gain"] = [row for row in rows["gain"]
                    if row["status"] != "absent" or _relevant(row["key"], body[:MAX_TEXT])]
    # 도착국에 흔한데 **아직 안 보이는** 독소조항. 올린 계약서에 없더라도
    # 협상 중에 들어올 수 있어 미리 알려 줍니다. (2026-10-02)
    # DDP 가 아닌 거래에 'DDP 수입자' 주의를 띄우지 않습니다(2회차).
    deal = (incoterms or "").upper()
    # **DDP 로 그 나라에 보낸다고 직접 넣었으면** 문장이 없어도 독소입니다 — 거래 조건
    # 자체가 문제입니다. 전에는 '협상 중에 들어올 수 있다'(주의)로만 냈습니다(3회차).
    if tags and (deal == "DDP" or (not deal and re.search(r"\bDDP\b", body[:MAX_TEXT]))):
        for row in rows["toxic"]:
            if row["key"] == "ddp_no_ior" and row["for_country"] and not row["present"]:
                row.update(present=True, status="present",
                           reason=f"인코텀즈 DDP · 도착국 {country.upper()} 로 넣으셨습니다 — 계약서에 "
                                  "문장이 없어도 이 거래 조건이 문제입니다.")
    watch = [row for row in rows["toxic"] if row["for_country"] and not row["present"]
             and not (row["key"] == "ddp_no_ior" and deal not in ("", "DDP"))
             and not (row["key"] == "reexport_control" and _REEXPORT_SET.search(body[:MAX_TEXT]))]
    for row in watch:
        row["watch_note"] = WATCH_NOTE.get(row["key"], "")
    # 규칙이 **주제째 놓친** 조항 — 주제 분류기가 고릅니다. 판정은 바꾸지 않고
    # 빠진 필수조항에 "이 문장일 수 있습니다"를 덧붙이거나, '확인 필요'로 냅니다.
    # (2026-10-03, app/processors/clause_topics.py)
    category = {row["key"]: row["category"] for row in contract_clauses.CLAUSES}
    # 주제 분류기도 갑/을·Supplier 를 바꿔 읽은 글로 봅니다 — 원문을 보면 "누가 의무를 지는지
    # 가리지 못했습니다"가 나왔습니다(2회차).
    maybe = clause_topics.candidates(contract_clauses.normalized(body[:MAX_TEXT]), analysis["clauses"], category)
    # 보여 줄 문장은 **계약서에 적힌 이름**으로 — "Seller warrants that Buyer may …" 는
    # 계약서에서 찾을 수 없습니다. 독소 근거와 겹치는지도 원문끼리 봅니다(3회차).
    for c in maybe:
        c["sentence"] = contract_clauses.original_words(c["sentence"], analysis.get("side"),
                                                        analysis.get("roles"))
    # 독소로 이미 짚은 문장은 '직접 확인'에 다시 내지 않습니다(사용성 2회차 — 같은 관할
    # 문장이 🔴 독소와 ⚪ '양쪽에 같게 걸림'으로 동시에 나왔습니다).
    toxic_text = " ".join(row.get("evidence", "") for row in analysis["clauses"].values())
    # 앞 60자만 견주면, 확인 문장이 제목("13. DISPUTE RESOLUTION All disputes …")부터 시작하고
    # 독소 근거는 그 안의 뒷문장일 때 못 거릅니다(3회차) — 근거가 문장 **안에** 드는지도 봅니다.
    cores = [core for core in (row.get("evidence", "").strip("… ")[:40] for row in analysis["clauses"].values()
                               if row["status"] == "present") if len(core) >= 25]
    maybe = [c for c in maybe if c["kind"] != "check"
             or not (c["sentence"][:60] in toxic_text or any(core in c["sentence"] for core in cores))]
    missing = [row for row in rows["must"] if row["status"] == "absent"]
    for row in missing:
        hint = next((c for c in maybe if c["kind"] == "must" and row["key"] in c["keys"]), None)
        row["maybe"] = hint["sentence"] if hint else ""
    return {
        "missing": missing,
        "check": [c for c in maybe if c["kind"] == "check"],
        "toxic": _mark_same_evidence([row for row in rows["toxic"] if row["present"]]),
        # **적혀 있으나 제 구실을 못 하는** 필수·이익조항 — 미정·부정·불리·무력.
        # '있다'고 하면 안심시키고, '없다'고 하면 이미 쓴 사람에게 넣으라고
        # 합니다. 둘 다 아니라서 따로 냅니다. (2026-10-02)
        "weak": [row for row in rows["must"] + rows["gain"] if row["status"] == "weak"],
        "gain": [row for row in rows["gain"] if row["status"] == "absent"],
        "ok_must": [row for row in rows["must"] if row["present"]],
        "present": sorted(found),
        "country": (country or "").upper(),
        "watch_country": watch,
        # Party A/B 계약서에서 누구를 우리(매도인)로 읽었는지. 틀렸으면
        # 사용자가 바로 알아야 합니다 — 방향이 뒤집히면 판정도 뒤집힙니다.
        "our_side": _side_shown(body[:MAX_TEXT], analysis),
        # 갑/을 계약서인데 누가 우리인지 못 정했으면 알립니다 — 방향이 뒤집히면 우리
        # 권리를 독소로 짚습니다(2회차).
        # Party A/B 도 — 정의를 못 읽으면 판정이 전부 0건이었는데 아무 말이 없었습니다(전문가 4회차).
        "side_unknown": not analysis["side"] and (bool(_GAB_EUL.search(body[:MAX_TEXT]))
                                                  or _party_ab_unknown(body[:MAX_TEXT])),
        # 40만 자를 넘으면 앞만 봅니다 — 그걸 밝힙니다. 전에는 뒤를 안 보면서
        # 글자 수는 전체를 적어 '다 읽었다'고 했습니다. (2026-10-04)
        "checked": min(full_length, MAX_TEXT),
        # 판정 기준 — 결과 위에 "CIF · 중국(CN) 기준"으로 적습니다(사용성 4회차).
        "incoterms": (incoterms or "").upper(),
        "incoterms_from_doc": in_doc if not chosen else "",
        "incoterms_mismatch": in_doc if chosen and in_doc and in_doc != chosen else "",
        "blanks": len(contract_clauses._BLANK.findall(head)),
        "review_notes": [lang_note] if lang_note else [],
        "truncated": full_length > MAX_TEXT,
        "note": DISCLAIMER,
    }


def read_file(filename: str, data: bytes) -> str:
    """계약서 파일에서 글자만 꺼냅니다. (PDF·Word·사진·텍스트) — read_contract 의 글자."""

    return read_contract(filename, data)[0]


def read_contract(filename: str, data: bytes) -> tuple[str, list[str]]:
    """계약서 파일의 (글자, 알림). 알림은 화면 상태줄에 그대로 붙입니다.

    사진·스캔이면 우리 컴퓨터의 OCR 로 읽고, 쓸 수 없으면 빈 글자입니다. **AI는 부르지
    않습니다.** 어디까지 읽었는지를 말없이 버리지 않게 알림으로 냅니다(사용성 점검
    2회차 — 60쪽·10쪽 넘는 부분과 OCR 이 못 읽은 쪽을 말없이 버렸습니다).
    """

    from app.services import document_extract_service as extract

    name = str(filename or "").lower()
    if not data or not data.strip():
        raise ServiceError("빈 파일입니다. 내용이 있는 계약서 파일을 올려 주세요.", "VALIDATION_ERROR")
    if name.endswith((".txt", ".md")):
        text = _decode(data)
        if not text.strip():
            raise ServiceError("빈 파일입니다. 내용이 있는 계약서 파일을 올려 주세요.", "VALIDATION_ERROR")
        return text, []
    if name.endswith(".docx"):
        return _read_docx_with_notes(data)
    text, notes, pages = _read_pages(name, data)
    note = _missing_pages(text, pages)
    if note:
        notes.append(note)
    return text, notes


def _read_pages(name: str, data: bytes) -> tuple[str, list[str], int]:
    """PDF·사진의 (글자, 알림, 올라온 쪽 수)."""

    from app.services import document_extract_service as extract

    notes: list[str] = []
    if name.endswith(".pdf"):
        texts, scans, pages = _read_contract_pdf(data)
        if pages > MAX_PDF_PAGES:
            notes.append(f"PDF 가 {pages}쪽이라 앞 {MAX_PDF_PAGES}쪽만 봤습니다 — 뒷부분은 나눠 올려 주세요.")
        text = "\n".join(texts).strip()
        # 글자 있는 쪽이 하나라도 있으면 빈 쪽만 OCR 합니다. 전부 그림이면 아래의 스캔본 길.
        if scans and any(_body_chars(page_text) >= 40 for page_text in texts):
            return (*_with_scanned_pages(texts, scans, notes), pages)
        images = list(scans.values())
    else:
        text, images, pages = "", extract._read_image(data), 1
    # **본문이 거의 없으면 OCR.** 쪽 번호("Page 1 of 1")만 글자로 박힌 스캔본도 OCR 합니다.
    if images and _body_chars(text) < extract.SCANNED_TEXT_CHARS:
        found, blank = _ocr_pages(images)
        if _body_chars(found) > _body_chars(text):
            kind = "스캔본" if name.endswith(".pdf") else "사진"
            notes.append(f"{kind}이라 그림에서 글자를 읽었습니다(OCR) — 틀린 글자가 있을 수 있으니 "
                         "중요한 조항은 원문과 맞춰 보세요.")
            if pages > MAX_OCR_PAGES:
                notes.append(f"스캔본은 앞 {MAX_OCR_PAGES}쪽만 읽습니다 — 뒷부분은 나눠 올려 주세요.")
            if blank:
                notes.append(f"{', '.join(map(str, blank))}쪽은 글자를 읽지 못했습니다.")
            return found, notes, pages
    return text, notes, pages


# "Page 1 of 3" · "1 / 3" · "- 1 of 3 -" — 문서가 스스로 적은 전체 쪽 수.
_PAGE_OF = re.compile(r"\b(?:page|p\.)\s*(\d{1,3})\s*(?:of|/)\s*(\d{1,3})\b|(\d{1,3})\s*/\s*(\d{1,3})\s*쪽", re.I)


def _missing_pages(text: str, pages: int) -> str:
    """문서가 'Page 1 of 3' 이라고 적었는데 그보다 적은 쪽이 올라왔으면 알림.

    사진 한 장(1쪽)만 올리고 '빠진 필수 9개'를 받았습니다 — 나머지 쪽에 있었을 수 있습니다
    (사용성 3회차).
    """

    totals = [int(m.group(2) or m.group(4)) for m in _PAGE_OF.finditer(text or "")]
    totals = [total for total in totals if 1 < total <= 300]
    if not totals:
        return ""
    total = max(totals)
    if pages >= total:
        return ""
    return (f"문서에 전체 {total}쪽이라고 적혀 있는데 {pages}쪽만 올라왔습니다 — 나머지 쪽도 올려 "
            "주셔야 '빠진 조항' 판정이 맞습니다.")


def _ocr_pages(images: list) -> tuple[str, list[int]]:
    """쪽마다 OCR — (글자, 못 읽은 쪽 번호). 국문은 글자마다 띄어 읽는 버릇을 고칩니다."""

    from app.processors import bank_redaction, ocr

    if not (ocr.available() and bank_redaction.ocr_available()):
        return "", []
    # 쪽 표시("[2쪽]")는 넣지 않습니다 — 근거 문장에 "[2쪽] 제 6 조 …" 로 섞였습니다(사용성 3회차).
    pages, blank = [], []
    for no, image in enumerate(images, 1):
        page = _join_hangul(ocr.read_text(image))
        if page.strip():
            pages.append(page)
        else:
            blank.append(no)
    return "\n\n".join(pages), blank


def _with_scanned_pages(texts: list[str], scans: dict, notes: list[str]) -> tuple[str, list[str]]:
    """글자 쪽과 스캔 쪽이 **섞인** PDF — 글자가 없는 쪽만 OCR 해서 제자리에 끼웁니다.

    전에는 문서 전체에 글자가 있으면 그림을 안 만들어, 서명 뒤에 스캔해 붙인 쪽의
    준거법·중재를 '빠진 필수'로 냈습니다(사용성 3회차 — 글자 6쪽 + 스캔 2쪽).
    """

    from app.processors import bank_redaction, ocr

    numbers = [no + 1 for no in sorted(scans)]
    if not (ocr.available() and bank_redaction.ocr_available()):
        notes.append(f"{', '.join(map(str, numbers))}쪽은 스캔(그림)이라 읽지 못했습니다 — 그 쪽의 조항은 "
                     "판정에 들어가지 않았습니다.")
        return "\n".join(texts).strip(), notes
    out, blank = list(texts), []
    for index, image in scans.items():
        page = _join_hangul(ocr.read_text(image))
        if page.strip():
            out[index] = page
        else:
            blank.append(index + 1)
    read = [no for no in numbers if no not in blank]
    if read:
        notes.append(f"{', '.join(map(str, read))}쪽은 스캔(그림)이라 OCR 로 읽었습니다 — 틀린 글자가 있을 "
                     "수 있으니 그 쪽의 조항은 원문과 맞춰 보세요.")
    if blank:
        notes.append(f"{', '.join(map(str, blank))}쪽은 비어 있거나 글자를 읽지 못했습니다.")
    return "\n".join(out).strip(), notes


def _join_hangul(text: str) -> str:
    """OCR 이 국문을 "갑 은 언제든지 서면 통 지 로" 처럼 글자마다 띄어 읽으면 규칙이 하나도
    안 걸립니다(사용성 점검 2회차 — 국문 스캔·사진이 '독소 0개'). 한 글자짜리 한글 낱말이
    줄의 절반을 넘는 줄만, 한 글자 낱말 앞뒤의 띄어쓰기를 붙입니다."""

    out = []
    for line in text.splitlines():
        words = line.split()
        singles = sum(1 for word in words if re.fullmatch(r"[가-힣]", word))
        if len(words) >= 4 and singles * 2 >= len(words):
            line = re.sub(r"(?<=[가-힣]) (?=[가-힣](?:\s|$))", "", line)
            line = re.sub(r"(?:(?<=^[가-힣])|(?<=\s[가-힣])) (?=[가-힣])", "", line)
            line = re.sub(r"(?<=[가-힣]) (?=[가-힣](?:\s|$))", "", line)
        out.append(line)
    return "\n".join(out)


# 계약서 읽기 한도 (2026-10-04). 오퍼시트용 읽기 함수(앞 5쪽·스캔 3쪽)를 같이 써서
# 8쪽 계약서 끝의 중재 조항을 '빠짐'이라 하고 뒤쪽 독소를 놓쳤습니다.
MAX_PDF_PAGES = 60
MAX_OCR_PAGES = 10


def _body_chars(text: str) -> int:
    """쪽 머리글·목차를 걷어 낸 본문 글자 수."""

    body = contract_clauses._drop_page_furniture(contract_clauses._drop_table_of_contents(text or ""))
    return len(re.sub(r"\s+", "", body))


def _decode(data: bytes) -> str:
    """텍스트 파일 — UTF-8(BOM 포함) 다음 CP949(메모장 기본 저장)를 봅니다.

    전에는 UTF-8 로만 읽어, 메모장으로 저장한 국문 계약서가 깨진 채 '독소 0개'가
    나왔습니다. 둘 다 아니면 깨진 채로 판정하지 않습니다.
    """

    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    text = data.decode("utf-8", errors="replace")
    if text.count("�") > max(3, len(text) // 100):
        raise ServiceError("글자를 읽지 못했습니다. 메모장에서 '다른 이름으로 저장 → 인코딩 UTF-8'로 "
                           "저장해 올리거나, 본문을 붙여 넣어 주세요.", "UNREADABLE")
    return text


def _read_docx_with_notes(data: bytes) -> tuple[str, list[str]]:
    import io

    import docx

    from app.processors import safe_files

    try:
        safe_files.check_docx(data)                       # 압축 폭탄(240KB → 풀면 200MB)은 열지 않습니다
    except safe_files.UnsafeFile as exc:
        raise ServiceError(str(exc), "VALIDATION_ERROR")
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception:
        raise ServiceError("Word 파일을 열지 못했습니다. 암호가 걸려 있거나 손상되었을 수 있습니다. "
                           "PDF로 저장해 올려 주세요.", "VALIDATION_ERROR")
    text, tracked = _docx_text(document)
    text = safe_files.clip(text)
    notes = ["Word 의 **변경 추적(수정 표시)**이 있어, 수정을 반영한 본문(넣은 글 포함 · 지운 글 제외)으로 "
             "판정했습니다. 상대가 새로 넣은 문장도 판정에 들어갔습니다."] if tracked else []
    return text, notes


def _read_docx(data: bytes) -> str:
    """Word 계약서 — 문단과 표 칸의 글자. 실무 계약서는 docx 가 가장 흔합니다."""

    import io

    import docx

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception:
        raise ServiceError("Word 파일을 열지 못했습니다. 암호가 걸려 있거나 손상되었을 수 있습니다. "
                           "PDF로 저장해 올려 주세요.", "VALIDATION_ERROR")
    return _docx_text(document)[0]


def _docx_text(document) -> tuple[str, bool]:
    """(글자, 변경 추적 여부). python-docx 의 .text 는 변경 추적으로 **넣은 글**(w:ins)·콘텐츠
    컨트롤(w:sdt)·머리글/바닥글을 빼서, 바이어가 수정 표시로 넣어 돌려준 독소조항을 놓쳤습니다
    (사용성 4회차). 문단 XML 의 w:t 를 모두 모읍니다 — 지운 글(w:delText)은 들어가지 않습니다."""

    from docx.oxml.ns import qn

    W_P, W_T, W_TAB, W_BR = qn("w:p"), qn("w:t"), qn("w:tab"), qn("w:br")

    def para(p) -> str:
        return "".join((node.text or "") if node.tag == W_T else " " for node in p.iter(W_T, W_TAB, W_BR))

    body = document.element.body
    lines = []
    for child in body.iterchildren():
        if child.tag == qn("w:tbl"):
            for tr in child.iter(qn("w:tr")):
                cells = [" ".join(para(p) for p in tc.iter(W_P)) for tc in tr.iterchildren(qn("w:tc"))]
                lines.append(" ".join(cells))
        else:
            lines.extend(para(p) for p in ([child] if child.tag == W_P else child.iter(W_P)))
    seen = set()
    for section in document.sections:
        for part in (section.header, section.footer):
            try:
                element = part._element
            except Exception:
                continue
            for p in element.iter(W_P):
                text = para(p)
                if text.strip() and text not in seen:
                    seen.add(text)
                    lines.append(text)
    tracked = body.find(".//" + qn("w:ins")) is not None or body.find(".//" + qn("w:del")) is not None
    return "\n".join(lines), tracked


def _read_contract_pdf(data: bytes) -> tuple[list[str], dict, int]:
    """PDF 의 쪽마다 글자(60쪽까지), 글자가 없는 쪽의 그림 {쪽 index: 그림}(10쪽까지), 전체 쪽 수."""

    import io

    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if not pdf.pages:
                raise ServiceError("빈 PDF입니다. 내용이 있는 파일을 올려 주세요.", "VALIDATION_ERROR")
            total = len(pdf.pages)
            pages = pdf.pages[:MAX_PDF_PAGES]
            texts = [(page.extract_text() or "") for page in pages]
            empty = [i for i, page_text in enumerate(texts) if _body_chars(page_text) < 40]
            from app.processors import safe_files

            images = {i: safe_files.render_page(pages[i], 150) for i in empty[:MAX_OCR_PAGES]}
    except ServiceError:
        raise
    except Exception:
        raise ServiceError("PDF를 열지 못했습니다. 암호가 걸려 있거나 파일이 손상되었을 수 "
                           "있습니다. 다시 저장해 올리거나 본문을 붙여 넣어 주세요.",
                           "VALIDATION_ERROR")
    return texts, images, total



def country_of(shipment) -> str:
    """이 건의 도착국 ISO 2자리. 못 알아내면 빈 글자입니다.

    도착국을 알면 그 나라에 흔한 독소조항을 앞세울 수 있습니다. 계약서를 올리기
    전에도 경고가 되므로, 운송 계획에 적힌 값을 그대로 씁니다. (2026-10-02)

    document_service 가 FTA 협정을 찾을 때 쓰는 방식과 같습니다.
      1) destination_country ("NL" 또는 "NL · 네덜란드")
      2) 비어 있으면 destination_code 앞 두 글자 (UN/LOCODE)

    **못 알아내면 비웁니다.** 억지로 맞추면 엉뚱한 나라의 조항을 앞세웁니다.
    공항 부호(IATA · ICN·LAX)는 나라를 담지 않으므로 이 길로는 못 알아냅니다.
    """

    # **isascii() 를 함께 봅니다.** 파이썬 isalpha() 는 한글도 True 라서,
    # "네덜란드" 에서 "네덜" 을 국가코드로 내놓았습니다. (2026-10-02 실제로 그랬습니다)
    # 나라 칸에 한글만 적힌 건은 도착지 부호 쪽으로 넘깁니다.
    def _iso2(value: str) -> str:
        head = value[:2]
        return head if len(head) == 2 and head.isascii() and head.isalpha() else ""

    text = str(getattr(shipment, "destination_country", "") or "").strip().upper()
    found = _iso2(text)
    if found:
        return found
    code = str(getattr(shipment, "destination_code", "") or "").strip().upper()
    # UN/LOCODE 는 다섯 글자(NLRTM)입니다. 세 글자는 공항 부호(ICN)라 나라가 없습니다.
    return _iso2(code) if len(code) == 5 else ""

def clause_text(keys) -> str:
    """고른 조항의 문안을 한 벌로. 계약서에 그대로 붙여 쓸 수 있게 냅니다."""

    lines = ["# 계약서 조항 문안", "",
             f"※ {DISCLAIMER}", ""]
    for head, row in _picked(keys):
        if head:
            lines += [f"# 🔴 {head}", ""]
        mark = contract_clauses.CATEGORIES[row["category"]]
        lines += [f"## [{mark}] {row['title']}", "",
                  f"{_labels(row)[0]}: {_readable(row['why'])}",
                  f"{_labels(row)[1]}: {_readable(row['risk'])}", ""]
        if row["category"] == "toxic":
            lines += [toxic_note(row["key"]), ""]
            if row["fix"]:
                lines += [f"고치는 법: {_readable(row['fix'])}", ""]
        lines += ["```", row["text_en"], "```", "", _readable(row["text_ko"]), "", "---", ""]
    return "\n".join(lines).rstrip() + "\n"


_CATEGORY_ORDER = {"toxic": 0, "must": 1, "gain": 2}


# 독소 문안 머리의 한 줄. 대부분 '빼는 것'이지만, 그 말이 틀린 조항이 있습니다
# (전문가 점검 2026-10-04): 재수출 통제는 **없을 때** 위험하고, EU 대리인 보상
# 포기 문구는 지워도 효력이 없습니다.
# 2회차: 고치는 법이 '빼라'가 아니라 '붙여라·바꿔라'인 조항이 더 있었습니다. 그리고 EU
# 대리인은 "지워도"가 아니라 "**적어 두어도** 효력이 없다"가 맞습니다(강행규정).
TOXIC_NOTE = {
    "reexport_control": "이 조항은 **없을 때** 위험합니다 — 아래 문구를 **넣으세요**.",
    "agency_law_eu": "보상 포기 문구는 **적어 두어도 효력이 없습니다** — 보상을 예산에 잡거나 구조를 바꾸세요.",
    "uncapped_ld": "지연배상에 **상한**(예: 계약금액의 5~10%)을 **붙이도록** 고치세요.",
    "exclusive_no_moq": "독점을 주려면 **최소 구매량**을 **함께 넣도록** 고치세요.",
    "ddp_no_ior": "**DAP 등으로 조건을 바꾸거나**, 우리가 수입자가 될 수 있는지 먼저 확인하세요.",
    "us_jury_punitive": "**중재로 바꾸거나**, 배심재판 포기·징벌적 손해 배제를 **넣으세요**.",
    "withholding_no_grossup": "**gross-up(떼인 만큼 더 지급)과 원천징수 증명서 교부**를 넣도록 고치세요.",
    "arbitrator_one_sided": "상대가 혼자 정하는 문구를 **빼고**, 중재기관 규칙이나 **양쪽 합의**로 정하게 고치세요.",
    "receivables_assign_ban": "양도 금지를 **빼거나**, 은행·팩토링사·무역보험사로의 양도는 **허용하도록** 고치세요.",
    "br_agent_indemnity": "보상 문구는 **지워도 효력이 없습니다** — 보상을 예산에 잡거나 판매점 구조로 바꾸세요.",
}
# 도착국에서 흔한데 아직 안 보일 때의 한 줄. 대부분은 '들어오면 지우라'지만, 재수출 통제는
# 없는 것이 위험이라 '넣으라'입니다(2회차 — 두바이 판매점에 거꾸로 안내했습니다).
WATCH_NOTE = {
    "reexport_control": "재수출 금지·최종용도 확인 문구를 **넣으세요** — 지금 없는 것이 위험입니다.",
    # 새 조항 6종(2026-10-06) — 문장이 없을 때 해야 할 일이 다릅니다.
    "withholding_no_grossup": "바이어가 대금에서 세금을 떼는 나라입니다 — **떼인 만큼 더 지급(gross-up)하고 원천징수 "
                              "증명서를 주는 문구**를 넣으세요. 없으면 그 세금은 우리 몫입니다.",
    "licence_in_buyer_name": "수입 허가·제품 등록이 필요하면 **우리 명의로** 받거나, 바이어 명의라면 계약이 끝날 때 "
                             "**무상 이전**하는 문구를 넣으세요.",
    "br_agent_indemnity": "브라질에 **대리인**을 두면 해지 때 수수료의 1/12 보상이 법으로 정해져 있습니다 — 대리인이 "
                          "아니라 판매점(수입 후 재판매)이면 해당 없습니다.",
}


def _labels(row: dict) -> tuple[str, str]:
    """설명 두 줄의 머리. 독소에 "왜 필요한가"는 어색했습니다(전문가·사용성 점검)."""

    if row["category"] == "toxic":
        return "왜 위험한가", "있으면 생기는 일"
    return "왜 필요한가", "없으면 생기는 일"


def toxic_note(key: str) -> str:
    return TOXIC_NOTE.get(key, "이 조항은 **넣는 것이 아니라 빼는 것**입니다.")


def _picked(keys) -> list[tuple[str, dict]]:
    """고른 조항을 화면 순서로 — 독소(묶음 순서) · 필수 · 이익.

    (소제목, 조항) 짝을 냅니다. 소제목은 독소 묶음이 **바뀌는 자리에만** 있고,
    나머지는 빈 문자열입니다. (2026-10-03)
    """

    picked = [contract_clauses.by_key(key) for key in keys or []]
    picked = [row for row in picked if row]
    if not picked:
        raise ServiceError("내보낼 조항을 골라 주세요.", "VALIDATION_ERROR")
    picked.sort(key=lambda row: (_CATEGORY_ORDER.get(row["category"], 9),
                                 contract_clauses.toxic_group(row["key"])[0]))
    out, last = [], ""
    for row in picked:
        label = contract_clauses.toxic_group(row["key"])[2]
        out.append((label if label and label != last else "", row))
        last = label
    return out


# ── 일반 사용자용 내려받기 (2026-10-03) ────────────────────────────────────────
#
# .md 는 Windows 에서 더블클릭해도 열 프로그램이 없고, 메모장으로 열면 ** · ```
# 가 그대로 보입니다. 받는 사람은 계약서를 쓰는 실무자라 Word·한글에서 열거나,
# 어디서든 열리는 평문이 맞습니다. 조항 설명에 쓰인 표시는 **굵게** 하나뿐입니다.

def _plain(text: str) -> str:
    return _readable(text).replace("**", "")


# 머리 — 「(넣을 문구의 예)」, 「3. PAYMENT」, 번호 없는 「LATE PAYMENT」.
_EN_HEAD = re.compile(r"^\(.*\)$|^(?:\d+(?:\.\d+)*\.?\s+)?[A-Z][A-Z0-9 &/,'()-]*[A-Z)]$")


def _export_lines(text_en: str) -> tuple[str, list[str]]:
    """내려받는 문안 — (안내 한 줄, 붙여 쓸 줄들).

    "(넣을 문구의 예)" 는 붙여 쓸 글이 아니라 안내라서 상자 밖으로 뺍니다. 조 번호
    ("9. ARBITRATION")는 이용자의 계약서 번호와 부딪혀 뗍니다(사용성 점검 2회차).
    """

    lines = _reflow(text_en)
    note = lines[0] if lines and re.fullmatch(r"\(.*\)", lines[0]) else ""
    body = lines[1:] if note else lines
    body = [re.sub(r"^\d+(?:\.\d+)*\.?\s+(?=[A-Z][A-Z &/,'()-]*$)", "", line) for line in body]
    return note, body


def _reflow(text_en: str) -> list[str]:
    """영문 문안을 문단으로. 소스에 80자로 꺾어 둔 줄을 도로 잇습니다.

    꺾인 그대로 계약서에 붙이면 문장 가운데서 줄이 끊깁니다. 머리(「(넣을 문구의
    예)」·「3. PAYMENT」)와 들여 쓴 줄·「- 」 목록은 제 줄로 둡니다.
    """

    out: list[str] = []
    joinable = False
    for raw in text_en.strip().splitlines():
        line = raw.strip()
        if not line:
            joinable = False
            continue
        alone = _EN_HEAD.match(line) or raw[:1].isspace() or line.startswith("- ")
        if joinable and not alone:
            out[-1] += " " + line
        else:
            out.append(line)
        joinable = not _EN_HEAD.match(line)
    return out


def clause_plain(keys) -> str:
    """고른 조항의 문안을 평문(.txt)으로. 기호 없이, 메모장에서 그대로 읽힙니다."""

    rule = "=" * 60
    lines = ["계약서 조항 문안", rule, "", f"※ {DISCLAIMER}", f"※ {BLANK_HELP}", ""]
    for head, row in _picked(keys):
        if head:
            lines += ["", f"■ {head}", ""]
        mark = contract_clauses.CATEGORIES[row["category"]]
        lines += [rule, f"[{mark}] {row['title']}", rule, "",
                  f"{_labels(row)[0]}: {_plain(row['why'])}",
                  f"{_labels(row)[1]}: {_plain(row['risk'])}", ""]
        if row["category"] == "toxic":
            lines += ["★ " + _plain(toxic_note(row["key"])), ""]
            if row["fix"]:
                lines += [f"고치는 법: {_plain(row['fix'])}", ""]
        note, wording = _export_lines(row["text_en"])
        lines += ["[영문 문안]" + (f" {note}" if note else ""), "", *wording, "",
                  "설명: " + _plain(row["text_ko"]), "", ""]
    # 메모장·옛 편집기가 한글을 깨뜨리지 않게 BOM 과 CRLF 로 냅니다.
    return "﻿" + "\r\n".join(lines).rstrip() + "\r\n"


# 받은 문안의 빈칸·한글 문단이 무엇인지 몰랐습니다(사용성 4회차).
BLANK_HELP = "‹ › · < > 안은 고쳐 넣을 칸입니다 — '|' 로 나뉜 것은 하나를 고르고, 나머지는 이 거래의 값으로 채우세요."


def report_plain(result: dict) -> str:
    """판정 결과를 평문(.txt)으로 — 화면의 '판정 결과 받기'. 메모장에서 그대로 읽힙니다."""

    text = as_text(result).replace("**", "")
    text = re.sub(r"^#+\s*", "", text, flags=re.M)
    return "\ufeff" + text.replace("\n", "\r\n").rstrip() + "\r\n"


_RED = "C0392B"
_INK = {"must": "1F4E79", "gain": "1E7B45", "toxic": _RED}


def _runs(paragraph, text: str, *, color: str | None = None, size: float | None = None) -> None:
    """**굵게** 표시를 진짜 굵은 글자로 바꿔 넣습니다."""

    from docx.shared import Pt, RGBColor

    for i, part in enumerate(_readable(text).split("**")):
        if not part:
            continue
        run = paragraph.add_run(part)
        run.bold = bool(i % 2) or None
        if color:
            run.font.color.rgb = RGBColor.from_string(color)
        if size:
            run.font.size = Pt(size)


def _boxed(document, text: str) -> None:
    """영문 문안을 테두리 친 상자(1칸 표)에 넣습니다. 복사해 붙이기 좋게."""

    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt

    note, lines = _export_lines(text)
    if note:
        _runs(document.add_paragraph(), note, color="666666", size=9.5)
    cell = document.add_table(rows=1, cols=1, style="Table Grid").cell(0, 0)
    shade = OxmlElement("w:shd")
    shade.set(qn("w:val"), "clear")
    shade.set(qn("w:fill"), "F4F6F8")
    cell._tc.get_or_add_tcPr().append(shade)
    cell.paragraphs[0].text = ""
    from docx.enum.text import WD_COLOR_INDEX

    for i, line in enumerate(lines):
        paragraph = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
        # <30>·<INCOTERMS> 같은 빈칸은 노랗게 — 그대로 붙여 쓰면 놓칩니다(사용성 점검 2026-10-04).
        for part in re.split(r"(<[^<>]{1,40}>)", line):
            if not part:
                continue
            run = paragraph.add_run(part)
            run.font.name = "Times New Roman"
            run.font.size = Pt(10.5)
            if part.startswith("<") and part.endswith(">"):
                run.font.highlight_color = WD_COLOR_INDEX.YELLOW
    document.add_paragraph()


def clause_docx(keys) -> bytes:
    """고른 조항의 문안을 Word(.docx)로. 한글(HWP)에서도 열립니다."""

    import io

    from docx import Document
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt

    picked = _picked(keys)
    document = Document()

    for section in document.sections:
        section.page_width, section.page_height = Cm(21), Cm(29.7)
        section.left_margin = section.right_margin = Cm(2.2)
        section.top_margin = section.bottom_margin = Cm(2)
    # 한글 글꼴을 따로 정하지 않으면 Word 가 아무 글꼴로 대신합니다.
    normal = document.styles["Normal"]
    normal.font.name = "Malgun Gothic"
    normal.font.size = Pt(10.5)
    normal.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "맑은 고딕")

    title = document.add_paragraph()
    _runs(title, "**계약서 조항 문안**", size=18)
    note = document.add_paragraph()
    _runs(note, f"※ {DISCLAIMER}", color="666666", size=9.5)
    _runs(document.add_paragraph(), f"※ {BLANK_HELP}", color="666666", size=9.5)

    for group, row in picked:
        if group:
            # 독소 묶음 소제목 — 「① 대금을 못 받거나 늦게 받음」
            band = document.add_paragraph()
            band.paragraph_format.space_before = Pt(20)
            band.paragraph_format.keep_with_next = True
            _runs(band, f"**{group}**", color=_RED, size=15)
        category = row["category"]
        mark = contract_clauses.CATEGORIES[category]
        head = document.add_paragraph()
        head.paragraph_format.space_before = Pt(14)
        head.paragraph_format.keep_with_next = True
        _runs(head, f"**[{mark}] {row['title']}**", color=_INK[category], size=13)
        if category == "toxic":
            warn = document.add_paragraph()
            _runs(warn, "■ " + toxic_note(row["key"]), color=_RED)
        for label, field in zip(_labels(row), ("why", "risk")):
            line = document.add_paragraph()
            _runs(line, f"**{label}:** {row[field]}")
        if category == "toxic" and row["fix"]:
            line = document.add_paragraph()
            _runs(line, f"**고치는 법:** {row['fix']}")
        _boxed(document, row["text_en"])
        _runs(document.add_paragraph(), "설명: " + row["text_ko"])

    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def _basis_line(result: dict) -> str:
    """판정 기준 한 줄 — "판정 기준: CIF(계약서에서 읽음) · 도착국 CN"."""

    parts = []
    terms = result.get("incoterms") or ""
    if terms:
        parts.append(f"{terms}(계약서에서 읽음)" if result.get("incoterms_from_doc") else terms)
    if result.get("country"):
        parts.append(f"도착국 {result['country']}")
    line = f"판정 기준: {' · '.join(parts)}" if parts else ""
    if result.get("incoterms_mismatch"):
        line += (f" — ⚠️ 고르신 인코텀즈는 {terms} 인데 계약서에는 **{result['incoterms_mismatch']}** 가 "
                 "적혀 있습니다. 맞는 쪽으로 다시 판정하세요.")
    return line


def as_text(result: dict) -> str:
    """판정을 사람이 읽는 글로. 무역 상담 답변에 그대로 씁니다."""

    lines = ["## 계약서 조항 점검", ""]
    if result.get("side_unknown"):
        lines += ["⚠️ 갑/을(Party A/B) 중 **누가 우리(매도인)인지 못 정했습니다.** 판정의 방향이 뒤집혔거나 "
                  "위험한 조항을 못 짚었을 수 있습니다. 당사자 정의에 '매도인'·'Seller' 표시가 있는지 확인하세요.", ""]
    if result.get("truncated"):
        lines += [f"⚠️ 계약서가 길어 **앞 {MAX_TEXT:,}자만** 봤습니다. 뒷부분은 따로 나눠 "
                  "올려 주세요.", ""]
    basis = _basis_line(result)
    if basis:
        lines += [basis, ""]
    if result.get("blanks"):
        lines += [f"⚠️ 채우지 않은 **빈칸이 {result['blanks']}곳** 있습니다(____ · [●] · ‹…› · TBD). 빈칸이 든 조항은 "
                  "'적혀 있으나 부족'으로 봤습니다.", ""]
    side = result.get("our_side")
    if side:
        # 역할 이름만 정한 계약서(Supplier/Company)는 이름이 없습니다 — "Supplier — " 로
        # 빈 자리가 나왔습니다(3회차). 화면(contract_clauses.js who())과 같은 꼴로.
        def who(label: str, name: str) -> str:
            return f"**{label} — {name}**" if name else f"**{label}**"
        # "…을 **을 — …**" 이 '을을'로 읽혀 화면처럼 이름표 꼴로 씁니다(사용성 3회차).
        lines += [f"우리 쪽(매도인·수출자): {who(side['label'], side['name'])} · "
                  f"상대(매수인): {who(side['other_label'], side['other_name'])} — "
                  "반대라면 판정도 반대가 됩니다.", ""]
    if result["toxic"]:
        lines += [f"### 🔴 지우거나 고쳐야 할 조항 {len(result['toxic'])}개", ""]
        last = None
        for row in result["toxic"]:
            # 화면·내려받기와 같은 묶음 소제목 (① 대금 … ⑧ 제재). (2026-10-03)
            if row.get("group_label") and row["group_label"] != last:
                lines += ([""] if last else []) + [f"**{row['group_label']}**"]
                last = row["group_label"]
            lines.append(f"- **{row['title']}** — {row['risk']}")
            if row.get("same_as"):
                lines.append(f"  - 근거: 위 ‘{row['same_as']}’ 조항과 같은 문장")
            elif row.get("evidence"):
                lines.append(f"  - 근거: “{row['evidence']}”")
            elif row.get("reason"):
                # 문장이 아니라 거래 조건(DDP + 도착국)으로 짚은 것 — 왜 짚었는지 적습니다.
                lines.append(f"  - 까닭: {row['reason']}")
            if row["fix"]:
                lines.append(f"  - 고치는 법: {row['fix']}")
        lines.append("")
    if result.get("weak"):
        lines += [f"### 🟡 적혀 있으나 제 구실을 못 하는 조항 {len(result['weak'])}개", ""]
        for row in result["weak"]:
            lines.append(f"- **{row['title']}** — {row['reason']}")
            if row.get("evidence"):
                lines.append(f"  - 근거: “{row['evidence']}”")
        lines.append("")
    if result["missing"]:
        lines += [f"### 🟠 빠진 필수조항 {len(result['missing'])}개", ""]
        for row in result["missing"]:
            lines.append(f"- **{row['title']}** — {row['why']}")
            if row.get("maybe"):
                lines.append(f"  - 규칙은 못 찾았지만 이 문장일 수 있습니다: “{row['maybe']}”")
        lines.append("")
    if result.get("check"):
        lines += [f"### ⚪ 규칙이 판정하지 못한 조항 {len(result['check'])}개 (직접 확인)", ""]
        for item in result["check"]:
            lines.append(f"- **{item['title']}** 조항으로 보입니다 — {item.get('label', '확인 필요')}")
            if item.get("why"):
                lines.append(f"  - 수출자 입장: {item['why']}")
            lines.append(f"  - 문장: “{item['sentence']}”")
        lines.append("")
    if result["gain"]:
        lines += [f"### 🔵 챙기면 이로운 조항 {len(result['gain'])}개", ""]
        for row in result["gain"]:
            lines.append(f"- **{row['title']}** — {row['risk']}")
        lines.append("")
    if result.get("watch_country"):
        lines += [f"### 🌍 도착국({result.get('country', '')})에서 흔한 조항 — 계약서에서 찾지 못함", ""]
        for row in result["watch_country"]:
            note = WATCH_NOTE.get(row["key"], "협상 중에 들어오면 지우거나 고치세요.")
            lines.append(f"- **{row['title']}** — {note}")
        lines.append("")
    if not (result["toxic"] or result["missing"] or result.get("weak")):
        # ⚪ 직접 확인·🌍 도착국 주의가 있는데 "독소조항은 보이지 않습니다"로 끝냈습니다(사용성 4회차).
        rest = " 위의 ⚪·🌍 항목은 직접 확인하세요." if (result.get("check") or result.get("watch_country")) else ""
        lines += ["필수조항은 다 보이고, 짚은 독소조항은 없습니다." + rest +
                  " 다만 **글자를 찾은 결과**일 뿐이라 내용까지 맞다는 뜻은 아닙니다.", ""]
    lines += [f"※ {result['note']}"]
    return "\n".join(lines)

# 계약서인지 가리는 표지.
#
# 왜 필요한가
#   상담 창에 계약서를 통째로 붙여 넣는 일이 많습니다. 그걸 그냥 AI에게
#   넘기면 "요약해 드릴게요" 같은 답이 돌아옵니다. 정작 물어보고 싶은 것은
#   **빠진 조항과 위험한 조항**입니다. 계약서로 보이면 그쪽으로 답합니다.
#
# 두 가지를 함께 봅니다. 하나만 보면 헛짚습니다.
#   - 계약서라고 적혀 있는가 (제목·머리글)
#   - 조항이 실제로 두 가지 이상 보이는가
CONTRACT_TITLES = (
    "sales contract", "purchase contract", "supply agreement", "distribution agreement",
    "sales agreement", "purchase order terms", "terms and conditions of sale",
    "매매계약", "수출계약", "공급계약", "판매계약", "대리점계약", "총판계약", "계약서",
)
# 스스로 **계약서가 아니라고** 적어 둔 서류. 그 말을 믿습니다.
#
# 오퍼시트·견적서·송장은 가격조건과 결제·선적·보험을 다 적습니다. 그래서
# 조항 개수만 보면 전부 계약서로 걸립니다. 실제로 오퍼시트 세 장이 모두
# 계약서로 판정되어, 서류 칸이 빈 채로 "13가지가 누락되었습니다"가 떴습니다.
# (2026-09-28)
TERMS_TITLES = ("purchase order terms", "terms and conditions of purchase", "terms and conditions of sale",
                "general terms and conditions", "구매약관", "구매 약관", "거래약관", "일반거래조건")
NOT_CONTRACT_TITLES = (
    "offer sheet", "firm offer", "quotation", "proforma invoice",
    "commercial invoice", "packing list", "bill of lading", "air waybill",
    "certificate of origin", "purchase order",
    "오퍼시트", "견적서", "상업송장", "포장명세서", "선하증권", "원산지증명서",
    "주문서", "발주서",
)

# **계약서다운** 조항. 제목이 없을 때는 이것들로 셉니다.
#
# incoterms · payment · shipment · insurance · packing · inspection 은
# 장사 서류면 다 있으므로 여기에 넣지 않습니다. 넣으면 오퍼시트가 계약서가
# 됩니다 — 실제로 그랬습니다.
CONTRACT_ONLY_CLAUSES = frozenset({
    # 필수·이익 조항 가운데 **계약서에만** 나오는 것
    "governing_law", "arbitration", "force_majeure", "title",
    "liability_cap", "late_interest", "ip", "cisg_silent", "agency_protection",
    # 독소조항. 이런 문구는 오퍼시트에 안 적습니다.
    "evergreen", "foreign_forum", "full_return", "mfn_price", "open_warranty",
    "payment_on_resale", "term_conflict", "termination_at_will",
    "uncapped_ld", "unlimited_damages", "us_jury_punitive",
    "buyer_set_off", "ip_assignment", "china_domestic_arb", "agency_law_eu",
})

# 여기에 **넣지 않은** 것 — 장사 서류면 다 있습니다.
#   incoterms · payment · shipment · insurance · inspection · goods
#   min_order · price_adjust · export_licence
# 실제로 오퍼시트 세 장에서 걸린 것이 incoterms·insurance·payment·shipment
# 넷이었고, 그것만으로 계약서 판정이 나 서류 칸이 통째로 비었습니다.

# 이만큼은 돼야 계약서 한 장으로 봅니다. 짧은 인용은 질문이지 계약서가 아닙니다.
# 제목을 찾는 범위. 무역서류는 **첫 몇 줄에** 무엇인지 적습니다.
#
# 글자 수로 자르면 안 됩니다. 짧은 계약서는 600자 안에 이미 "commercial
# invoice, packing list" 같은 본문이 들어옵니다. 그 언급에 걸려 진짜
# 계약서를 놓쳤습니다. 줄로 셉니다. (2026-09-28)
TITLE_LOOKUP_LINES = 3


def _title_area(text: str) -> str:
    """서류가 스스로 무엇이라고 적어 둔 자리. 빈 줄을 뺀 첫 몇 줄입니다."""

    rows = [row.strip() for row in str(text or "").splitlines() if row.strip()]
    return " ".join(rows[:TITLE_LOOKUP_LINES]).lower()

CONTRACT_MIN_CHARS = 400
CONTRACT_MIN_CLAUSES = 2

# 제목이 없을 때 필요한 **계약서다운** 조항 수.
#
# 조항 종류를 좁혔으니 문턱도 다시 잡습니다. 예전에는 아무 조항이나 넷이었고,
# 그래서 오퍼시트(incoterms·insurance·payment·shipment)가 전부 걸렸습니다.
# 지금은 준거법·중재·불가항력 같은 것만 셉니다. 오퍼시트에는 이런 조항이
# **하나도 없습니다.** 셋이면 계약서로 봐도 됩니다. (2026-09-28)
CONTRACT_MIN_ONLY_CLAUSES = 3


def looks_like_contract(text: str) -> bool:
    """이 글이 계약서인가. 확실하지 않으면 False입니다(평소대로 상담으로 답합니다).

    잘못 보면 두 가지가 한꺼번에 나빠집니다.
      계약서를 놓치면  조항을 못 짚어 줍니다 (아쉽지만 상담은 됩니다)
      계약서로 잘못 보면 **서류 칸이 통째로 비고** "13가지가 누락되었습니다"가
                      뜹니다. 멀쩡히 읽히는 서류인데도요.
    뒤쪽이 더 나쁩니다. 그래서 확실할 때만 계약서로 봅니다.
    """

    body = str(text or "")
    if len(body) < CONTRACT_MIN_CHARS:
        return False
    lowered = body.lower()
    # **제목은 첫 몇 줄에서만 찾습니다.**
    #
    # 본문까지 뒤지면 안 됩니다. 계약서는 "each party shall provide the
    # commercial invoice, packing list, and transport documents" 처럼 다른
    # 서류를 본문에서 언급합니다. 그것 때문에 진짜 계약서를 놓쳤습니다.
    # (2026-09-28 — 본문 2,038번째 글자의 "commercial invoice" 에 걸렸습니다)
    head = _title_area(body)
    # **약관**이라고 적힌 발주서는 계약서입니다 — "PURCHASE ORDER TERMS AND CONDITIONS" 가
    # 'purchase order' 에 걸려 서류로 빠졌습니다(사용성 점검 2회차). 실무에서는 바이어의
    # 발주서 약관이 곧 계약 조건입니다.
    terms = any(word in head for word in TERMS_TITLES)
    # 스스로 오퍼시트·송장이라고 적어 둔 것은 계약서가 아닙니다.
    if not terms and any(word in head for word in NOT_CONTRACT_TITLES):
        return False
    if terms:
        return len(contract_clauses.find_in(body)) >= CONTRACT_MIN_CLAUSES
    if any(word in head for word in CONTRACT_TITLES):
        return len(contract_clauses.find_in(body)) >= CONTRACT_MIN_CLAUSES
    # 제목이 없으면 **계약서다운 조항**만 셉니다.
    # 가격조건·결제·선적은 장사 서류면 다 있어 세지 않습니다.
    found = set(contract_clauses.find_in(body)) & CONTRACT_ONLY_CLAUSES
    return len(found) >= CONTRACT_MIN_ONLY_CLAUSES
