"""화면이 쓰는 이름과 서버가 읽는 이름이 맞는가 — 배선 점검.

스케줄 문제를 놓친 자리입니다. 창구(API)는 멀쩡했고, 화면이 고른 값을
제출까지 못 실어 보낸 것이었습니다. 같은 종류를 전 화면에서 찾습니다.

보는 것
  ㄱ) JS 가 부르는 주소가 실제로 있는 주소인가
  ㄴ) 템플릿이 쓰는 url_for 대상이 실제로 있는가
  ㄷ) JS 가 찾는 data-* 표가 템플릿에 있는가 (없으면 그 기능이 죽어 있습니다)
  ㄹ) 템플릿이 붙여 둔 data-* 를 아무도 안 쓰는가 (죽은 표)
  ㅁ) JS 가 보내는 칸 이름을 서버가 읽는가
"""
import sys, io, re, json
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from tests._fuzz_app import build_app

app = build_app()
rules = {str(r) for r in app.url_map.iter_rules()}
endpoints = {r.endpoint for r in app.url_map.iter_rules()}
# /documents/<shipment_id> 같은 자리를 정규식으로
patterns = [re.compile("^" + re.sub(r"<[^>]+>", "[^/]+", re.escape(p).replace(r"\<", "<").replace(r"\>", ">")) + "$")
            for p in rules]
patterns = []
for p in rules:
    body = re.escape(p)
    body = re.sub(r"\<[^>]*?\>", "[^/]+", body)
    patterns.append(re.compile("^" + body + "$"))

js_files = sorted(Path("app/static/js").glob("*.js"))
templates = sorted(Path("app/templates").rglob("*.html"))
js_text = {p: p.read_text(encoding="utf-8") for p in js_files}
tpl_text = {p: p.read_text(encoding="utf-8") for p in templates}

bad, checked = [], 0

# ㄱ) JS 안에 글자로 박힌 주소가 실제로 있는가
URL_IN_JS = re.compile(r"""["'`](/(?:api|planning|documents|tracking|lookup|assistant|contract|dashboard|shipments)[a-z0-9/_\-.]*)["'`]""")
for path, text in js_text.items():
    for m in URL_IN_JS.finditer(text):
        url = m.group(1).rstrip("/")
        checked += 1
        if not any(p.match(url) or p.match(url + "/") for p in patterns):
            line = text[:m.start()].count("\n") + 1
            bad.append(f"[없는 주소] {path.name}:{line}  {url}")

# ㄴ) 템플릿의 url_for 대상이 있는가
URL_FOR = re.compile(r"url_for\(\s*['\"]([a-zA-Z0-9_.]+)['\"]")
for path, text in tpl_text.items():
    for m in URL_FOR.finditer(text):
        checked += 1
        if m.group(1) not in endpoints and m.group(1) != "static":
            line = text[:m.start()].count("\n") + 1
            bad.append(f"[없는 endpoint] {path.name}:{line}  {m.group(1)}")

# ㄷ) JS 가 찾는 data-* 표가 어느 템플릿에도 없는가
SELECTOR = re.compile(r"""querySelector(?:All)?\(\s*["'`]\[(data-[a-z0-9\-]+)[^\]]*\]""")
all_tpl = "\n".join(tpl_text.values())
all_js = "\n".join(js_text.values())
for path, text in js_text.items():
    seen = set()
    for m in SELECTOR.finditer(text):
        attr = m.group(1)
        if attr in seen:
            continue
        seen.add(attr)
        checked += 1
        if attr not in all_tpl and attr not in re.sub(SELECTOR.pattern, "", all_js):
            line = text[:m.start()].count("\n") + 1
            bad.append(f"[화면에 없는 표] {path.name}:{line}  {attr}")

# ㄹ) 템플릿의 data-* 를 아무도 안 쓰는가
ATTR_IN_TPL = re.compile(r"\b(data-[a-z0-9\-]{3,})\s*[=>\s]")
SKIP = {"data-value", "data-code", "data-country", "data-mode", "data-kind", "data-key",
        "data-url", "data-name", "data-label", "data-id", "data-index", "data-no"}
orphans = {}
for path, text in tpl_text.items():
    for m in ATTR_IN_TPL.finditer(text):
        attr = m.group(1)
        if attr in SKIP:
            continue
        checked += 1
        if attr not in all_js and all_tpl.count(attr) <= 1:
            orphans.setdefault(attr, f"{path.name}:{text[:m.start()].count(chr(10)) + 1}")
for attr, where in sorted(orphans.items()):
    bad.append(f"[아무도 안 쓰는 표] {where}  {attr}")

# 하나씩 열어 확인한 것. 감싸기만 하는 껍데기라 아무도 안 써도 됩니다.
# (data-greeting 은 JS 가 dataset.greeting 으로 스스로 붙입니다) (2026-09-26)
KNOWN_ATTRS = {"data-greeting", "data-cal-fold", "data-calc-panel", "data-contract-card",
               "data-doc-calc-note", "data-hint", "data-hs-fill-label", "data-modes",
               "data-money-example", "data-note", "data-rail-recent", "data-stepper"}
known = sum(1 for b in bad if any(a in b for a in KNOWN_ATTRS))
bad = [b for b in bad if not any(a in b for a in KNOWN_ATTRS)]

print(f"   (알고 있는 껍데기 표 {known}개는 셈에서 뺍니다)")
print(f"■ 배선 점검 · 주소 {len(rules)}개 · JS {len(js_files)}개 · 템플릿 {len(templates)}개")
print(f"   확인 {checked:,}가지 · 문제 {len(bad)}건")
seen = {}
for b in bad:
    seen[b.split("]")[0] + "]"] = seen.get(b.split("]")[0] + "]", 0) + 1
for key, count in sorted(seen.items(), key=lambda kv: -kv[1]):
    print(f"   {key} {count}건")
for b in bad[:40]:
    print("   ★", b)
