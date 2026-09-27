"""④ 서류 PDF 생성 — 흔들어 봅니다. 값 종류를 크게 늘렸습니다.

무엇을 보나
  ㄱ) 오류 없이 끝나는가 (죽으면 이용자는 서류를 못 받습니다)
  ㄴ) 정말 PDF 인가 (%PDF 머리 · %%EOF 꼬리 · 쪽 수)
  ㄷ) A4 한 장인가 (쪽이 늘거나 줄면 인쇄가 어긋납니다)
  ㄹ) 내용이 있는가 (흰 종이만 나오면 안 됩니다)
  ㅁ) 여러 장 묶기도 쪽 수가 맞는가
"""
import sys, io, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from PIL import Image
from tests._fuzz_app import build_app
from app.services import draft_document_service as D
from app.services import ServiceError
from app.validators import ValidationError

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 515)

VALUES = [
    "주식회사 한빛무역", "SAMPLE CO., LTD.", "上海远洋贸易有限公司",
    "株式会社ヤマト商事", "شركة الخليج للتجارة", "บริษัท ไทยเทรด จำกัด",
    "Công ty TNHH Thương mại", "İstanbul Dış Ticaret", "ООО Владивосток",
    "भारत व्यापार", "🚢 해상 ✈ 항공 📦",
    "가" * 600, "A" * 800, "가나다 " * 200,            # 칸을 넘치는 긴 글
    "줄바꿈\n두 번째 줄\n세 번째 줄", "탭\t사이", "  앞뒤 빈칸  ",
    "1,234,567.89", "0.001", "-99", "999999999999999",
    "<script>alert(1)</script>", "'; DROP TABLE x; --", "%s %d {0} {}",
    "​​", "＝ＡＢＣ１２３", "—–…·※№㈜℃㎏",
    "", "   ", None,
]
# 숫자 칸에는 숫자를 넣습니다. 글자를 넣으면 서버가 옳게 막아(확인함) PDF 까지
# 가지 못하므로, 여기서는 **PDF 그리기**를 흔드는 데 집중합니다.
WHOLE = ["1", "7", "100", "9999", "48", "365"]                 # 수량은 정수만
DECIMAL = ["0.5", "1234.56", "88888", "12.5", "0.01", "45000"]  # 단가·중량·금액
COUNTS = ("quantity", "qty", "packages", "pieces", "카톤")
NUMERIC = ("quantity", "unit_price", "amount", "weight", "cbm", "packages",
           "net", "gross", "price", "qty", "value")
KINDS = list(D.FORMS)


def cell(key):
    if any(word in key for word in COUNTS):
        return random.choice(WHOLE)
    if any(word in key for word in NUMERIC):
        return random.choice(DECIMAL)
    return random.choice(VALUES)


def money_row(row: dict) -> dict:
    """금액 = 단가 × 수량으로 맞춥니다.

    서버가 둘을 맞대어 보게 된 뒤로(2026-09-26), 무작위 금액은 옳게 막힙니다.
    여기서 보려는 것은 **PDF 그리기**라 입력에서 막히면 안 봐집니다.
    """
    from decimal import Decimal
    count = row.get("quantity")
    price = row.get("unit_price")
    if count and price:
        row = dict(row)
        row["amount"] = str((Decimal(str(price)) * Decimal(str(count)))
                            .quantize(Decimal("0.01")))
    return row
app = build_app()
bad, made, checked = [], 0, 0
with app.app_context():
    for turn in range(ROUNDS):
        kind = random.choice(KINDS)
        names = D.fields_for(kind)
        fields = {name: cell(name)
                  for name in random.sample(names, random.randint(0, len(names)))}
        rows = []
        for _ in range(random.randint(1, 25)):          # 한도(20)를 넘는 줄도 섞습니다
            rows.append(money_row({col["key"]: cell(col["key"])
                                   for col in D.item_columns(kind)
                                   if random.random() < 0.8}))
        draft = {"fields": fields, "items": rows}
        try:
            data = D.pdf_bytes(kind, draft)
        except (ValidationError, ServiceError) as error:
            bad.append(f"{turn} {kind}: 막힘 — {error}")
            continue
        except Exception as error:
            bad.append(f"{turn} {kind}: 죽음 {type(error).__name__} {error}")
            continue
        made += 1
        checked += 4
        if not data.startswith(b"%PDF-"):
            bad.append(f"{turn} {kind}: PDF 머리가 아님 {data[:8]!r}")
        if b"%%EOF" not in data[-2048:]:
            bad.append(f"{turn} {kind}: PDF 꼬리(%%EOF)가 없음")
        if len(data) < 5_000:
            bad.append(f"{turn} {kind}: 너무 작음 {len(data)} 바이트 — 흰 종이일 수 있음")
        pages = data.count(b"/Type /Page\n") + data.count(b"/Type /Page ")
        if pages != 1:
            bad.append(f"{turn} {kind}: 쪽이 {pages}장 (A4 한 장이어야 함)")

        # 흰 종이가 아닌지 — 그림으로 다시 열어 잉크를 셉니다 (100회마다)
        if turn % 50 == 0:
            checked += 1
            from app.processors import document_form
            rendered = D.render(kind, draft)
            page = document_form.draw_form(kind, rendered["data"], rendered["columns"])
            ink = sum(1 for px in page.convert("L").getdata() if px < 200)
            if ink < 2_000:
                bad.append(f"{turn} {kind}: 잉크가 {ink}점뿐 — 거의 흰 종이")
            if page.size != document_form.PAGE:
                bad.append(f"{turn} {kind}: 종이 크기가 {page.size} (A4 {document_form.PAGE} 아님)")

        # 여러 장 묶기
        if turn % 250 == 0:
            checked += 1
            picks = random.sample(KINDS, random.randint(1, len(KINDS)))
            try:
                merged = D.pdf_documents([{"kind": k, "data": D.render(k, draft)["data"]}
                                          for k in picks])
                count = merged.count(b"/Type /Page\n") + merged.count(b"/Type /Page ")
                if count != len(picks):
                    bad.append(f"{turn}: {len(picks)}장을 묶었는데 {count}쪽")
            except (ValidationError, ServiceError) as error:
                bad.append(f"{turn}: 묶기 막힘 — {error}")
            except Exception as error:
                bad.append(f"{turn}: 묶기 죽음 {type(error).__name__} {error}")

print(f"■ ④ PDF 생성 {ROUNDS:,}회 · 만든 건 {made:,} · 확인 {checked:,}가지 · 문제 {len(bad)}건")
seen = {}
for b in bad:
    key = b.split(": ", 1)[-1][:60]
    seen[key] = seen.get(key, 0) + 1
for key, count in sorted(seen.items(), key=lambda kv: -kv[1])[:12]:
    print(f"   ★ {count:>5}회  {key}")
