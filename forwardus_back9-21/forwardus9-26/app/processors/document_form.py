"""서류 초안을 그림 한 장으로 그립니다.

Pillow만 씁니다. 새 라이브러리를 넣지 않았고 바깥을 부르지도 않습니다.
같은 그림을 PNG로도 PDF로도 내보냅니다.

왜 그림으로 그리나
    대화 중에 "이렇게 나옵니다"를 바로 보여 주려면 화면에 붙일 그림이 필요합니다.
    글자가 살아 있는 PDF가 필요하면 서류 화면의 "인쇄 / PDF 저장"을 쓰세요.
    그쪽은 브라우저가 벡터로 뽑아 줍니다. 여기서 만드는 PDF는 그림입니다.

서식은 LAYOUTS에 칸의 자리로 적어 둡니다. 첨부해 주신 양식의 번호(①②③…)를
그대로 달아서, 종이와 화면을 나란히 놓고 볼 수 있게 했습니다.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# A4 비율. 150dpi면 인쇄해도 글자가 깨지지 않고 파일도 무겁지 않습니다.
PAGE = (1240, 1754)
MARGIN = 60

INK = (15, 23, 42)
LINE = (120, 132, 150)
LABEL = (90, 102, 122)
MUTED = (150, 160, 175)
WHITE = (255, 255, 255)

# 미리보기에서만 쓰는 표시. 값 앞에 붙이면 그 칸을 다르게 그립니다.
# PDF를 만들 때는 붙이지 않으므로 내려받은 서류에는 나오지 않습니다.
#   MASKED  은행·바이어 정보. 글자를 하나도 보이지 않게 덮습니다.
#   HINT    빈 칸. 어디서 채우면 되는지 빨간 글씨로 적습니다.
MASKED = "\x00mask"
HINT = "\x00hint:"
# 빈 서식: 칸만 그리고 "—"도 찍지 않습니다. (손으로 적을 자리)
BLANK = "\x00blank"
HINT_COLOR = (200, 45, 45)
MASK_FILL = (214, 220, 229)

# 돈 칸. 64.0이 아니라 64.00으로 적습니다. 단가는 넷째 자리까지 있을 수 있습니다.
MONEY_KEYS = {"invoice_value", "unit_price", "amount"}


def money_text(value) -> str:
    """6400.0 → '6,400.00', 0.8525 → '0.8525'. 숫자가 아니면 그대로."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value or "")
    text = f"{value:,.4f}".rstrip("0")
    whole, _, cents = text.partition(".")
    return f"{whole}.{cents.ljust(2, '0')}"

# 한글이 나오는 글꼴을 찾습니다. 없으면 기본 글꼴로 내려갑니다.
# (배포 환경에는 맑은 고딕이 없을 수 있습니다)
FONT_CANDIDATES = (
    "C:/Windows/Fonts/malgun.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
)
BOLD_CANDIDATES = ("C:/Windows/Fonts/malgunbd.ttf",
                   "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf")


def _font(size: int, bold: bool = False):
    for path in (BOLD_CANDIDATES if bold else ()) + FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def fonts_ready() -> bool:
    """한글 글꼴을 찾았는지. 못 찾으면 화면에서 알려 줍니다."""

    return any(Path(path).exists() for path in FONT_CANDIDATES)


# --- 서식 ------------------------------------------------------------------------
# 한 줄은 (칸 이름, 서식의 라벨, 가로 몫). 가로 몫을 합쳐 1이 한 줄입니다.
# 값이 여러 개인 칸은 이름을 "+"로 이어 붙입니다. (예: "exporter+exporter_address")

# 서식의 번호. 맑은 고딕에는 동그라미 숫자가 ⑮까지만 있고 ⑯부터는 없습니다.
# 그대로 쓰면 네모(□)로 찍힙니다. 첨부해 주신 PACKING LIST 원본도 ⑯ 자리가
# 깨져 있었는데 같은 이유입니다. 없는 번호는 (16)처럼 적습니다.
CIRCLED = {index: chr(0x245F + index) for index in range(1, 16)}


def no(index: int, text: str) -> str:
    """서식 번호를 붙인 라벨. 글꼴에 없는 번호는 괄호로 적습니다."""

    return f"{CIRCLED.get(index, f'({index})')} {text}"

LAYOUTS = {
    "commercial_invoice": {
        "title": "COMMERCIAL INVOICE",
        "rows": [
            [("exporter+exporter_address", no(1, "Seller"), 0.5),
             ("doc_no+doc_date", no(7, "Invoice No. and date"), 0.5)],
            [("consignee+consignee_address", no(4, "Consignee"), 0.5),
             ("buyer", no(9, "Buyer (if other than consignee)"), 0.5)],
            [("lc_no", no(8, "L/C No. and date"), 0.5),
             ("other_references", no(10, "Other references"), 0.5)],
            [("etd", no(5, "Departure date"), 0.34),
             ("vessel_or_flight", no(6, "Vessel / flight"), 0.33),
             ("carrier", "Carrier", 0.33)],
            [("pol", no(2, "From"), 0.34), ("pod", no(3, "To"), 0.33),
             ("incoterms", no(16, "Terms of delivery"), 0.33)],
            [("payment_terms", no(17, "Terms of payment"), 1.0)],
        ],
        "table": True,
        "footer": [
            [("invoice_value+currency", no(15, "Invoice value"), 0.34),
             ("gross_weight_kg", "Gross weight (kg)", 0.33),
             ("net_weight_kg", "Net weight (kg)", 0.33)],
            [("shipping_marks", no(11, "Shipping marks"), 0.5),
             ("remarks", "Remarks", 0.5)],
            [("signed_by", no(18, "Signed by"), 1.0)],
        ],
    },
    "packing_list_std": {
        "title": "PACKING LIST",
        "rows": [
            [("exporter+exporter_address", no(1, "Seller"), 0.5),
             ("invoice_no+doc_date", no(7, "Invoice No. and date"), 0.5)],
            [("consignee+consignee_address", no(2, "Consignee"), 0.5),
             ("buyer", no(8, "Buyer (if other than consignee)"), 0.5)],
            [("etd", no(3, "Departure date"), 0.5),
             ("other_references", no(9, "Other references"), 0.5)],
            [("vessel_or_flight", no(4, "Vessel / flight"), 0.34),
             ("pol", no(5, "From"), 0.33), ("pod", no(6, "To"), 0.33)],
        ],
        "table": True,
        "footer": [[("signed_by", no(16, "Signed by"), 1.0)]],
    },
    "packing_list": {
        "title": "PACKING LIST",
        "rows": [
            [("order_no", "ORDER #", 0.5), ("doc_date", "DATE", 0.5)],
            [("consignee+consignee_address+consignee_city_zip", "SHIPPED TO", 0.5),
             ("attention", "ATTENTION", 0.5)],
            [("date_ordered", "DATE ORDERED", 0.34),
             ("customer_order_no", "CUSTOMER ORDER NUMBER", 0.33),
             ("date_shipped", "DATE SHIPPED", 0.33)],
            [("shipped_via", "SHIPPED VIA", 0.34),
             ("container_no", "CONTAINER NUMBER", 0.33),
             ("invoice_no", "OUR INVOICE NUMBER", 0.33)],
        ],
        "table": True,
        "footer": [
            [("net_weight_kg", "NET WEIGHT (KG)", 0.34),
             ("gross_weight_kg", "GROSS WEIGHT (KG)", 0.33),
             ("total_cbm", "MEASUREMENT (CBM)", 0.33)],
            [("comments", "COMMENTS", 0.5), ("packed_by", "PACKED BY", 0.5)],
        ],
    },
    # 선적의뢰서 (Shipping Request / S·I). 포워더·선사에 B/L 내용을 알려 주는 서식입니다.
    # 칸 구성은 document_service.DOCUMENT_SECTIONS["shipping_instruction"]과 같습니다.
    "shipping_instruction": {
        "title": "SHIPPING REQUEST",
        "rows": [
            [("exporter+exporter_address", "Shipper", 0.5),
             ("booking_no+doc_no+doc_date", "Booking No. · S/R No. · Date", 0.5)],
            [("consignee+consignee_address", "Consignee", 0.5),
             ("notify_party", "Notify Party", 0.5)],
            [("pol", "Port of Loading", 0.25), ("pod", "Port of Discharge", 0.25),
             ("vessel_or_flight", "Vessel / Voyage", 0.25), ("etd", "ETD", 0.25)],
            [("carrier", "Carrier", 0.34), ("freight_term", "Freight", 0.33),
             ("incoterms", "Terms of delivery", 0.33)],
        ],
        "table": True,
        "footer": [
            [("gross_weight_kg", "Total gross weight (kg)", 0.34),
             ("total_cbm", "Total measurement (CBM)", 0.33),
             ("container_seal_no", "Container No. / Seal No.", 0.33)],
            [("shipping_marks", "Shipping marks", 0.5),
             ("dangerous_goods", "Dangerous goods", 0.5)],
            [("remarks", "Remarks", 0.5), ("signed_by", "Signed by", 0.5)],
        ],
    },
    "proforma_invoice": {
        "title": "PROFORMA INVOICE",
        "rows": [
            [("exporter+exporter_address", no(2, "Exporter / Beneficiary / Seller"), 0.4),
             ("consignee+consignee_address", no(3, "Consignee / Buyer"), 0.3),
             ("doc_no+doc_date+validity_date+po_no",
              no(4, "P/I No. & Date") + " · " + no(5, "Validity") + " · " + no(6, "P/O"), 0.3)],
            [("pol", no(7, "Port of Loading"), 0.25),
             ("pod", no(8, "Port of Discharge"), 0.25),
             ("final_destination", no(9, "Final destination"), 0.25),
             ("incoterms", no(10, "Terms of Price"), 0.25)],
            [("carriage_by", no(11, "Carriage By"), 0.25),
             ("country_of_origin", no(12, "Country of Origin"), 0.25),
             ("shipment_time", no(13, "Shipment"), 0.5)],
        ],
        "table": True,
        "footer": [
            [("invoice_value+currency", no(19, "Total"), 1.0)],
            [("shipping_marks", no(20, "Shipping Marks"), 1.0)],
            [("payment_terms", no(21, "Payment Term"), 1.0)],
            [("bank_info", no(22, "Seller's Bank Information"), 1.0)],
            [("remarks", no(23, "Remarks"), 1.0)],
            [("accepted_by", no(24, "Accepted by (Buyer)"), 0.5),
             ("signed_by", no(25, "(Seller)"), 0.5)],
        ],
    },
}


def available(kind: str) -> bool:
    return kind in LAYOUTS


# --- 그리기 ----------------------------------------------------------------------

def _wrap(draw, text: str, font, width: int) -> list[str]:
    """칸 너비에 맞춰 줄을 나눕니다. 한글은 띄어쓰기가 드물어 글자 단위로도 자릅니다."""

    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        current = ""
        for word in paragraph.split(" "):
            trial = f"{current} {word}".strip()
            if current and draw.textlength(trial, font=font) > width:
                lines.append(current)
                current = word
            else:
                current = trial
            # 한 낱말이 칸보다 길면 글자 단위로 끊습니다.
            while draw.textlength(current, font=font) > width and len(current) > 1:
                cut = len(current)
                while cut > 1 and draw.textlength(current[:cut], font=font) > width:
                    cut -= 1
                lines.append(current[:cut])
                current = current[cut:]
        lines.append(current)
    return [line for line in lines if line != ""] or [""]


def _cell(draw, box, label: str, value: str, fonts) -> None:
    """칸 하나. 테두리 + 작은 라벨 + 값."""

    x, y, w, h = box
    draw.rectangle([x, y, x + w, y + h], outline=LINE, width=1)
    draw.text((x + 9, y + 7), label, font=fonts["label"], fill=LABEL)

    # 두 값을 이어 붙이는 칸(Seller = 상호 + 주소)도 있어 들어 있는지로 봅니다.
    if BLANK in str(value or "") and not str(value).replace(BLANK, "").strip():
        return
    text = str(value or "").strip()
    if not text:
        draw.text((x + 9, y + 28), "—", font=fonts["body"], fill=MUTED)
        return
    # 가린 칸은 글자를 하나도 그리지 않습니다. 끝자리만 보이는 식도 아닙니다.
    if MASKED in text:
        draw.rectangle([x + 9, y + 27, x + w - 9, y + min(h - 8, 27 + 40)], fill=MASK_FILL)
        draw.text((x + 15, y + 33), "화면에서 가림 · PDF에는 들어갑니다",
                  font=fonts["label"], fill=LABEL)
        return
    top = y + 26
    for part in text.split("\n"):
        # 아직 안 정해진 칸은 눈에 띄게 둡니다. 비워 두면 안 적은 것과 구별이 안 됩니다.
        color = MUTED if part.startswith("미정") else INK
        if part.startswith(HINT):
            part, color = part[len(HINT):], HINT_COLOR
        for line in _wrap(draw, part, fonts["body"], w - 18):
            if top + 18 > y + h - 4:
                break
            draw.text((x + 9, top), line, font=fonts["body"], fill=color)
            top += 19


def _rows(draw, rows, top: int, width: int, data: dict, fonts, height: int) -> int:
    for row in rows:
        left = MARGIN
        for names, label, share in row:
            cell_w = int(width * share)
            parts = [(money_text(data.get(name)) if name in MONEY_KEYS
                      else str(data.get(name, "") or "")).strip()
                     for name in names.split("+") if str(data.get(name, "") or "").strip()]
            # 칸이 넘치면 아랫줄이 잘립니다. 적힌 값이 안내에 밀려 잘리지 않게
            # 실제 값을 먼저, "어디서 채우세요" 안내를 뒤로 보냅니다.
            parts.sort(key=lambda part: part.startswith(HINT))
            value = "\n".join(parts)
            _cell(draw, (left, top, cell_w, height), label, value, fonts)
            left += cell_w
        top += height
    return top


def _table(draw, columns, items, top: int, width: int, fonts) -> int:
    """품목 표. 줄 수만큼 늘어납니다."""

    head = 34
    left = MARGIN
    share = width // max(1, len(columns))
    draw.rectangle([MARGIN, top, MARGIN + width, top + head], outline=LINE,
                   width=1, fill=(244, 247, 251))
    for column in columns:
        draw.text((left + 8, top + 10), column["label"], font=fonts["label"], fill=LABEL)
        draw.line([left, top, left, top + head], fill=LINE, width=1)
        left += share
    top += head

    for item in items or [{}]:
        left = MARGIN
        row_h = 40
        for column in columns:
            draw.rectangle([left, top, left + share, top + row_h], outline=LINE, width=1)
            value = item.get(column["key"], "")
            if column["key"] in MONEY_KEYS:
                text = money_text(value)
            else:
                text = f"{value:,}" if isinstance(value, (int, float)) else str(value or "")
            color = INK
            if text.startswith(HINT):
                text, color = text[len(HINT):], HINT_COLOR
            for index, line in enumerate(_wrap(draw, text, fonts["body"], share - 16)[:2]):
                draw.text((left + 8, top + 8 + index * 17), line, font=fonts["body"], fill=color)
            left += share
        top += row_h
    return top


DRAFT_NOTE = "ForwardUs 초안 · 아직 확정된 서류가 아닙니다"


def draw_form(kind: str, data: dict, columns: list[dict], note: str = DRAFT_NOTE) -> Image.Image:
    """서식 한 장을 그립니다. note는 맨 아래 작은 글씨입니다. (초안 / 빈 서식)"""

    layout = LAYOUTS[kind]
    fonts = {"title": _font(30, bold=True), "label": _font(13),
             "body": _font(16), "small": _font(12)}

    page = Image.new("RGB", PAGE, WHITE)
    draw = ImageDraw.Draw(page)
    width = PAGE[0] - MARGIN * 2

    title = layout["title"]
    draw.text(((PAGE[0] - draw.textlength(title, font=fonts["title"])) / 2, 46),
              title, font=fonts["title"], fill=INK)

    top = _rows(draw, layout["rows"], 108, width, data, fonts, height=92)
    if layout.get("table"):
        top = _table(draw, columns, data.get("items") or [], top + 10, width, fonts) + 10
    top = _rows(draw, layout.get("footer", []), top, width, data, fonts, height=76)

    # 내용 바로 아래에 답니다. 페이지 맨 밑에 두면 빈 자리를 잘라낼 수 없습니다.
    draw.text((MARGIN, min(top + 16, PAGE[1] - 30)), note, font=fonts["small"], fill=MUTED)
    return page


def crop_to_content(image: Image.Image, pad: int = 28) -> Image.Image:
    """빈 아래쪽을 잘라냅니다. 대화창에 붙일 때 씁니다.

    종이는 A4라 내용이 짧으면 아래가 많이 빕니다. 인쇄할 PDF는 A4 그대로
    두어야 하지만, 화면에 보여 줄 때는 빈 자리가 길면 보기 어렵습니다.
    """

    grey = image.convert("L")
    box = grey.point(lambda v: 255 if v < 250 else 0).getbbox()
    if not box:
        return image
    bottom = min(image.height, box[3] + pad)
    return image.crop((0, 0, image.width, bottom))


def as_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


def as_pdf(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "PDF", resolution=150.0)
    return buffer.getvalue()


def as_pdf_pages(images: list[Image.Image]) -> bytes:
    """여러 서류를 한 파일로. 서류 한 장이 A4 한 쪽입니다."""

    buffer = io.BytesIO()
    first, rest = images[0], images[1:]
    first.save(buffer, "PDF", resolution=150.0, save_all=True, append_images=rest)
    return buffer.getvalue()
