"""㉖ 품목표 **전체**로 찾기 정확도를 잽니다. (부호 11,327 + 상위 이름 5,745)

손으로 200개를 이어 두는 것으로는 모자랍니다. 찾기 자체가 얼마나 맞는지를
품목표 전체로 재고, 안 맞는 쪽을 고칩니다.

어떻게 재나
  ㄱ) 그 부호의 **제 이름**으로 찾으면 그 부호가 나오는가 (가장 기본)
  ㄴ) 사람이 치는 만큼만 적었을 때 — 괄호·부연을 떼고 **앞 낱말 2~3개**만
  ㄷ) 호(4자리) 이름으로 찾으면 그 호의 부호가 나오는가
"""
import sys, io, random, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from tests._fuzz_app import build_app
from app.collectors import hsk_catalog as H

SAMPLE = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 2626)

DROP = re.compile(r"\([^)]*\)|\[[^\]]*\]")          # 괄호 안 부연
GENERIC = {"기타", "그밖의것", "그밖의물품", "기타의것"}


def as_typed(name: str, words: int) -> str:
    """사람이 치는 만큼만. 괄호를 떼고 앞 낱말 몇 개."""
    plain = DROP.sub(" ", name)
    plain = plain.replace("ㆍ", " ").replace("·", " ").replace(",", " ")
    parts = [p for p in plain.split() if p.strip()]
    return " ".join(parts[:words])


app = build_app()
with app.app_context():
    catalog = H._catalog()
    codes = list(catalog["codes"])
    levels = catalog.get("levels") or {}

    # 같은 이름이 여러 부호에 붙어 있습니다. ("면으로 만든 것" 이 수십 개)
    # 이름만으로는 그중 하나를 고를 수 없으므로, **같은 이름을 가진 부호 아무거나**
    # 나오면 맞은 것으로 봅니다. 이름이 몇 개 부호에 걸쳐 있는지도 함께 셉니다.
    by_name = {}
    for code, (name, _en) in catalog["codes"].items():
        by_name.setdefault(H._plain(name), set()).add(code)

    def wants(code):
        return by_name.get(H._plain(catalog["codes"][code][0]), {code})

    def score(pairs, label, limit=12):
        top1 = inlist = missing = skipped = 0
        misses = []
        for query, want in pairs:
            if not query or len(query) < 2:
                skipped += 1
                continue
            rows = H.search(query, limit) or []
            # 나오는 부호는 "8807.20-0000" 모양입니다. 점·줄표를 떼고 견줍니다.
            got = [re.sub(r"[.\-]", "", str(r.get("code") or "")) for r in rows]
            if not got:
                missing += 1
                if len(misses) < 8: misses.append(f"'{query}' → 아무것도 없음")
                continue
            ok = want if isinstance(want, set) else {want}
            at = next((i for i, c in enumerate(got)
                       if any(c.startswith(w) for w in ok)), None)
            if at is None:
                if len(misses) < 8:
                    misses.append(f"'{query}' → {got[:2]} (기대 {sorted(ok)[:2]})")
            else:
                inlist += 1
                top1 += (at == 0)
        total = len(pairs) - skipped
        print(f"  {label:<34} 맨 위 {top1 * 100 / max(total,1):5.1f}%"
              f" · 목록 안 {inlist * 100 / max(total,1):5.1f}%"
              f" · 아무것도 없음 {missing * 100 / max(total,1):4.1f}%   ({total:,}개)")
        return misses

    picks = random.sample(codes, min(SAMPLE, len(codes)))
    shared = sum(1 for c in picks if len(wants(c)) > 1)
    print(f"  (뽑은 {len(picks):,}개 중 같은 이름이 여러 부호에 붙은 것 {shared:,}개 "
          f"— 이름만으로는 하나를 고를 수 없습니다)")
    # ㄱ) 제 이름 그대로
    m1 = score([(catalog["codes"][c][0], wants(c)) for c in picks
                if H._plain(catalog["codes"][c][0]) not in GENERIC], "① 제 이름 그대로")
    # ㄴ) 사람이 치는 만큼 (앞 낱말 2개 / 3개)
    m2 = score([(as_typed(catalog["codes"][c][0], 2), wants(c)) for c in picks
                if H._plain(catalog["codes"][c][0]) not in GENERIC], "② 앞 낱말 2개만")
    m3 = score([(as_typed(catalog["codes"][c][0], 3), wants(c)) for c in picks
                if H._plain(catalog["codes"][c][0]) not in GENERIC], "③ 앞 낱말 3개만")
    # ㄷ) 호 이름으로 (4자리)
    heads = [h for h in levels if len(h) == 4]
    hpicks = random.sample(heads, min(SAMPLE, len(heads)))
    m4 = score([(as_typed(levels[h][0], 2), h) for h in hpicks], "④ 호 이름 앞 낱말 2개")
    print()
    for label, misses in (("①", m1), ("②", m2), ("③", m3), ("④", m4)):
        for x in misses[:4]:
            print(f"   {label} ☆ {x[:110]}")
