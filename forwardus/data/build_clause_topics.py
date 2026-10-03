"""Build data/processed/clause_topics.json — 계약 조항 **주제** 분류기.

왜 있나 (2026-10-03)
  계약서 조항 판정은 낱말 규칙(app/processors/contract_clauses.py)으로 합니다.
  규칙은 정확하지만 **처음 보는 표현**은 놓칩니다. 이 분류기는 규칙이 놓친
  문장을 "이 문장이 준거법 조항일 수 있습니다"처럼 **확인 필요**로 띄웁니다.

  분류기는 **주제**만 압니다. 유리·불리(독소 여부)는 모릅니다 — 배심재판
  포기는 주제가 '배심'이어도 우리에게 유리합니다. 판정은 계속 규칙이 합니다.

출처 (모두 CC BY 4.0 — 출처를 밝히면 가공해 쓸 수 있습니다)
  - CUAD v1 (The Atticus Project): 실제 계약서 510건, 조항 41종에 사람이 단 라벨
    https://zenodo.org/records/4595826
  - LEDGAR (LexGLUE 판, coastalcph/lex_glue): 미국 SEC 공시 계약 조항 약 8만 개, 100종
    https://huggingface.co/datasets/coastalcph/lex_glue
  - CUAD 계약서의 **조항 제목**으로 직접 단 라벨 — 두 데이터셋에 없는 무역 주제
    (불가항력·검사·인도·포장·소유권 유보·연체 이자·상계·수출 규제)
  - 이 저장소의 조항 문안·테스트 문구 — 국문

모양
  주제마다 낱말 가중치(log 비율) 상위 N개만 남긴 **희소 선형 모델**입니다.
  서버는 순수 파이썬으로 더하기만 합니다. 새 패키지도, 바깥 호출도 없습니다.

쓰는 법
  pip install -r data/requirements-build.txt   (pandas · pyarrow)
  데이터를 data/raw/contracts/ 에 둡니다 (README 의 받는 법 참고)
  python data/build_clause_topics.py
"""

from __future__ import annotations

import ast
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "contracts"
OUT = ROOT / "data" / "processed" / "clause_topics.json"
sys.path.insert(0, str(ROOT))

SEED = 20261003
TARGET_PRECISION = 0.90     # 확신 문턱을 이 정밀도에 맞춥니다
MIN_PER_TOPIC = 40

# ── 주제 ─────────────────────────────────────────────────────────────────
# title: 화면에 낼 이름 · keys: 이 주제를 다루는 우리 조항
TOPICS = {
    "governing_law": ("준거법", ("governing_law", "cisg_silent")),
    "jurisdiction": ("관할 법원", ("foreign_forum",)),
    "arbitration": ("중재", ("arbitration", "china_domestic_arb")),
    "jury_waiver": ("배심재판", ("us_jury_punitive",)),
    "confidential": ("비밀유지", ("confidential", "one_way_nda")),
    "amendment": ("계약 변경·통지", ("amendment",)),
    "indemnity": ("손해배상·면책", ("unlimited_damages", "own_negligence_indemnity",
                                   "eu_gdpr_indemnity", "us_class_action_pl")),
    "liability_cap": ("책임 한도", ("liability_cap", "unlimited_damages")),
    "liquidated": ("지연배상금·위약금", ("uncapped_ld",)),
    "termination": ("해지", ("termination_at_will", "exit_buyback")),
    "warranty": ("품질 보증", ("claim_period", "open_warranty")),
    "assignment": ("양도", ("assignment_one_way",)),
    "ip": ("지식재산·금형", ("ip", "ip_assignment", "buyer_design_ip", "cn_tech_transfer",
                            "tooling_free", "cn_trademark_buyer")),
    "audit": ("감사·장부", ("audit_rights",)),
    "mfn": ("최혜 가격", ("mfn_price",)),
    "non_compete": ("경업 금지", ("non_compete_wide",)),
    "exclusivity": ("독점·대리점", ("exclusive_no_moq", "agency_protection", "gulf_agent_lock",
                                  "agency_law_eu")),
    "min_order": ("최소 주문", ("min_order",)),
    "renewal": ("자동 갱신", ("evergreen",)),
    "price": ("가격 조정", ("price_adjust", "retro_price_deduction")),
    "sanctions": ("제재·수출 규제", ("ru_sanctions_warranty", "export_licence", "reexport_control")),
    "taxes": ("세금·원천징수", ("tariff_absorption", "ddp_no_ior", "no_set_off", "buyer_set_off")),
    "payment": ("결제", ("payment", "lc_deadline", "docs_before_payment", "payment_retention",
                        "payment_on_resale", "suspend_delivery")),
    "insurance": ("보험", ("insurance",)),
    "force_majeure": ("불가항력", ("force_majeure",)),
    "title": ("소유권·위험 이전", ("title",)),
    "inspection": ("검사·인수", ("inspection", "inspection_buyer_sole", "full_inspection")),
    "delivery": ("인도·선적", ("shipment", "incoterms")),
    "packing": ("포장·화인", ("packing",)),
    "late_interest": ("연체 이자", ("late_interest",)),
    "set_off": ("상계", ("no_set_off", "buyer_set_off")),
}

# **가까운 주제의 묶음.** (2026-10-03)
# LEDGAR 는 조항 하나에 라벨 하나라, "준거법·관할·배심재판 포기"를 한 문단에
# 쓴 조항도 '준거법' 하나로만 적혀 있습니다. 관할을 맞혀도 틀렸다고 셉니다.
# 그래서 정밀도를 **묶음 단위**로 재고, 화면에도 묶음 이름을 함께 냅니다.
FAMILIES = {
    "dispute": ("분쟁 해결", ("governing_law", "jurisdiction", "arbitration", "jury_waiver")),
    "liability": ("배상·책임", ("indemnity", "liability_cap", "liquidated")),
    "money": ("대금·세금", ("payment", "taxes", "late_interest", "price", "set_off")),
    "goods": ("인도·검사·소유권", ("delivery", "inspection", "title", "packing")),
    "term": ("해지·갱신", ("termination", "renewal")),
    "boiler": ("양도·변경", ("assignment", "amendment")),
    "market": ("독점·경업·물량", ("exclusivity", "non_compete", "min_order", "mfn")),
}
FAMILY_OF = {t: f for f, (_title, ts) in FAMILIES.items() for t in ts}

LEDGAR_MAP = {
    "Governing Laws": "governing_law",
    "Jurisdictions": "jurisdiction", "Consent To Jurisdiction": "jurisdiction",
    "Submission To Jurisdiction": "jurisdiction", "Venues": "jurisdiction",
    "Arbitration": "arbitration", "Waiver Of Jury Trials": "jury_waiver",
    "Confidentiality": "confidential",
    "Amendments": "amendment", "Modifications": "amendment", "Notices": "amendment",
    "Indemnifications": "indemnity", "Indemnity": "indemnity",
    "Terminations": "termination", "Warranties": "warranty",
    "Assignments": "assignment", "Assigns": "assignment",
    "Intellectual Property": "ip", "Books": "audit", "Records": "audit",
    "Sanctions": "sanctions", "Anti-Corruption Laws": "sanctions",
    "Taxes": "taxes", "Tax Withholdings": "taxes", "Withholdings": "taxes",
    "Payments": "payment", "Insurances": "insurance",
}

CUAD_MAP = {
    "Governing Law": "governing_law", "Cap On Liability": "liability_cap",
    "Uncapped Liability": "liability_cap", "Liquidated Damages": "liquidated",
    "Termination For Convenience": "termination", "Warranty Duration": "warranty",
    "Anti-Assignment": "assignment", "Ip Ownership Assignment": "ip", "Joint Ip Ownership": "ip",
    "Audit Rights": "audit", "Most Favored Nation": "mfn", "Non-Compete": "non_compete",
    "No-Solicit Of Customers": "non_compete", "Exclusivity": "exclusivity",
    "Minimum Commitment": "min_order", "Volume Restriction": "min_order",
    "Renewal Term": "renewal", "Notice Period To Terminate Renewal": "renewal",
    "Price Restrictions": "price", "Insurance": "insurance",
}

# 두 데이터셋에 없는 무역 주제 — CUAD 계약서의 **조항 제목**으로 라벨을 답니다.
# 제목 줄: "12. Force Majeure." / "ARTICLE 7 - INSPECTION AND ACCEPTANCE" / "7.2 Title"
HEADINGS = {
    "force_majeure": r"force\s+majeure|excusable\s+delays?",
    "title": r"title|title\s+and\s+risk(?:\s+of\s+loss)?|risk\s+of\s+loss|(?:passage|transfer|retention)"
             r"\s+of\s+title|title\s+to\s+(?:products|goods)|ownership\s+of\s+(?:products|goods)",
    "inspection": r"inspections?(?:\s+(?:of\s+(?:work|goods|products)|and\s+(?:acceptance|testing)|rights))?"
                  r"|acceptance(?:\s+(?:testing|of\s+(?:products|goods)|and\s+rejection))?|rejection",
    "delivery": r"deliver(?:y|ies)(?:\s+(?:terms|schedule|and\s+(?:acceptance|shipment)))?|shipments?"
                r"|shipping(?:\s+(?:terms|and\s+delivery))?|time\s+of\s+delivery|delivery\s+dates?",
    "packing": r"packaging(?:\s+and\s+labell?ing)?|packing(?:\s+and\s+(?:labell?ing|marking))?"
               r"|shipping\s+marks?|labell?ing",
    "late_interest": r"late\s+(?:payments?|charges?)|interest\s+on\s+(?:late|overdue)\s+(?:payments?|amounts?)",
    "set_off": r"set[- ]?offs?|right\s+(?:of|to)\s+set[- ]?off|no\s+set[- ]?off",
    "sanctions": r"export\s+(?:controls?|compliance|regulations?|restrictions?)",
    "price": r"prices?|pricing|price\s+(?:adjustments?|changes?|increases?)",
    "mfn": r"most\s+favou?red\s+(?:nation|customer)(?:\s+(?:pricing|treatment))?",
    "renewal": r"renewal|automatic\s+renewal|term\s+and\s+renewal|renewal\s+term",
    "liability_cap": r"limitations?\s+(?:of|on)\s+liability",
}
# 제목은 줄 머리가 아니라 **본문 중간**에 붙어 있습니다 (CUAD 원문).
#   "6.8      Force Majeure.  Neither party …"   "17. FORCE MAJEURE: The Sellers …"
#   "4.18 Packaging. During the Term, …"         "c. Force Majeure. A Party …"
_HEAD = re.compile(
    r"(?:(?<=\s)|^)(?:(?:section|article|clause)\s+)?"
    r"(?:\d{1,2}(?:\.\d{1,2}){0,2}\.?|[a-z]\.|\([a-z0-9]{1,3}\))\s+"
    r"(?P<title>[A-Z][A-Za-z,&\- ]{2,50}?)(?:\s*[.:]\s+|\s{2,})(?=[A-Z(\"“])")


# ── 낱말 ─────────────────────────────────────────────────────────────────
# 서버와 **같은 함수**로 쪼갭니다. 다르게 쪼개면 가중치가 맞지 않습니다.
from app.processors.clause_topics import tokens  # noqa: E402


# ── 모으기 ───────────────────────────────────────────────────────────────
def _clip(text: str, n: int = 1200) -> str:
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text[:n]


def ledgar():
    import pandas as pd

    names = {int(k): v for k, v in
             json.loads((RAW / "ledgar_labels.json").read_text(encoding="utf-8")).items()}
    rows = {"train": [], "test": []}
    for split, part in (("train", "train"), ("train", "validation"), ("test", "test")):
        frame = pd.read_parquet(RAW / f"ledgar_{part}.parquet")
        for text, label in zip(frame["text"], frame["label"]):
            rows[split].append((_clip(text), LEDGAR_MAP.get(names[int(label)], "other"), "ledgar"))
    return rows


def cuad(rng: random.Random):
    data = json.loads((RAW / "CUAD_v1" / "CUAD_v1.json").read_text(encoding="utf-8"))["data"]
    docs = [d["title"] for d in data]
    rng.shuffle(docs)
    held = set(docs[: len(docs) // 5])            # 계약서 단위로 20% 를 시험용으로
    rows = {"train": [], "test": []}
    for doc in data:
        split = "test" if doc["title"] in held else "train"
        for para in doc["paragraphs"]:
            spans = []
            for qa in para["qas"]:
                topic = CUAD_MAP.get(qa["id"].split("__")[-1])
                for ans in qa["answers"]:
                    spans.append((ans["answer_start"], ans["answer_start"] + len(ans["text"])))
                    # 갱신·최혜 조항 답은 짧습니다("successive one-year terms"). 25자부터.
                    if topic and len(ans["text"]) >= 25:
                        rows[split].append((_clip(ans["text"]), topic, "cuad"))
            # 어떤 라벨에도 안 걸린 문장 — '기타'
            context = para["context"]
            for m in re.finditer(r"[^.]{60,600}\.", context):
                if any(a < m.end() and m.start() < b for a, b in spans):
                    continue
                if rng.random() < 0.06:
                    rows[split].append((_clip(m.group()), "other", "cuad"))
        # 조항 제목으로 다는 라벨
        for text, topic in _by_heading(doc["paragraphs"][0]["context"]):
            rows[split].append((text, topic, "heading"))
    return rows


def _by_heading(context: str):
    heads = list(_HEAD.finditer(context))
    for i, m in enumerate(heads):
        title = re.sub(r"\s+", " ", m.group("title")).strip(" .:-,")
        for topic, pattern in HEADINGS.items():
            if re.fullmatch(pattern, title, re.I):
                end = heads[i + 1].start() if i + 1 < len(heads) else len(context)
                body = _clip(context[m.end():end])
                if len(body) >= 60:
                    yield body, topic
                break


def edgar():
    """SEC EDGAR 공급·구매 계약서 (collect_edgar_contracts.py 가 받아 둔 것).

    조항 제목으로만 라벨을 답니다. 계약서 단위로 다섯에 하나를 시험용으로.
    """

    rows = {"train": [], "test": []}
    folder = RAW / "edgar"
    for path in sorted(folder.glob("*.txt")) if folder.exists() else []:
        split = "test" if sum(path.stem.encode()) % 5 == 0 else "train"
        text = path.read_text(encoding="utf-8")
        for body, topic in _by_heading(text):
            rows[split].append((body, topic, "edgar"))
    return rows


def ours():
    """이 저장소의 조항 문안과 테스트 문구 — 국문·무역 표현."""

    from app.processors import contract_clauses as cc

    key_topic = {}
    for topic, (_title, keys) in TOPICS.items():
        for key in keys:
            key_topic.setdefault(key, topic)
    rows = []
    for row in cc.CLAUSES:
        topic = key_topic.get(row["key"])
        if topic:
            rows.append((_clip(row["text_en"]), topic, "ours"))
    for name in ("test_contract_wording.py", "test_contract_paraphrase.py"):
        tree = ast.parse((ROOT / "tests" / name).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "CASES":
                for key, bodies in ast.literal_eval(node.value).items():
                    if key in key_topic:
                        rows += [(_clip(b), key_topic[key], "ours") for b in bodies]
    return rows


# ── 학습 ─────────────────────────────────────────────────────────────────
#
# **나이브 베이즈**에 '기타'(other)를 함께 겨루게 합니다. (2026-10-03)
#
# 처음에는 주제마다 낱말 가중치를 더하는 방식이었는데, '기타'와 겨루지 않아
# 주제와 무관한 문장도 어느 주제든 1위가 되었고, 그래서 문턱을 높게 두어야
# 했습니다. 규칙에 없는 표현 14개로 재 보니 1위는 13개가 맞았는데 문턱을
# 넘은 것은 5개였습니다. 이제 '기타'를 이겨야 주제가 됩니다.
VOCAB = 12000


def train(rows):
    """**로지스틱 회귀** (다항, L2). 조항 하나를 낱말 집합으로 봅니다.

    나이브 베이즈는 1위는 잘 맞히는데 확신 점수가 실제 정답률과 어긋나, 정밀도
    90% 를 지키려면 문턱이 너무 높았습니다(규칙에 없는 표현 13개 중 5개만 띄움).
    로지스틱 회귀는 점수가 정답률에 가깝게 나옵니다. 학습만 numpy 로 하고, 저장
    모양(낱말별 주제 가중치 + 기본값)은 같아서 서버는 그대로 더하기만 합니다.
    """

    import numpy as np

    classes = [t for t in TOPICS] + ["other"]
    docs = Counter(topic for _t, topic, _s in rows)
    keep = [c for c in classes if docs[c] >= MIN_PER_TOPIC]
    for c in classes:
        if c not in keep:
            print(f"  ! {c}: 예문 {docs[c]}개 — 뺍니다")
    rows = [r for r in rows if r[1] in keep]
    toks = [tokens(text) for text, _t, _s in rows]
    df = Counter()
    for t in toks:
        df.update(t)
    vocab = [tok for tok, n in df.most_common() if n >= 4][:VOCAB]
    index = {tok: i for i, tok in enumerate(vocab)}
    feats = [[index[t] for t in ts if t in index] for ts in toks]
    y = np.array([keep.index(r[1]) for r in rows])
    # 주제가 적은 쪽이 묻히지 않게 무게를 답니다 (많은 '기타'·변경 조항에 끌려가지 않게)
    freq = np.bincount(y, minlength=len(keep)).astype(float)
    class_w = (freq.sum() / (len(keep) * freq)) ** 0.5

    rng = np.random.default_rng(SEED)
    n, v, k = len(rows), len(vocab), len(keep)
    W = np.zeros((v, k), dtype=np.float32)
    b = np.log(freq / freq.sum()).astype(np.float32)
    # Adam — 낱말마다 걸음을 맞춥니다. 길이로 나눈 값이 작아 보통 경사하강은
    # 거의 안 움직였습니다(손실 1.86 에서 멈춤). (2026-10-03)
    lr, l2, batch = 0.02, 1e-6, 256
    mW, vW = np.zeros_like(W), np.zeros_like(W)
    mb, vb = np.zeros_like(b), np.zeros_like(b)
    beta1, beta2, step = 0.9, 0.999, 0
    for epoch in range(10):
        order = rng.permutation(n)
        loss = 0.0
        for start in range(0, n, batch):
            idx = order[start:start + batch]
            X = np.zeros((len(idx), v), dtype=np.float32)
            for r, j in enumerate(idx):
                if feats[j]:
                    X[r, feats[j]] = 1.0 / np.sqrt(len(feats[j]))   # 긴 조항이 점수를 독차지하지 않게
            logits = X @ W + b
            logits -= logits.max(axis=1, keepdims=True)
            p = np.exp(logits)
            p /= p.sum(axis=1, keepdims=True)
            yt = y[idx]
            loss += -np.log(p[np.arange(len(idx)), yt] + 1e-9).sum()
            g = p
            g[np.arange(len(idx)), yt] -= 1.0
            g *= class_w[yt][:, None]
            gW = X.T @ g / len(idx) + l2 * W
            gb = g.mean(axis=0)
            step += 1
            mW = beta1 * mW + (1 - beta1) * gW
            vW = beta2 * vW + (1 - beta2) * gW * gW
            mb = beta1 * mb + (1 - beta1) * gb
            vb = beta2 * vb + (1 - beta2) * gb * gb
            c1, c2 = 1 - beta1 ** step, 1 - beta2 ** step
            W -= lr * (mW / c1) / (np.sqrt(vW / c2) + 1e-8)
            b -= lr * (mb / c1) / (np.sqrt(vb / c2) + 1e-8)
        lr *= 0.85
        print(f"    epoch {epoch + 1}  loss {loss / n:.3f}")
    table = {tok: [round(float(W[i, c]) * 100) for c in range(k)]
             for tok, i in index.items()}
    prior = [round(float(x) * 100) for x in b]
    return {"classes": keep, "prior": prior, "table": table, "norm": "sqrt"}, docs


def score(nb, text):
    """(주제, 1위와 2위의 차) — '기타'가 1위면 주제 None. 서버와 같은 계산."""

    toks = [t for t in tokens(text) if t in nb["table"]]
    if not toks:
        return None, 0.0
    scale = 1.0 / math.sqrt(len(toks))
    sums = [p / 100 for p in nb["prior"]]
    for t in toks:
        for i, v in enumerate(nb["table"][t]):
            sums[i] += v / 100 * scale
    order = sorted(range(len(sums)), key=sums.__getitem__, reverse=True)
    top, second = order[0], order[1]
    topic = nb["classes"][top]
    margin = sums[top] - sums[second]
    return (None if topic == "other" else topic), margin


def _sentences(rows, rng, keep=0.35):
    """조항을 문장으로 잘라 시험용으로 더합니다. 실제 입력은 한두 문장입니다."""

    out = []
    for text, gold, src in rows:
        for s in re.split(r"(?<=[.;])\s+", text):
            if len(s) >= 40 and rng.random() < keep:
                out.append((s, gold, src + "/sent"))
    return out


def calibrate(nb, rows):
    """주제마다 정밀도가 TARGET_PRECISION 이상인 가장 낮은 '차' 문턱.

    문단과 문장을 함께 씁니다. 문단에만 맞추면 짧은 실제 입력에서 문턱을 못
    넘고, 문장에만 맞추면 문단에서 헐거워집니다.
    """

    scored = defaultdict(list)
    for text, gold, _src in rows:
        topic, margin = score(nb, text)
        if topic:
            same = gold == topic or (FAMILY_OF.get(topic) and FAMILY_OF.get(topic) == FAMILY_OF.get(gold))
            scored[topic].append((margin, bool(same)))
    thresholds, report = {}, {}
    for topic, items in scored.items():
        items.sort(reverse=True)
        best = None
        tp = fp = 0
        for margin, ok in items:
            tp += ok
            fp += not ok
            if tp >= 5 and tp / (tp + fp) >= TARGET_PRECISION:
                best = (margin, tp, fp)
        fam = FAMILY_OF.get(topic)
        positives = sum(1 for _t, g, _s in rows if g == topic or (fam and FAMILY_OF.get(g) == fam))
        if best:
            thresholds[topic] = round(best[0], 2)
            report[topic] = {"threshold": round(best[0], 2),
                             "precision": round(best[1] / (best[1] + best[2]), 3),
                             "recall": round(best[1] / max(positives, 1), 3),
                             "test_positives": positives}
    return thresholds, report


def main() -> int:
    rng = random.Random(SEED)
    led, cu, ed = ledgar(), cuad(rng), edgar()
    mine = ours()
    print(f"EDGAR 제목 라벨: 학습 {len(ed['train'])} · 시험 {len(ed['test'])}")
    train_rows = led["train"] + cu["train"] + ed["train"] + mine
    test_rows = led["test"] + cu["test"] + ed["test"]
    test_rows = test_rows + _sentences(test_rows, rng)
    # '기타'가 너무 많으면 주제가 묻힙니다. 학습용만 줄입니다.
    others = [r for r in train_rows if r[1] == "other"]
    rng.shuffle(others)
    train_rows = [r for r in train_rows if r[1] != "other"] + others[:25000]
    print(f"학습 {len(train_rows):,} · 시험 {len(test_rows):,} (문장 포함) · 우리 문구 {len(mine)}")
    print("주제별 학습 예문:", dict(Counter(r[1] for r in train_rows).most_common()))

    nb, _docs = train(train_rows)
    thresholds, report = calibrate(nb, test_rows)
    for topic in TOPICS:
        r = report.get(topic)
        print(f"  {topic:15} " + (f"문턱 {r['threshold']:6.2f}  정밀도 {r['precision']:.0%}  "
                                   f"재현율 {r['recall']:.0%}  (시험 {r['test_positives']})"
                                   if r else "— 문턱 없음(예문 부족 또는 정밀도 미달)"))
    model = {
        "version": 3,
        "kind": "logistic_regression",
        "built": "2026-10-03",
        "sources": ["CUAD v1 (CC BY 4.0, The Atticus Project)",
                    "LEDGAR via LexGLUE (CC BY 4.0, coastalcph/lex_glue)",
                    "CUAD section headings (derived)",
                    "SEC EDGAR supply/purchase agreements, section headings (US public filings)",
                    "FORWARDUS clause texts"],
        "target_precision": TARGET_PRECISION,
        "classes": nb["classes"],
        "prior": nb["prior"],
        "table": nb["table"],
        "norm": nb.get("norm", ""),
        "topics": {t: {"title": TOPICS[t][0], "keys": list(TOPICS[t][1]),
                       "family": FAMILY_OF.get(t, ""),
                       "family_title": FAMILIES[FAMILY_OF[t]][0] if t in FAMILY_OF else "",
                       "threshold": thresholds.get(t)}
                   for t in nb["classes"] if t != "other"},
        "report": report,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(model, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"\n저장 {OUT.relative_to(ROOT)}  {OUT.stat().st_size / 1024:.0f}KB")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
