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

    text = str(value or "").strip()
    if not text:
        draw.text((x + 9, y + 28), "—", font=fonts["body"], fill=MUTED)
        return
    # 아직 안 정해진 칸은 눈에 띄게 둡니다. 비워 두면 안 적은 것과 구별이 안 됩니다.
    color = MUTED if text.startswith("미정") else INK
    top = y + 26
    for line in _wrap(draw, text, fonts["body"], w - 18):
        if top + 18 > y + h - 4:
            break
        draw.text((x + 9, top), line, font=fonts["body"], fill=color)
        top += 19


def _rows(draw, rows, top: int, width: int, data: dict, fonts, height: int) -> int:
    for row in rows:
        left = MARGIN
        for names, label, share in row:
            cell_w = int(width * share)
            value = "\n".join(
                str(data.get(name, "") or "").strip()
                for name in names.split("+") if str(data.get(name, "") or "").strip())
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
            text = f"{value:,}" if isinstance(value, (int, float)) else str(value or "")
            for index, line in enumerate(_wrap(draw, text, fonts["body"], share - 16)[:2]):
                draw.text((left + 8, top + 8 + index * 17), line, font=fonts["body"], fill=INK)
            left += share
        top += row_h
    return top


def draw_form(kind: str, data: dict, columns: list[dict]) -> Image.Image:
    """서식 한 장을 그립니다."""

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
    note = "ForwardUs 초안 · 아직 확정된 서류가 아닙니다"
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
