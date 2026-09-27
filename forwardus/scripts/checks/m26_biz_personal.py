"""㉖-2 기업 수출 상위 200 · 개인 수출 상위 200 으로 HS 찾기 정확도를 잽니다.

왜 둘로 나눠 재나
  같은 검색창에 회사 담당자와 개인 판매자가 같이 들어옵니다. 회사는
  "이차전지 양극재"라 적고 개인은 "보조배터리"라 적습니다. 한쪽만 맞히면
  다른 쪽은 부호를 못 찾고, 못 찾으면 아무 부호나 적어 신고합니다.
  (2026-09-27 사용자 지시)

무엇을 보나 — 두 가지
  ① 이름 그대로 쳤을 때      "황산니켈"
  ② 사람이 실제로 적는 대로   "황산니켈 HS코드", "황산니켈은 몇번이에요"
  ②가 중요합니다. ①만 통과하고 ②가 0건이던 것이 이 검사로 드러났습니다.

기대값은 표 자신이 적어 둔 호입니다. 검사와 표가 어긋날 수 없게 표에서
직접 읽어 옵니다 — 표에 품목을 더하면 검사 대상도 함께 늘어납니다.

    python scripts/checks/m26_biz_personal.py
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from app.collectors import hsk_catalog as H
from tests._fuzz_app import build_app

# 무역을 모르는 분이 실제로 적는 말버릇입니다. 하나라도 0건이면 안 됩니다.
HABITS = ("{}", "{} HS코드", "{} hs코드", "{} 품목번호", "{}는 몇번이에요",
          "{} 세번", "{} 관세율", "{} 수출하려는데")


def measure(label: str, table: dict) -> tuple[int, int, int, list[str]]:
    """한 표를 다 훑습니다. (전체, 맨 위가 맞음, 목록에 있음, 어긋난 것)"""

    top = inside = 0
    bad: list[str] = []
    for name, want in table.items():
        total_forms = 0
        top_forms = 0
        in_forms = 0
        for habit in HABITS:
            total_forms += 1
            rows = H.search(habit.format(name)) or []
            codes = [str(row.get("code") or "") for row in rows]
            at = next((i for i, code in enumerate(codes)
                       if any(code.startswith(w) for w in want)), None)
            if at is None:
                bad.append(f"{habit.format(name)}: 기대 {want} · 나온 것 {codes[:3] or '0건'}")
            else:
                in_forms += 1
                if at == 0:
                    top_forms += 1
        # 말버릇을 다 통과해야 그 품목이 통과입니다.
        if in_forms == total_forms:
            inside += 1
        if top_forms == total_forms:
            top += 1
    return len(table), top, inside, bad


def main() -> int:
    app = build_app()
    worst: list[str] = []
    with app.app_context():
        for label, table in (("기업 수출 상위", H.HEADINGS_BUSINESS),
                             ("개인 수출 상위", H.HEADINGS_PERSONAL)):
            total, top, inside, bad = measure(label, table)
            print(f"■ {label} {total}개 · 말버릇 {len(HABITS)}가지 = {total * len(HABITS)}회")
            print(f"   말버릇 전부에서 맨 위가 맞음 {top}개 ({top * 100 / total:.0f}%)")
            print(f"   말버릇 전부에서 목록에 있음  {inside}개 ({inside * 100 / total:.0f}%)")
            print(f"   어긋난 물음                 {len(bad)}회\n")
            worst += bad

    for row in worst[:40]:
        print("   ☆", row)
    if len(worst) > 40:
        print(f"   … 그 밖에 {len(worst) - 40}회")
    return 1 if worst else 0


if __name__ == "__main__":
    raise SystemExit(main())
