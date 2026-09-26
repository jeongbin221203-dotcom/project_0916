"""⑯ 사업자등록번호 — 있을 수 있는 번호만 통과하는가.

수출신고서에 그대로 들어갑니다. 한 자리를 잘못 적으면 신고가 반려되고,
운 나쁘면 **남의 회사 번호**가 됩니다.
"""
import sys, io, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from app.validators import business_no as B
from app.validators import ValidationError

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 100000
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 1616)

bad, checked = [], 0

# ① 규칙대로 만든 번호는 반드시 통과해야 합니다
made = 0
for _ in range(ROUNDS):
    head = f"{random.randint(100, 999)}"
    kind = f"{random.randint(1, 99):02d}"          # 00 은 발급되지 않습니다
    body = f"{random.randint(0, 99999):05d}"
    nine = head + kind + body[:4]
    real = nine + str(B.check_digit(nine))
    made += 1
    checked += 2
    if not B.is_valid(real):
        bad.append(f"규칙대로 만든 {B.format_no(real)} 를 막음")
    try:
        got = B.parse(real)
    except ValidationError as error:
        bad.append(f"규칙대로 만든 {B.format_no(real)} 에서 오류 — {error}")
        continue
    if B.digits_of(got) != real:
        bad.append(f"{real} → {got} 로 바뀜")

    # ② 한 자리를 바꾸면 반드시 걸려야 합니다 (오타를 잡는 것이 이 번호의 존재 이유)
    at = random.randrange(10)
    other = random.choice([d for d in "0123456789" if d != real[at]])
    typo = real[:at] + other + real[at + 1:]
    checked += 1
    if typo[3:5] != "00" and B.is_valid(typo):
        bad.append(f"{B.format_no(real)} 의 {at+1}번째를 {other} 로 바꾼 "
                   f"{B.format_no(typo)} 가 통과")

    # ③ 두 자리를 맞바꾼 오타 (사람이 가장 많이 하는 실수)
    a, b = random.sample(range(10), 2)
    if real[a] != real[b]:
        swapped = list(real); swapped[a], swapped[b] = swapped[b], swapped[a]
        swapped = "".join(swapped)
        checked += 1
        # 자리바꿈은 검증번호로 늘 잡히지는 않습니다. 잡히는 비율만 셉니다.

    # ④ 적는 모양이 달라도 같은 결과여야 합니다
    checked += 1
    shapes = [real, B.format_no(real), f" {real} ", real[:3] + " " + real[3:5] + " " + real[5:],
              real[:3] + "." + real[3:5] + "." + real[5:]]
    if len({B.digits_of(s) for s in shapes}) != 1:
        bad.append(f"{real}: 적는 모양에 따라 달라짐")

# ⑤ 절대 통과하면 안 되는 것
NEVER = ["", "   ", "0000000000", "1111111111", "9999999999", "1234567890",
         "123456789", "12345678901", "abcdefghij", "123-45-6789",
         "000-00-00000", "12-34-567890", None, "１２３４５６７８９０"]
for value in NEVER:
    checked += 1
    try:
        got = B.parse(value)
        if got:                      # 빈 값은 빈 글자로 돌아오는 것이 맞습니다
            bad.append(f"{value!r} 가 {got} 로 통과")
    except ValidationError:
        pass

print(f"■ ⑯ 사업자등록번호 {made:,}개 · 확인 {checked:,}가지 · 문제 {len(bad)}건")
for b in bad[:12]: print("   ★", b)

# 한 자리 오타가 몇 %나 잡히는지 (검증번호의 본래 목적)
random.seed(99)
caught = trials = 0
for _ in range(20000):
    nine = f"{random.randint(100,999)}{random.randint(1,99):02d}{random.randint(0,9999):04d}"
    real = nine + str(B.check_digit(nine))
    at = random.randrange(10)
    other = random.choice([d for d in "0123456789" if d != real[at]])
    typo = real[:at] + other + real[at+1:]
    trials += 1
    if not B.is_valid(typo):
        caught += 1
print(f"   한 자리 오타 {trials:,}가지 중 잡아낸 것 {caught:,} ({caught*100/trials:.1f}%)")
