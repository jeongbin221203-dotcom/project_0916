"""㉒㉔ 컨테이너·B/L 조회 — 번호 판정이 맞는가.

컨테이너 번호는 B/L·포장명세서·적재목록에 그대로 실립니다. 한 자리를 잘못
적으면 그 화물을 추적할 수 없고 선사·세관 기록과 어긋납니다.
"""
import sys, io, random, string
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from tests._fuzz_app import build_app
from app.collectors import container_client as C
from app.services import container_tracking_service as T

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 100000
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 2224)

app = build_app()
bad, checked, caught, typos = [], 0, 0, 0
with app.app_context():
    for _ in range(ROUNDS):
        owner = "".join(random.choices(string.ascii_uppercase, k=3))
        category = random.choice(C.CATEGORY_LETTERS)
        serial = f"{random.randrange(1000000):06d}"
        head = owner + category + serial
        real = head + str(C.container_check_digit(head))
        checked += 3
        # ① 규칙대로 만든 번호는 반드시 통과
        if not C.container_no_valid(real):
            bad.append(f"규칙대로 만든 {real} 을 막음")
        if not C.is_container_no(real):
            bad.append(f"{real} 모양 판정 실패")
        if T.detect_kind(real) != "container":
            bad.append(f"{real} 를 컨테이너로 못 알아봄")

        # ② 한 자리 오타는 반드시 걸려야 합니다
        at = random.randrange(11)
        pool = string.ascii_uppercase if at < 4 else string.digits
        other = random.choice([c for c in pool if c != real[at]])
        typo = real[:at] + other + real[at + 1:]
        if typo != real and C.CONTAINER_NO.match(typo):
            typos += 1
            checked += 1
            # ISO 6346 은 나머지 10과 0을 같은 끝자리(0)로 씁니다. 그래서 한 자리
            # 오타의 약 1/11 은 표준 자체로 잡을 수 없습니다. 우리 잘못이 아니라
            # 표준의 한계이므로 비율만 잽니다.
            caught += not C.container_no_valid(typo)

        # ③ 틀린 번호는 화면에서 '번호가 틀렸다'고 말해야 합니다
        if typos and typos % 500 == 0 and not C.container_no_valid(typo):
            checked += 1
            message = T.track(typo)["message"]
            if "있을 수 없는" not in message:
                bad.append(f"{typo}: 틀린 번호인데 알려 주지 않음 — {message[:60]}")

        # ④ 적는 모양이 달라도 같은 결과
        checked += 1
        spaced = f"{real[:4]} {real[4:7]} {real[7:]}"
        if C.container_no_valid(spaced) != C.container_no_valid(real):
            bad.append(f"{real}: 띄어 쓰면 결과가 달라짐")

    # ⑤ 번호 종류 가려내기
    KINDS = [("CSQU3054383", "container"), ("MSKU6874230", "container"),
             ("123456789012345", "export_declaration"),
             ("HLCUBO12345678", "bl"), ("MAEU123456789", "bl"),
             ("24KRPUS1234567890", "cargo"), ("", "")]
    for value, want in KINDS:
        checked += 1
        got = T.detect_kind(value)
        if got != want:
            bad.append(f"{value!r} → '{got}' (기대 '{want}')")

print(f"■ ㉒㉔ 컨테이너 번호 {ROUNDS:,}개 · 확인 {checked:,}가지 · 문제 {len(bad)}건")
print(f"   한 자리 오타 {typos:,}가지 중 잡아낸 것 {caught:,} ({caught*100/max(typos,1):.1f}%)")
for b in bad[:10]: print("   ★", b)
