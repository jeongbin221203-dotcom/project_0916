"""① L/C 날짜 — 경계와 휴일. 우리가 내준 날이 진짜 마감보다 **늦으면** 돈을 못 받습니다.

지켜야 할 것
  deadline        = min(최종선적일, 유효기일 − 제시기간)   ← 어김없이
  recommended_etd ≤ deadline                              ← 권하는 날이 마감을 넘으면 안 됩니다
  cargo_ready_by  ≤ recommended_etd
  recommended_etd ≤ presentation_by ≤ 유효기일
  days_left       = (deadline − 오늘).days
"""
import sys, io, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from datetime import date, timedelta
from app.processors import lc_schedule as L

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 1122)

PRESENTATION = [None, "", "  ", "0", "1", "7", "10", "15", "20", "21", "45", "89", "90",
                "91", "-3", "999", "abc", "21일", "7.9", 21, 0, 1.0, True, [], {}]
bad, checked = [], 0
base = date(2026, 9, 26)

for turn in range(ROUNDS):
    today = base + timedelta(days=random.randint(-400, 400))
    have_latest = random.random() < 0.85
    have_expiry = random.random() < 0.85
    if not have_latest and not have_expiry:
        checked += 1
        if L.plan(today=today) is not None:
            bad.append(f"{turn}: 날짜가 하나도 없는데 계산을 냄")
        continue
    latest = today + timedelta(days=random.randint(-120, 400)) if have_latest else None
    expiry = today + timedelta(days=random.randint(-120, 460)) if have_expiry else None
    raw = random.choice(PRESENTATION)
    mode = random.choice(["SEA", "AIR", "sea", "air", "", None, "TRUCK"])
    transit = random.choice([None, (3, 5), (18, 32), (1, 1), (45, 60)])

    try:
        got = L.plan(latest_shipment=latest, expiry=expiry, presentation=raw,
                     transport_mode=mode, transit_days=transit, today=today)
    except Exception as error:
        bad.append(f"{turn}: 죽음 {type(error).__name__} {error}"); continue
    if got is None:
        bad.append(f"{turn}: 날짜가 있는데 계산이 안 나옴"); continue

    days = got["presentation_days"]
    checked += 8

    # 제시기간이 범위 밖이면 21일이어야 합니다
    want_days, want_stated = L.presentation_days(raw)
    if (days, got["presentation_stated"]) != (want_days, want_stated):
        bad.append(f"{turn}: 제시기간 {raw!r} → {days}/{got['presentation_stated']} "
                   f"(기대 {want_days}/{want_stated})")
    if not (L.MIN_PRESENTATION_DAYS <= days <= L.MAX_PRESENTATION_DAYS):
        bad.append(f"{turn}: 제시기간이 범위 밖 {days}일")

    # ① 마감은 둘 중 빠른 날
    by_expiry = expiry - timedelta(days=days) if expiry else None
    want_deadline = min([d for d in (latest, by_expiry) if d])
    if got["deadline"] != want_deadline:
        bad.append(f"{turn}: 마감 {got['deadline']} ≠ {want_deadline} "
                   f"(최종선적 {latest} · 유효기일 {expiry} − {days}일)")
    want_reason = ("both" if latest and by_expiry and latest == by_expiry
                   else "expiry" if by_expiry and want_deadline == by_expiry
                   else "latest_shipment")
    if got["deadline_reason"] != want_reason:
        bad.append(f"{turn}: 이유 '{got['deadline_reason']}' ≠ '{want_reason}'")

    # ② 권하는 선적일이 마감을 넘으면 안 됩니다 — 넘으면 대금을 못 받습니다
    if got["recommended_etd"] > got["deadline"]:
        bad.append(f"{turn}: 권한 선적일 {got['recommended_etd']} 이 마감 {got['deadline']} 을 넘음")
    if got["cargo_ready_by"] > got["recommended_etd"]:
        bad.append(f"{turn}: 화물 준비일이 선적일보다 늦음")

    # ③ 서류 제시는 선적 뒤, 유효기일 안
    if got["presentation_by"] < got["recommended_etd"]:
        bad.append(f"{turn}: 서류 제시일 {got['presentation_by']} 이 선적일보다 이름")
    if expiry and got["presentation_by"] > expiry:
        bad.append(f"{turn}: 서류 제시일 {got['presentation_by']} 이 유효기일 {expiry} 을 넘음")

    # ④ 남은 날·가능 여부
    if got["days_left"] != (got["deadline"] - today).days:
        bad.append(f"{turn}: 남은 날 {got['days_left']} 이 안 맞음")
    needed = L.prep_days(mode)
    if got["feasible"] != (today + timedelta(days=needed) <= got["deadline"]):
        bad.append(f"{turn}: 가능 여부가 안 맞음 (needed {needed})")
    if not got["feasible"] and not any("연장" in note for note in got["notes"]):
        bad.append(f"{turn}: 못 맞추는데 연장 이야기가 없음")

    # ⑤ 도착 예상
    checked += 1
    if transit:
        low, high = min(transit), max(transit)
        if got["eta_from"] != got["recommended_etd"] + timedelta(days=low) \
                or got["eta_to"] != got["recommended_etd"] + timedelta(days=high):
            bad.append(f"{turn}: 도착 예상이 소요일과 안 맞음")
    elif got["eta_from"] or got["eta_to"]:
        bad.append(f"{turn}: 소요일을 안 줬는데 도착 예상을 만들어 냄")

    # ⑥ 글자로 바꿔도 날이 그대로인가
    checked += 1
    text = L.as_text(got)
    for key in ("deadline", "recommended_etd", "cargo_ready_by", "presentation_by"):
        if text[key] != got[key].isoformat():
            bad.append(f"{turn}: {key} 글자 변환이 어긋남")
            break

print(f"■ ① L/C 날짜 {ROUNDS:,}가지 · 확인 {checked:,}가지 · 문제 {len(bad)}건")
seen = {}
for b in bad:
    seen[b.split(": ", 1)[-1][:70]] = seen.get(b.split(": ", 1)[-1][:70], 0) + 1
for key, count in sorted(seen.items(), key=lambda kv: -kv[1])[:12]:
    print(f"   ★ {count:>5}회  {key}")
