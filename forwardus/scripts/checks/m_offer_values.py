# -*- coding: utf-8 -*-
"""오퍼시트의 **돈·수량·통화·포장·중량**을 양식별로 잽니다.

왜 따로 보나
  m_offer_formats.py 는 인코텀즈·항구·날짜를 봅니다. 이 파일은 **숫자**를 봅니다.
  숫자가 틀리면 가장 크게 다칩니다. 항구가 비면 사람이 눈치채지만, 단가가
  8,616 대신 8.616 로 들어가면 그대로 송장이 나갑니다.

무엇을 흔드나 (실제 무역서류 표기만 씁니다)
  금액    8616.00 / 8,616.00 / USD 8,616.00 / US$8,616.00 / $8,616.00 / 8 616,00
  수량    720 / 720 PCS / 1,200 / 1,200 PCS
  통화    USD / US$ / $ / usd
  포장    carton / cartons / CTN / export cartons / 50 CTNS
  중량    500 / 500 KG / 500.00 KGS / 0.5 MT

무엇이 맞는 답인가
  **읽히면 정확한 값, 안 읽히면 빈 칸.** 어림잡은 값은 틀린 답입니다.
  특히 유럽식 소수점(8.616,00 = 8616)은 미국식으로 읽으면 천 배가 틀립니다.
  가릴 수 없으면 비우는 것이 맞습니다.
"""
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app import create_app                                    # noqa: E402
from config import TestConfig                                 # noqa: E402
from app.services import document_extract_service as X        # noqa: E402

# (적는 모양, 뜻하는 값 · None 이면 "비워야 맞다")
MONEY = [
    ("8616.00", 8616.0),
    ("8,616.00", 8616.0),
    ("8616", 8616.0),
    ("6.50", 6.5),
    ("USD 8,616.00", 8616.0),        # 통화를 붙여 적습니다
    ("US$8,616.00", 8616.0),
    ("$8,616.00", 8616.0),
    ("8,616.00 USD", 8616.0),
    # 유럽식. 8.616,00 은 8616 입니다(마침표가 천 단위, 쉼표가 소수점).
    # 예전에는 쉼표·빈칸을 무조건 떼어 8.616 로 읽었습니다 — **천 배** 틀렸고,
    # 송장에 그대로 찍혀 나가도 아무도 못 알아챕니다. (2026-09-28 고침)
    ("8.616,00", 8616.0),
    ("8 616,00", 8616.0),
    ("1.234.567,89", 1234567.89),
    # 숫자가 아닌 것
    ("", None), ("-", None), ("TBD", None), ("무료", None),
    ("0", None),                     # 0원짜리 줄은 받지 않습니다
    ("-100", None),                  # 음수는 받지 않습니다
]

QUANTITY = [
    ("720", 720.0), ("1,200", 1200.0), ("2,500", 2500.0),
    ("720 PCS", 720.0), ("1,200 pcs", 1200.0),
    ("50 CTN", 50.0), ("50 CTNS", 50.0),
    ("", None), ("몇 개", None),
]

WEIGHT = [
    ("500", 500.0), ("500 KG", 500.0), ("500.00 KGS", 500.0),
    ("1,100 KG", 1100.0), ("432", 432.0),
    ("0.5 MT", None),                # 단위가 달라 곱해야 합니다. 짐작하지 않습니다.
    ("", None),
]

# 통화는 세 글자 코드만 받습니다. "US$" · "$" 는 코드가 아니라 기호라
# 어느 나라 달러인지 가릴 수 없습니다(USD·CAD·AUD·SGD·HKD). 비웁니다.
CURRENCY = [("USD", "USD"), ("usd", "USD"), ("KRW", "KRW"), ("EUR", "EUR"),
            ("US$", ""), ("$", ""), ("", ""), ("달러", "")]

# 포장 종류는 **package_unit**(서류에 찍힌 단위 글자)에서 읽습니다.
# package_type 은 AI 가 우리 낱말로 고른 값이라 다릅니다.
PACKAGE = [("CARTON", "carton"), ("CTN", "carton"), ("CTNS", "carton"),
           ("BOX", "carton"), ("PLT", "pallet"), ("DRUM", "drum"),
           ("BAG", "flexible_bag"), ("", ""), ("아무말", "")]


def _near(got: str, want) -> bool:
    if want is None:
        return got == ""
    if got == "":
        return False
    try:
        return abs(float(got) - want) < 0.005
    except ValueError:
        return False


# ── 한 장을 통째로, 나라별 관습대로 적었을 때 ────────────────────────────────
#
# 위는 자리마다 표기를 하나씩 봤습니다. 여기서는 **오퍼시트 한 장**을 그 나라
# 방식으로 적어 놓고 칸이 제대로 차는지 봅니다. 실제로 받는 서류의 모습입니다.

# 표본 PDF 5건 그대로. (수량, 단가, 금액, 총액, 순중량)
DEALS = [
    ((720, 6.50, 4680.00), (480, 8.20, 3936.00), 8616.00, 432),
    ((1800, 2.40, 4320.00), (1200, 5.10, 6120.00), 10440.00, 960),
    ((1600, 1.80, 2880.00), (800, 2.70, 2160.00), 5040.00, 480),
    ((2500, 1.20, 3000.00), (1500, 1.60, 2400.00), 5400.00, 1050),
    ((1200, 3.10, 3720.00), (600, 3.80, 2280.00), 6000.00, 648),
]


def _us(value) -> str:
    """미국식 8,616.00"""
    return f"{value:,.2f}"


def _euro_dot(value) -> str:
    """유럽식 8.616,00 — 마침표가 천 단위, 쉼표가 소수점"""
    return f"{value:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _euro_space(value) -> str:
    """프랑스식 8 616,00 — 빈칸이 천 단위"""
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def _plain(value) -> str:
    """민짜 8616.00"""
    return f"{value:.2f}"


NUMBER_STYLES = [("미국식", _us), ("유럽식", _euro_dot),
                 ("프랑스식", _euro_space), ("민짜", _plain)]
MONEY_WRAP = [("그대로", lambda s: s), ("앞에 USD", lambda s: f"USD {s}"),
              ("앞에 US$", lambda s: f"US${s}"), ("앞에 $", lambda s: f"${s}"),
              ("뒤에 USD", lambda s: f"{s} USD")]
QTY_UNIT = [("없음", ""), ("PCS", " PCS"), ("pcs", " pcs"), ("CTN", " CTN")]
KG_UNIT = [("없음", ""), ("KG", " KG"), ("KGS", " KGS")]


def whole_sheets() -> list[dict]:
    """양식 50가지. 자리마다 버릇을 돌려 가며 씁니다."""

    cases = []
    no = 0
    for num_name, num_fn in NUMBER_STYLES:
        for wrap_name, wrap_fn in MONEY_WRAP:
            for lines_wanted in (2, 1):
                no += 1
                if no > 50:
                    return cases
                first, second, total, net = DEALS[no % len(DEALS)]
                qty_name, qty_unit = QTY_UNIT[no % len(QTY_UNIT)]
                kg_name, kg_unit = KG_UNIT[no % len(KG_UNIT)]
                rows = [first] + ([second] if lines_wanted == 2 else [])
                # 수량·중량도 **같은 나라 식으로** 적습니다. 실제 서류가 그렇습니다.
                # (유럽 오퍼시트에서 수량만 미국식으로 적지 않습니다)
                whole = (lambda v: f"{v:,}".replace(",", ".")) if num_name in ("유럽식",) else                         (lambda v: f"{v:,}".replace(",", " ")) if num_name == "프랑스식" else                         (lambda v: f"{v:,}") if num_name == "미국식" else (lambda v: f"{v}")
                items = [{"product_description": f"시험품목 {n}",
                          "package_count": f"{whole(count)}{qty_unit}",
                          "unit_price": wrap_fn(num_fn(price)),
                          "amount": wrap_fn(num_fn(money)),
                          "net_weight_kg": f"{whole(net)}{kg_unit}"}
                         for n, (count, price, money) in enumerate(rows, 1)]
                cases.append({
                    "no": no,
                    "이름": f"{num_name} · {wrap_name} · 수량{qty_name} · 중량{kg_name} · {lines_wanted}줄",
                    "items": items,
                    "want": [(count, price, money) for count, price, money in rows],
                    "want_net": float(net),
                })
    return cases


def check_whole_sheets() -> list[str]:
    """틀린 것만 돌려줍니다."""

    wrong = []
    for case in whole_sheets():
        for no, (raw, want) in enumerate(zip(case["items"], case["want"]), 1):
            line = X._item(raw, [], no)
            count, price, money = want
            for key, expect, label in (("quantity", count, "수량"),
                                       ("unit_price", price, "단가"),
                                       ("amount", money, "금액"),
                                       ("net_weight_kg", case["want_net"], "순중량")):
                got = line.get(key, "")
                if not _near(got, expect):
                    wrong.append(f"{case['no']:>2}. {case['이름']} · 줄{no} {label}: "
                                 f"받음 {got!r} · 기대 {expect} · 넣은 값 {raw.get(key if key != 'quantity' else 'package_count')!r}")
    return wrong


def main() -> int:
    app = create_app(TestConfig)
    bad = []
    checked = 0
    with app.app_context():
        # --- 금액·단가 -------------------------------------------------------
        for written, want in MONEY:
            for key, label in (("unit_price", "단가"), ("amount", "금액")):
                notes: list = []
                line = X._item({key: written, "product_description": "시험"}, notes, 1)
                checked += 1
                if not _near(line.get(key, ""), want):
                    bad.append((f"{label} {written!r}", want, line.get(key, "")))

        # --- 수량 ------------------------------------------------------------
        for written, want in QUANTITY:
            notes = []
            line = X._item({"package_count": written, "product_description": "시험"}, notes, 1)
            checked += 1
            if not _near(line.get("quantity", ""), want):
                bad.append((f"수량 {written!r}", want, line.get("quantity", "")))

        # --- 중량 ------------------------------------------------------------
        for written, want in WEIGHT:
            notes = []
            line = X._item({"net_weight_kg": written, "product_description": "시험"}, notes, 1)
            checked += 1
            if not _near(line.get("net_weight_kg", ""), want):
                bad.append((f"순중량 {written!r}", want, line.get("net_weight_kg", "")))

        # --- 통화 ------------------------------------------------------------
        for written, want in CURRENCY:
            form = X.to_form({"currency": written})["fields"]
            checked += 1
            if form.get("currency", "") != want:
                bad.append((f"통화 {written!r}", want, form.get("currency", "")))

        # --- 포장 종류 -------------------------------------------------------
        for written, want in PACKAGE:
            line = X._item({"package_unit": written, "product_description": "시험"}, [], 1)
            checked += 1
            if line.get("package_type", "") != want:
                bad.append((f"포장 {written!r}", want, line.get("package_type", "")))

        # --- 줄 금액의 합이 서류 합계와 맞는가 --------------------------------
        for lines, total, should_warn in (
                ([{"amount": "4680.00"}, {"amount": "3936.00"}], "8616.00", False),
                ([{"amount": "4680.00"}, {"amount": "3936.00"}], "9000.00", True),
                ([{"amount": "4680.00"}, {}], "8616.00", True),          # 한 줄만 읽힘
        ):
            notes = []
            X._check_amounts(lines, total, notes)
            checked += 1
            if bool(notes) != should_warn:
                bad.append((f"합계 확인 {total} · 줄 {len(lines)}",
                            "알려야 함" if should_warn else "조용해야 함",
                            "알림 " + str(len(notes)) + "건"))

    sheets = check_whole_sheets()
    print(f"■ 오퍼시트 값 표기 · 자리별 {checked}가지 + 한 장 통째로 50가지")
    print(f"   문제 {len(bad) + len(sheets)}건\n")
    for what, want, got in bad:
        print(f"  ★ {what:28} 기대 {want!r:14} 받음 {got!r}")
    for row in sheets[:20]:
        print(f"  ★ {row}")
    if len(sheets) > 20:
        print(f"  … 그 밖에 {len(sheets) - 20}건 더")
    return 1 if (bad or sheets) else 0


if __name__ == "__main__":
    raise SystemExit(main())
