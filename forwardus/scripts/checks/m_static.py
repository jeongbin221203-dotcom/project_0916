"""전체 코드 정적 점검 — 파이썬·템플릿·JS·지식글·자료파일을 모두 열어 봅니다."""
import sys, io, json, ast, re
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

bad, checked = [], 0

# ① 파이썬 파일이 모두 파싱되는가 · 들여쓰기·널바이트
py_files = sorted(Path("app").rglob("*.py")) + sorted(Path("tests").rglob("*.py")) \
         + sorted(Path("scripts").rglob("*.py")) + [Path("config.py"), Path("run.py")]
py_files = [p for p in py_files if p.exists() and "__pycache__" not in str(p)]
trees = {}
for path in py_files:
    checked += 1
    raw = path.read_bytes()
    if b"\x00" in raw:
        bad.append(f"[널바이트] {path}")
        continue
    try:
        trees[path] = ast.parse(raw.decode("utf-8"), filename=str(path))
    except SyntaxError as error:
        bad.append(f"[문법] {path}:{error.lineno} {error.msg}")
    except UnicodeDecodeError as error:
        bad.append(f"[글자] {path} {error}")
print(f"  파이썬 {len(py_files)}개 — 파싱 실패 {sum(1 for b in bad if b.startswith('[문법]'))}건")

# ② 모든 모듈이 import 되는가 (앱 컨텍스트 없이)
import importlib
fails = []
for path in sorted(trees):
    if not str(path).startswith("app"):
        continue
    name = str(path.with_suffix("")).replace("\\", "/").replace("/", ".").removesuffix(".__init__")
    checked += 1
    try:
        importlib.import_module(name)
    except Exception as error:
        fails.append(f"[import] {name}: {type(error).__name__} {error}")
bad += fails
print(f"  app 모듈 import — 실패 {len(fails)}건")

# ③ 위험한 흔적 — 디버그·비밀·임시
DANGER = [
    (re.compile(r"^\s*(breakpoint\(\)|import pdb|pdb\.set_trace)", re.M), "디버거"),
    (re.compile(r"\bTODO\s*:?\s*(제거|지우|삭제|remove|delete)", re.I), "지우라고 적어 둔 것"),
    (re.compile(r"debug\s*=\s*True", re.I), "debug=True"),
    (re.compile(r"verify\s*=\s*False"), "인증서 검증 끔"),
    (re.compile(r"except\s*:\s*(#.*)?$", re.M), "맨 except:"),
    (re.compile(r"eval\(|exec\("), "eval/exec"),
]
for path in sorted(trees):
    if str(path).startswith(("tests", "scripts")):
        continue
    text = path.read_text(encoding="utf-8")
    for pattern, label in DANGER:
        checked += 1
        for m in pattern.finditer(text):
            line = text[:m.start()].count("\n") + 1
            bad.append(f"[{label}] {path}:{line}  {m.group(0)[:60].strip()}")

# ④ 키·비밀이 코드에 박혀 있는가
SECRET = re.compile(r"(api[_-]?key|secret|password|token)\s*[=:]\s*[\"'][A-Za-z0-9_\-]{16,}[\"']", re.I)
for path in sorted(trees):
    text = path.read_text(encoding="utf-8")
    checked += 1
    for m in SECRET.finditer(text):
        line = text[:m.start()].count("\n") + 1
        bad.append(f"[박힌 비밀] {path}:{line}  {m.group(0)[:50]}")

# ⑤ 템플릿이 모두 파싱되는가
from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError
env = Environment(loader=FileSystemLoader("app/templates"), autoescape=True,
                  extensions=[])
templates = sorted(Path("app/templates").rglob("*.html"))
for path in templates:
    checked += 1
    name = str(path.relative_to("app/templates")).replace("\\", "/")
    try:
        env.parse(path.read_text(encoding="utf-8"), name=name)
    except TemplateSyntaxError as error:
        bad.append(f"[템플릿] {name}:{error.lineno} {error.message}")
print(f"  템플릿 {len(templates)}개 — 문법 실패 "
      f"{sum(1 for b in bad if b.startswith('[템플릿]'))}건")

# ⑥ JSON 자료가 모두 읽히는가
jsons = sorted(Path("data").rglob("*.json")) if Path("data").exists() else []
for path in jsons:
    checked += 1
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        bad.append(f"[JSON] {path}: {type(error).__name__} {error}")
print(f"  JSON 자료 {len(jsons)}개 — 읽기 실패 "
      f"{sum(1 for b in bad if b.startswith('[JSON]'))}건")

# ⑦ 지식 글의 앞머리(front-matter)가 온전한가
NEEDED = ("title", "keywords")
mds = sorted(Path("app/knowledge").glob("*.md"))
for path in mds:
    checked += 1
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        bad.append(f"[지식글] {path.name}: 앞머리가 없음")
        continue
    head = text.split("---", 2)[1]
    for key in NEEDED:
        if not re.search(rf"^{key}\s*:", head, re.M):
            bad.append(f"[지식글] {path.name}: '{key}' 가 없음")
    if len(text.split("---", 2)) < 3 or not text.split("---", 2)[2].strip():
        bad.append(f"[지식글] {path.name}: 본문이 비어 있음")
print(f"  지식 글 {len(mds)}개 — 문제 "
      f"{sum(1 for b in bad if b.startswith('[지식글]'))}건")

# ⑧ JS 가 짝이 맞는가 (괄호·따옴표는 node 가 봅니다. 여기선 흔적만)
js_files = sorted(Path("app/static/js").glob("*.js"))
for path in js_files:
    checked += 1
    text = path.read_text(encoding="utf-8")
    for pattern, label in [(re.compile(r"console\.log\("), "console.log"),
                           (re.compile(r"\bdebugger\b"), "debugger")]:
        for m in pattern.finditer(text):
            line = text[:m.start()].count("\n") + 1
            bad.append(f"[{label}] {path.name}:{line}")
print(f"  JS {len(js_files)}개")

print(f"\n■ 정적 점검 · 확인 {checked:,}가지 · 문제 {len(bad)}건")
seen = {}
for b in bad:
    seen[b.split("]")[0] + "]"] = seen.get(b.split("]")[0] + "]", 0) + 1
for key, count in sorted(seen.items(), key=lambda kv: -kv[1]):
    print(f"   {key} {count}건")
for b in bad[:40]:
    print("   ★", b)
