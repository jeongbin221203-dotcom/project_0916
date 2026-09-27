"""⑦ 서류 간 값 어긋남 — 넓힌 조합.

지난번에는 한 번에 한 칸만 망가뜨렸습니다. 이번에는 은행이 실제로 걸고
넘어지는 자리를 넣습니다.

  ㄱ) 여러 칸을 **동시에** 어긋나게 — 하나만 알리고 나머지를 놓치지 않는가
  ㄴ) 같은 칸이 서류마다 **제각각** (A는 X · B는 Y · C는 Z)
  ㄷ) 표기만 다른 **같은 값** — "1,250.00" vs "1250" vs " 1250.0 "
       이걸 어긋남이라고 하면 멀쩡한 서류에 경고가 떠, 사람이 경고를 안 믿습니다.
  ㄹ) 눈에는 같아 보이는 **다른 글자** — "SAMPLE CO., LTD." vs "SAMPLE CO.,LTD"
       은행은 이런 것도 불일치로 봅니다. 대소문자·공백만 다른 것은 아닙니다.
  ㅁ) 한쪽만 비어 있음 — "다르다"가 아니라 "아직 안 적었다"로 갈라야 합니다
"""
import sys, io, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from tests._fuzz_app import build_app
from app.processors.document_validator import (VALIDATION_FIELDS, NUMERIC_FIELDS,
                                               validate_documents)

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 707)

KINDS = ["commercial_invoice", "packing_list", "packing_list_std",
         "proforma_invoice", "shipping_instruction"]
# 기준값이 비어 있는 칸은 어느 서류에도 안 실립니다. 없는 칸을 두고
# "서로 다르다"를 따질 수는 없으므로 흔들기에서 뺍니다.
TEXT_FIELDS: list[str] = []          # REFERENCE 를 읽은 뒤 채웁니다

REFERENCE = {
    "quantity": 100, "gross_weight_kg": 800.0, "net_weight_kg": 700.0,
    "invoice_value": 1250.0, "total_cbm": 3.0,
    "currency": "USD", "incoterms": "FOB", "hs_code": "3306.10-0000",
    "consignee": "SAMPLE CO., LTD.", "exporter": "HONG KIL DONG CO., LTD.",
    "pol": "BUSAN, KOREA", "pod": "LOS ANGELES, USA",
    "exporter_address": "45, Namdaemun-ro, Jung-gu, Seoul",
    "consignee_address": "100 Main St, Los Angeles, CA",
    "notify_party": "SAME AS CONSIGNEE", "product_description": "TOOTHPASTE",
    "package_type": "CARTON", "shipping_marks": "SAMPLE/LA/1-100",
    "etd": "2026-11-05", "vessel_or_flight": "HMM BLESSING",
    "carrier": "HMM", "payment_terms": "T/T 30 DAYS", "freight_term": "PREPAID",
    "dangerous_goods": "",
}
TEXT_FIELDS[:] = [f for f in VALIDATION_FIELDS
                  if f not in NUMERIC_FIELDS and REFERENCE.get(f)]
FORM = {kind: list(VALIDATION_FIELDS) for kind in KINDS}
LABELS = {kind: kind for kind in KINDS}


def same_number(value):
    """사람이 적는 여러 모양. 값은 같습니다."""
    number = float(value)
    return random.choice([
        f"{number:,.2f}", f"{number:,.0f}" if number == int(number) else f"{number:,.2f}",
        f" {number} ", str(int(number)) if number == int(number) else str(number),
        f"{number:.1f}",
    ])


def same_text(value):
    """대소문자·앞뒤 공백만 다른 모양. 은행도 이건 같다고 봅니다."""
    return random.choice([value, value.lower(), value.upper(),
                          f"  {value} ", " ".join(value.split())])


def looks_same_but_different(value):
    """눈에는 같아 보이는데 **다른 글자**. 은행은 불일치로 봅니다."""
    if len(value) < 4:
        return value + "X"
    return random.choice([
        value.replace(", ", ",", 1) if ", " in value else value + ".",
        value.replace(".", "", 1) if "." in value else value + " CO",
        value[:-1],
        value + " LTD",
        value.replace("O", "0", 1) if "O" in value else value + "1",
    ])


def doc_from(reference):
    return {field: reference[field] for field in VALIDATION_FIELDS
            if reference.get(field) not in (None, "")}


app = build_app()
bad = []
counts = {"ㄱ 여러 칸 동시": [0, 0], "ㄴ 서류마다 제각각": [0, 0],
          "ㄷ 표기만 다른 같은 값": [0, 0], "ㄹ 눈에는 같은 다른 글자": [0, 0],
          "ㅁ 한쪽만 빔": [0, 0]}
checked = 0

with app.app_context():
    for turn in range(ROUNDS):
        picks = random.sample(KINDS, random.randint(2, len(KINDS)))
        docs = {kind: doc_from(REFERENCE) for kind in picks}
        case = random.choice(list(counts))
        want_fields = set()

        if case == "ㄱ 여러 칸 동시":
            spoil = random.sample(TEXT_FIELDS, random.randint(2, 4))
            kind = random.choice(picks)
            for field in spoil:
                docs[kind][field] = looks_same_but_different(str(REFERENCE[field]))
                want_fields.add((kind, field))

        elif case == "ㄴ 서류마다 제각각":
            field = random.choice(TEXT_FIELDS)
            for index, kind in enumerate(picks[1:], start=1):
                docs[kind][field] = f"{REFERENCE[field]} V{index}"
                want_fields.add((kind, field))

        elif case == "ㄷ 표기만 다른 같은 값":
            for kind in picks:
                for field in random.sample(
                        [f for f in VALIDATION_FIELDS if REFERENCE.get(f)], 6):
                    if REFERENCE.get(field) in (None, ""):
                        continue
                    docs[kind][field] = (same_number(REFERENCE[field])
                                         if field in NUMERIC_FIELDS
                                         else same_text(str(REFERENCE[field])))
            # 어긋난 것이 없어야 합니다 (want_fields 비어 있음)

        elif case == "ㄹ 눈에는 같은 다른 글자":
            field = random.choice(TEXT_FIELDS)
            kind = random.choice(picks)
            changed = looks_same_but_different(str(REFERENCE[field]))
            if changed.strip().upper() == str(REFERENCE[field]).strip().upper():
                continue                      # 정말 같아졌으면 건너뜁니다
            docs[kind][field] = changed
            want_fields.add((kind, field))

        else:                                  # ㅁ 한쪽만 빔
            field = random.choice(TEXT_FIELDS)
            kind = random.choice(picks)
            docs[kind][field] = ""
            want_fields.add((kind, field))

        checked += 1
        try:
            found = validate_documents(docs, REFERENCE, LABELS, FORM)
        except Exception as error:
            bad.append(f"{turn} [{case}]: 죽음 {type(error).__name__} {error}")
            continue
        got = {(row["document"], row["field"]) for row in found["findings"]}

        missed = want_fields - got
        extra = got - want_fields
        counts[case][0] += len(missed)
        counts[case][1] += len(extra)
        if missed and len(bad) < 40:
            bad.append(f"{turn} [{case}] 미탐: {sorted(missed)}")
        if extra and len(bad) < 40:
            bad.append(f"{turn} [{case}] 오탐: {sorted(extra)[:3]} "
                       f"(적은 값 {docs[sorted(extra)[0][0]].get(sorted(extra)[0][1])!r})")

print(f"■ ⑦ 서류 간 어긋남(넓힌 조합) {ROUNDS:,}회 · 확인 {checked:,}가지")
print(f"   {'무엇을 흔들었나':<26}{'미탐':>7}{'오탐':>7}")
for case, (missed, extra) in counts.items():
    print(f"   {case:<26}{missed:>7}{extra:>7}")
print(f"   죽음 {sum(1 for b in bad if '죽음' in b)}건")
for b in bad[:10]:
    print("   ★", b[:150])
