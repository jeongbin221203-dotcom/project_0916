"""③ 계산 — Decimal로 따로 셈해서 맞대어 봅니다. 값의 폭을 크게 늘렸습니다.

CBM은 금액과 바로 이어집니다(⑧). 아주 작은 화물·아주 큰 화물·한쪽으로
길쭉한 화물·무거운 화물을 섞어, 부동소수점 때문에 어긋나는 자리가 없는지 봅니다.
"""
import sys, io, random, math
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP, getcontext
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
getcontext().prec = 60
from app.processors import cargo_calculator as C
from app.validators.cargo_validator import PACKAGE_TYPES
PACKS = sorted(PACKAGE_TYPES)

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 99)
D = Decimal
FACTOR = D(1_000_000) / D(C.AIR_VOLUME_DIVISOR_CM3)      # 166.666… 그대로


def q(value: Decimal, digits: int) -> Decimal:
    return value.quantize(D(1).scaleb(-digits), rounding=ROUND_HALF_UP)


def money(value: Decimal) -> Decimal:
    """금액은 사사오입 — 은행·세관과 같은 셈법."""
    return value.quantize(D("0.01"), rounding=ROUND_HALF_UP)


def volume(value: Decimal) -> Decimal:
    """round_volume 과 같은 규칙 — 0보다 큰 값을 0으로 만들지 않습니다."""
    rounded = q(value, 4)
    if rounded == 0 and value > 0:
        deep = q(value, 9)
        return deep if deep != 0 else value
    return rounded


def a_size():
    """실제로 들어오는 상자 크기의 폭"""
    kind = random.random()
    if kind < 0.12:   return D(str(random.choice([1, 2, 3, 5, 7.5])))          # 아주 작은 것
    if kind < 0.25:   return D(str(random.choice([580, 1180, 1200, 1990])))    # 아주 큰 것
    if kind < 0.35:   return D(str(round(random.uniform(0.1, 3), 2)))          # 얇은 것
    return D(str(round(random.uniform(10, 160), random.choice([0, 1, 2]))))


bad, checked = [], 0
for turn in range(ROUNDS):
    kind = random.choice(list(C.CONTAINER_SPECS))
    rows, want_lines = [], []
    for _ in range(random.randint(1, 6)):
        L, Wd, H = a_size(), a_size(), a_size()
        count = random.choice([1, 2, 7, 33, 100, 480, 1999, 9999])
        # 반올림해서 0 이 되면 서버가 옳게 막습니다(확인함). 그건 여기서
        # 보려는 것이 아니므로 0 이 되지 않게 만듭니다.
        each = D(str(round(random.uniform(0.01, 900), random.choice([0, 1, 2, 3]))))
        if each <= 0:
            each = D("0.01")
        price = D(str(round(random.uniform(0.01, 50000), 2)))
        rows.append({"length_cm": str(L), "width_cm": str(Wd), "height_cm": str(H),
                     "quantity": str(count), "weight_per_package_kg": str(each),
                     "unit_price": str(price), "package_type": random.choice(PACKS),
                     "product_description": "시험 화물"})
        unit = L * Wd * H / D(1_000_000)
        want_lines.append({
            "cbm": volume(unit * count),
            "kg": q(each * count, 2),
            "rt": q(max(volume(unit * count), q(each * count, 2) / D(1000)), 3),
        })

    try:
        got = C.calculate_cargo_lines(rows, kind, strict=True)
    except Exception as error:
        bad.append(f"{turn}: 죽음 {type(error).__name__} {error}"); continue

    # ── 품목별 ──
    for index, (line, want) in enumerate(zip(got["lines"], want_lines), start=1):
        checked += 3
        if D(str(line["total_cbm"])) != want["cbm"]:
            bad.append(f"{turn}/{index}: CBM {line['total_cbm']} ≠ {want['cbm']}")
        if D(str(line["total_weight_kg"])) != want["kg"]:
            bad.append(f"{turn}/{index}: 총중량 {line['total_weight_kg']} ≠ {want['kg']}")
        if D(str(line["revenue_ton"])) != want["rt"]:
            bad.append(f"{turn}/{index}: R/T {line['revenue_ton']} ≠ {want['rt']}")
        # 용적중량 — 반올림한 166.67 을 쓰면 여기서 어긋납니다
        checked += 1
        if D(str(line["volume_weight_kg"])) != q(want["cbm"] * FACTOR, 2):
            bad.append(f"{turn}/{index}: 용적중량 {line['volume_weight_kg']} "
                       f"≠ {q(want['cbm'] * FACTOR, 2)}")
        checked += 1
        charge = q(max(want["kg"], want["cbm"] * FACTOR), 2)
        if D(str(line["chargeable_weight_kg"])) != charge:
            bad.append(f"{turn}/{index}: 운임중량 {line['chargeable_weight_kg']} ≠ {charge}")
        # 금액 = 단가 × 수량
        checked += 1
        want_money = money(D(rows[index - 1]["unit_price"]) * D(rows[index - 1]["quantity"]))
        if line.get("amount") is not None and D(str(line["amount"])) != want_money:
            bad.append(f"{turn}/{index}: 금액 {line['amount']} ≠ {want_money}")

    # ── 합계 ── (줄마다 맞춘 값을 더하는 것이 화면·송장과 맞습니다)
    sum_cbm = volume(sum((w["cbm"] for w in want_lines), D(0)))
    sum_kg = q(sum((w["kg"] for w in want_lines), D(0)), 2)
    checked += 2
    if D(str(got["total_cbm"])) != sum_cbm:
        bad.append(f"{turn}: 합계 CBM {got['total_cbm']} ≠ {sum_cbm}")
    if D(str(got["total_weight_kg"])) != sum_kg:
        bad.append(f"{turn}: 합계 중량 {got['total_weight_kg']} ≠ {sum_kg}")
    checked += 1
    rt = q(max(sum_cbm, sum_kg / D(1000)), 3)
    if D(str(got["revenue_ton"])) != rt:
        bad.append(f"{turn}: 합계 R/T {got['revenue_ton']} ≠ {rt}")
    checked += 1
    if D(str(got["billable_revenue_ton"])) != q(max(D(1), rt), 3):
        bad.append(f"{turn}: 청구 R/T {got['billable_revenue_ton']} ≠ {q(max(D(1), rt), 3)}")
    # 컨테이너 수 — 부피·중량 중 큰 쪽, 최소 1
    spec = C.CONTAINER_SPECS[kind]
    by_v = math.ceil(sum_cbm / D(str(spec["max_cbm"])))
    by_w = math.ceil(sum_kg / D(spec["max_weight_kg"]))
    checked += 1
    if got["container_quantity"] != max(1, by_v, by_w):
        bad.append(f"{turn}: {kind} 개수 {got['container_quantity']} ≠ {max(1, by_v, by_w)}")
    # 송장 금액 = 품목 금액의 합
    checked += 1
    money_sum = money(sum((money(D(r["unit_price"]) * D(r["quantity"])) for r in rows), D(0)))
    if got.get("amount") is not None and D(str(got["amount"])) != money_sum:
        bad.append(f"{turn}: 송장 금액 {got['amount']} ≠ {money_sum}")
    # 0보다 큰 화물이 부피 0으로 떨어지면 운임 기준이 사라집니다
    checked += 1
    if got["total_cbm"] <= 0:
        bad.append(f"{turn}: 합계 CBM 이 0 — 운임 기준이 사라짐")

print(f"■ ③ 계산 독립 검산 {ROUNDS:,}회 · 확인 {checked:,}가지 · 문제 {len(bad)}건")
for b in bad[:14]: print("   ★", b)
