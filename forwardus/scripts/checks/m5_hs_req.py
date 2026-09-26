"""⑤ HS부호 → 수출요건이 류(類)·호와 맞는가. 품목표 전체에서 뽑아 봅니다."""
import sys, io, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from tests._fuzz_app import build_app
from app.collectors import hsk_catalog as H
from app.processors import export_requirements as E

RULE_BY_KEY = {rule["key"]: rule for rule in E.RULES}
app = build_app()
bad, checked = [], 0
with app.app_context():
    codes = list(H._catalog()["codes"])
    random.seed(606)
    sample = random.sample(codes, min(4000, len(codes)))
    for code in sample:
        checked += 1
        try:
            found = E.check(code, is_dangerous=False)
        except Exception as error:
            bad.append(f"{code}: 죽음 {type(error).__name__} {error}"); continue
        chapter, heading = code[:2], code[:4]
        for item in found:
            rule = RULE_BY_KEY.get(item["key"])
            if rule is None:
                bad.append(f"{code}: '{item['title']}' 규칙을 표에서 못 찾음"); continue
            if chapter not in rule["chapters"] and heading not in rule["headings"]:
                bad.append(f"{code}: '{item['title']}' 이 류·호와 안 맞는데 걸림")
            if not item.get("agency"):
                bad.append(f"{code}: '{item['title']}' 에 기관이 없음")
            if not item.get("documents"):
                bad.append(f"{code}: '{item['title']}' 에 낼 서류가 없음")
            if not (item.get("lookup") or {}).get("url"):
                bad.append(f"{code}: '{item['title']}' 에 확인할 곳이 없음")
        # 같은 부호를 몇 번 물어도 같은 답이 와야 합니다
        if [i["key"] for i in E.check(code)] != [i["key"] for i in found]:
            bad.append(f"{code}: 두 번 물으면 답이 달라짐")
        # 위험물 표시를 켜면 위험물 신고가 반드시 붙고, 끄면 붙으면 안 됩니다
        checked += 1
        if not any("위험물" in row["title"] for row in E.check(code, is_dangerous=True)):
            bad.append(f"{code}: 위험물로 표시했는데 위험물 신고가 안 붙음")
        if any("위험물" in row["title"] for row in found):
            bad.append(f"{code}: 위험물이 아닌데 위험물 신고가 붙음")
        # 한 줄 요약은 걸린 가지 수와 맞아야 합니다
        line = E.summary(code, found)
        if found and str(len(found)) not in line:
            bad.append(f"{code}: 요약이 가지 수({len(found)})와 안 맞음 — {line[:40]}")
        # 띄어쓰기·점을 넣어도 같은 답
        dotted = f"{code[:4]}.{code[4:6]}-{code[6:]}"
        if [i["key"] for i in E.check(dotted)] != [i["key"] for i in found]:
            bad.append(f"{code}: 점을 넣으면 답이 달라짐")
print(f"■ ⑤ HS부호 {len(sample)}개 · 확인 {checked}가지 · 문제 {len(bad)}건")
for b in bad[:12]: print("   ★", b)
