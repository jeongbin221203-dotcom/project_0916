"""올린 무역 서류(B/L, Offer Sheet, 견적서, Packing List…)를 읽어 서류 작성 칸을 채웁니다.

사람이 이미 받아 둔 서류가 있으면 같은 값을 다시 칠 이유가 없습니다.
PDF나 사진을 올리면 AI가 읽어 정해진 모양의 JSON으로 돌려주고, 그 값을
서류 작성 화면(/documents/new)의 칸 이름으로 옮겨 줍니다.

intake_service와 같은 원칙을 지킵니다.

**AI가 읽은 값을 그대로 믿지 않습니다.**
항구는 우리 목록에서 다시 찾고, Incoterms·통화·포장 종류는 우리가 아는
값인지 보고, 숫자는 우리 검증기로 다시 읽습니다. 확인되지 않은 값은 칸에
넣지 않고 "확인하지 못했다"고 적어 둡니다. 비어 있는 칸이 틀린 칸보다 낫습니다.

**여기서 Shipment를 만들지 않습니다.**
칸을 채울 뿐이고, 확인하고 "서류 만들기"를 누르는 것은 사람입니다.

**올린 파일은 남기지 않습니다.**
읽는 동안만 메모리에 두고 버립니다. 서버에 쌓아 둘 이유가 없습니다.
"""

from __future__ import annotations

import base64
import io
import re

from app.collectors import ai_client
from app.collectors.base_client import get_config
from app.processors import bank_redaction
from app.services import ServiceError, document_start_service
from app.services.intake_service import (INCOTERMS, PACKAGE_TYPES, _amount, _currencies,
                                         _date, _pick, _place)
from app.validators.shipment_validator import optional_text

ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PDF_TEXT_PAGES = 5
# 그림으로 보내는 장 수. B/L·Offer Sheet는 한두 장이고, 장마다 토큰이 듭니다.
MAX_IMAGE_PAGES = 3
MAX_TEXT_CHARS = 12_000
# 긴 변 기준. 이보다 크면 줄입니다. 글자는 이 정도면 충분히 읽힙니다.
MAX_IMAGE_EDGE = 2000
MAX_ITEMS = document_start_service.MAX_ITEMS
AI_TIMEOUT_SECONDS = 90

DOCUMENT_LABELS = {
    "bill_of_lading": "선하증권 (B/L)",
    "air_waybill": "항공화물운송장 (AWB)",
    "offer_sheet": "Offer Sheet",
    "quotation": "견적서",
    "proforma_invoice": "Proforma Invoice",
    "commercial_invoice": "상업송장 (Commercial Invoice)",
    "packing_list": "포장명세서 (Packing List)",
    "other": "기타 무역 서류",
}

# 서류에 찍힌 포장 단위 → 우리 포장 종류. AI의 판단보다 이 표를 먼저 봅니다.
PACKAGE_UNIT_WORDS = {
    "carton": ("CT", "CTN", "CTNS", "CARTON", "CARTONS", "BOX", "BOXES", "BX", "C/T"),
    "pallet": ("PLT", "PLTS", "PALLET", "PALLETS", "PL", "SKID", "SKIDS"),
    "wooden_crate": ("CRT", "CRATE", "CRATES", "WOODEN CASE", "WOODEN CASES", "W/C", "CASE", "CASES"),
    "drum": ("DRM", "DRUM", "DRUMS", "DR"),
    "flexible_bag": ("BAG", "BAGS", "JUMBO BAG", "JUMBO BAGS", "FIBC", "TON BAG", "TON BAGS"),
    "bulk": ("BULK", "IN BULK"),
}
_UNIT_LOOKUP = {word: kind for kind, words in PACKAGE_UNIT_WORDS.items() for word in words}

_STR = {"type": ["string", "null"]}
_NUM = {"type": ["number", "null"]}


def _object(properties: dict) -> dict:
    """strict 모드는 모든 키를 required로, 나머지 키는 막아야 합니다."""

    return {"type": "object", "additionalProperties": False,
            "properties": properties, "required": list(properties)}


_PARTY = _object({"name": _STR, "address": _STR, "country": _STR})

EXTRACT_SCHEMA = _object({
    "document_type": {"type": "string", "enum": list(DOCUMENT_LABELS)},
    "shipper": _PARTY,
    "consignee": _PARTY,
    "notify_party": _PARTY,
    "transport_mode": {"type": ["string", "null"], "enum": ["SEA", "AIR", None]},
    "incoterms": _STR,
    "incoterms_place": _STR,
    "currency": _STR,
    "total_amount": _NUM,
    "payment_terms": _STR,
    "port_of_loading": _STR,
    "port_of_discharge": _STR,
    "vessel_name": _STR,
    "voyage_no": _STR,
    "bl_no": _STR,
    "container_no": _STR,
    "shipping_marks": _STR,
    "shipment_date": _STR,
    "items": {"type": "array", "items": _object({
        "product_description": _STR,
        "hs_code": _STR,
        "package_count": _NUM,
        "package_unit": _STR,
        "package_type": {"type": ["string", "null"], "enum": sorted(PACKAGE_TYPES) + [None]},
        "gross_weight_kg": _NUM,
        "net_weight_kg": _NUM,
        "measurement_cbm": _NUM,
        "length_cm": _NUM,
        "width_cm": _NUM,
        "height_cm": _NUM,
        "unit_price": _NUM,
        "amount": _NUM,
    })},
    "unreadable": {"type": "array", "items": {"type": "string"}},
})

EXTRACT_PROMPT = """당신은 한국 수출기업의 무역 서류를 읽어 값을 옮겨 적는 사람입니다.
사용자가 올린 서류(B/L, AWB, Offer Sheet, 견적서, Proforma/Commercial Invoice,
Packing List 중 하나)의 그림과, 읽을 수 있으면 본문 글자를 받습니다.

지켜야 할 것
- 서류에 **적혀 있는 것만** 옮깁니다. 안 보이거나 확실하지 않으면 null입니다. 짐작하지 마세요.
- 관세율·운임·환율·무게를 기억에서 꺼내 채우지 마세요.
- 숫자는 단위와 천 단위 쉼표를 떼고 숫자만 적습니다. ("1,200.50 KGS" -> 1200.5)
- 무게는 kg으로 적습니다. 서류가 LBS면 kg으로 바꾸지 말고 null로 두고 unreadable에 적으세요.
- 날짜는 YYYY-MM-DD로 적습니다.
- 칸 이름이 다르게 찍혀 있어도 뜻으로 찾으세요.
  Shipper = Exporter = Seller = Beneficiary
  Consignee = Buyer = Messrs = Applicant(L/C) = Importer
  Port of Loading = POL = From,  Port of Discharge = POD = To = Destination
- 필드 설명
  document_type    서류 종류
  shipper/consignee/notify_party  name은 회사명, address는 주소, country는 두 글자 국가 코드(US, CN…)
                   Notify가 "SAME AS CONSIGNEE"이면 name에 그 글자를 그대로 적으세요.
  transport_mode   배(B/L, 선박명)면 SEA, 항공(AWB, 편명)이면 AIR, 모르면 null
  incoterms        EXW FCA FAS FOB CFR CIF CPT CIP DAP DPU DDP 중 하나. "FOB BUSAN"이면 incoterms=FOB, incoterms_place=BUSAN
  currency         USD KRW EUR JPY CNY 같은 세 글자 통화 코드
  total_amount     서류 전체 합계 금액
  payment_terms    물품 대금의 결제 조건 (T/T 30 days, L/C at sight 같은 것).
                   B/L의 "FREIGHT PREPAID/COLLECT"는 운임 지급 조건이라 여기에 넣지 않습니다.
  shipment_date    선적(예정)일. B/L이면 On Board Date
  items            품목 줄마다 하나. 합계 줄(TOTAL)은 품목이 아닙니다.
      package_count  포장 개수 (예: 500 CTNS -> 500)
      package_unit   서류에 찍힌 포장 단위 글자 그대로 (CTNS, PLTS…)
      package_type   carton pallet wooden_crate drum flexible_bag uld bulk 중 하나, 모르면 null
      gross_weight_kg / net_weight_kg  그 줄 전체의 총중량 / 순중량
      measurement_cbm  그 줄 전체의 용적 (CBM)
      length_cm width_cm height_cm  한 포장의 치수가 cm로 적혀 있을 때만
      unit_price / amount  단가 / 그 줄 금액
  unreadable       흐리거나 잘려서 읽지 못한 칸을 한국어로 짧게 (없으면 빈 목록)"""


def available() -> bool:
    return ai_client.available()


# --- 파일 읽기 ---------------------------------------------------------------------

def _suffix(filename: str) -> str:
    match = re.search(r"(\.[A-Za-z0-9]+)$", filename or "")
    return match.group(1).lower() if match else ""


def _jpeg_data_url(image) -> str:
    """그림을 JPEG data URL로. 크면 줄이고, 투명·팔레트 그림은 RGB로 바꿉니다.

    다시 그려서 보내는 것이라 파일에 숨어 있던 것(메타데이터 등)은 따라가지 않습니다.
    """

    if max(image.size) > MAX_IMAGE_EDGE:
        image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
    if image.mode != "RGB":
        image = image.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _read_pdf(data: bytes) -> tuple[str, list]:
    """PDF에서 글자와 앞 몇 장의 그림을 꺼냅니다.

    글자가 있어도 그림을 같이 보냅니다. B/L은 칸 배치로 Shipper와 Consignee를
    가르는데, 글자만 뽑으면 그 배치가 사라져 누가 누구인지 섞입니다.
    그림은 계좌번호를 칠한 뒤에 보내므로 여기서는 PIL 그림으로 돌려줍니다.
    """

    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if not pdf.pages:
                raise ServiceError("빈 PDF입니다. 내용이 있는 파일을 올려 주세요.", "VALIDATION_ERROR")
            text = "\n".join((page.extract_text() or "") for page in pdf.pages[:MAX_PDF_TEXT_PAGES])
            images = [page.to_image(resolution=150).original.copy()
                      for page in pdf.pages[:MAX_IMAGE_PAGES]]
    except ServiceError:
        raise
    except Exception:
        # 암호가 걸렸거나 깨진 PDF. 어느 쪽이든 사람이 할 수 있는 일은 같습니다.
        raise ServiceError("PDF를 열지 못했습니다. 암호가 걸려 있거나 파일이 손상되었을 수 "
                           "있습니다. 다시 저장해 올리거나 사진으로 찍어 올려 주세요.",
                           "VALIDATION_ERROR")
    return text.strip(), images


def _read_image(data: bytes) -> list:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            return [image.copy()]
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ServiceError("그림 파일을 열지 못했습니다. PNG나 JPG로 다시 저장해 올려 주세요.",
                           "VALIDATION_ERROR")


def read_upload(filename: str, data: bytes) -> tuple[str, list]:
    """올린 파일에서 (본문 글자, PIL 그림 목록)을 꺼냅니다. 아직 아무것도 가리지 않은 상태입니다."""

    suffix = _suffix(filename)
    if suffix not in ALLOWED_SUFFIXES:
        raise ServiceError("PDF 또는 이미지(PNG·JPG·WEBP) 파일만 올릴 수 있습니다.",
                           "VALIDATION_ERROR")
    if not data:
        raise ServiceError("빈 파일입니다. 내용이 있는 파일을 올려 주세요.", "VALIDATION_ERROR")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ServiceError(f"파일은 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB까지 올릴 수 있습니다.",
                           "VALIDATION_ERROR")
    if suffix == ".pdf":
        return _read_pdf(data)
    return "", _read_image(data)


# --- 계좌번호 가리기 ---------------------------------------------------------------
# 은행 계좌·SWIFT·IBAN은 OpenAI로 보내지 않습니다. 글자는 [ACCOUNT_1] 같은 표시로
# 바꾸고, 그림은 우리 컴퓨터의 OCR로 번호를 칠한 뒤에만 보냅니다.
# 가린 번호는 되살리지 않습니다. 은행 정보는 이용자가 서류 작성 화면에서 직접 적습니다.

def _png_bytes(image) -> bytes:
    if image.mode != "RGB":
        image = image.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _protect(text: str, images: list) -> tuple[str, list[str], list[str]]:
    """보낼 글자와 그림에서 은행 번호를 가립니다. (가린 글, 보낼 그림 data URL, 알림)"""

    from PIL import Image

    notes: list[str] = []
    text, secrets = bank_redaction.redact(text)
    hidden = len(secrets)
    urls: list[str] = []
    if images and bank_redaction.ocr_available():
        for image in images:
            # OCR이 읽기 좋은 크기로 맞춘 뒤 칠합니다. 칠한 그림만 바깥으로 나갑니다.
            if max(image.size) > MAX_IMAGE_EDGE:
                image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
            masked = bank_redaction.redact_image(_png_bytes(image))
            hidden += masked["found"]
            with Image.open(io.BytesIO(masked["image"])) as clean:
                urls.append(_jpeg_data_url(clean.copy()))
    elif images and text.strip():
        # 칠할 도구가 없으면 그림은 보내지 않고, 가린 글자만 보냅니다.
        notes.append("계좌번호를 가릴 도구(OCR)가 없어 서류 그림은 보내지 않고 글자만 읽었습니다. "
                     "Shipper·Consignee가 바뀌어 들어가지 않았는지 확인해 주세요.")
    elif images:
        raise ServiceError("사진·스캔 서류 속 계좌번호를 가리는 도구(OCR)가 설치되어 있지 않아 "
                           "받을 수 없습니다. 글자가 있는 PDF로 올리거나 칸을 직접 채워 주세요.",
                           "OCR_UNAVAILABLE")
    if hidden:
        notes.append(f"계좌번호·SWIFT {hidden}개를 가린 뒤 AI에 보냈습니다. "
                     "은행 정보는 서류 작성 화면에서 직접 적어 주세요.")
    return text, urls, notes


def _scrub(value):
    """AI가 돌려준 값에 섞인 가림 표시·계좌번호를 [계좌번호]로 지웁니다. 되살리지 않습니다."""

    if isinstance(value, str):
        return bank_redaction.strip_bank_numbers(value)[0]
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items()}
    return value


# --- AI에게 읽히기 -----------------------------------------------------------------

def _ask_ai(text: str, images: list[str]) -> dict:
    content: list[dict] = [{"type": "text", "text": (
        "서류 본문에서 뽑은 글자입니다. 그림과 함께 보고 옮겨 주세요.\n\n" + text[:MAX_TEXT_CHARS]
        if text else "서류 그림입니다. 글자를 읽어 옮겨 주세요.")}]
    content += [{"type": "image_url", "image_url": {"url": url, "detail": "high"}}
                for url in images]
    result = ai_client.structured_chat(
        [{"role": "system", "content": EXTRACT_PROMPT}, {"role": "user", "content": content}],
        EXTRACT_SCHEMA, name="trade_document_extract", max_tokens=3000,
        model=get_config("AI_DOC_MODEL", ai_client.MODEL), timeout=AI_TIMEOUT_SECONDS)
    if not result["success"]:
        # structured_chat의 문구는 HS 검색용이라 여기서 다시 씁니다.
        if result.get("error_code") == "API_TIMEOUT":
            raise ServiceError("서류를 읽는 데 시간이 너무 걸렸습니다. 장 수를 줄이거나 "
                               "첫 장만 올려 다시 시도해 주세요.", "API_TIMEOUT", 502)
        raise ServiceError("AI가 서류를 읽지 못했습니다. 잠시 뒤 다시 올리거나, 더 선명한 "
                           "파일로 올려 주세요.", result.get("error_code") or "API_ERROR", 502)
    return result["data"]


# --- 우리 칸으로 옮기기 ---------------------------------------------------------------

def _clean(value, limit: int = 300) -> str:
    return optional_text(value, max_length=limit) if isinstance(value, str) else ""


def _party(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    country = _clean(raw.get("country"), 2).upper()
    return {"name": _clean(raw.get("name"), 200), "address": _clean(raw.get("address"), 500),
            "country": country if re.fullmatch(r"[A-Z]{2}", country) else ""}


def _package_type(raw: dict) -> str:
    """서류에 찍힌 단위 글자를 먼저 보고, 없을 때만 AI의 판단을 씁니다."""

    unit = re.sub(r"[\s.]+", " ", str(raw.get("package_unit") or "")).strip().upper()
    if unit in _UNIT_LOOKUP:
        return _UNIT_LOOKUP[unit]
    return _pick(raw.get("package_type"), PACKAGE_TYPES, upper=False)


def _item(raw, notes: list, no: int) -> dict:
    if not isinstance(raw, dict):
        return {}
    label = f"품목 {no}"
    line = {
        "product_description": _clean(raw.get("product_description")),
        "hs_code": "".join(ch for ch in str(raw.get("hs_code") or "") if ch.isdigit())[:10],
        "package_type": _package_type(raw),
        "quantity": _amount(raw.get("package_count"), f"{label} 포장 개수", notes),
        "net_weight_kg": _amount(raw.get("net_weight_kg"), f"{label} 순중량", notes),
        "unit_price": _amount(raw.get("unit_price"), f"{label} 단가", notes),
        "amount": _amount(raw.get("amount"), f"{label} 금액", notes),
    }
    for key, name in (("length_cm", "가로"), ("width_cm", "세로"), ("height_cm", "높이")):
        line[key] = _amount(raw.get(key), f"{label} {name}", notes)

    # 서류에는 줄 전체의 총중량이 찍힙니다. 우리 칸은 한 포장 무게라 나눠 넣습니다.
    gross = _amount(raw.get("gross_weight_kg"), f"{label} 총중량", notes)
    if gross and line["quantity"] and float(line["quantity"]) > 0:
        each = float(gross) / float(line["quantity"])
        line["weight_per_package_kg"] = f"{each:.3f}".rstrip("0").rstrip(".")
    elif gross:
        notes.append(f"{label}의 총중량({gross}kg)은 읽었지만 포장 개수가 없어 "
                     "한 포장 무게를 계산하지 못했습니다.")

    if raw.get("hs_code") and len(line["hs_code"]) not in (6, 10):
        notes.append(f"{label}의 HS부호 '{raw['hs_code']}'는 자릿수가 맞지 않아 확인이 필요합니다. "
                     "HS CODE 간편 검색으로 확인해 주세요.")
    return {key: value for key, value in line.items() if value}


def _payment_terms(value) -> str:
    """B/L의 FREIGHT PREPAID/COLLECT는 운임 조건이지 대금 결제 조건이 아닙니다.

    실제로 AI가 "PREPAID"를 결제 조건 칸에 넣은 적이 있습니다. 그대로 두면
    상업송장의 TERMS OF PAYMENT에 PREPAID가 찍힙니다.
    """

    text = _clean(value, 300)
    return "" if re.fullmatch(r"(?i)(freight\s+)?(prepaid|collect)", text) else text


def _port(text, mode: str, role: str, notes: list):
    """서류의 항구 이름을 우리 목록에서 찾습니다.

    B/L은 "BUSAN, KOREA"·"LOS ANGELES, CA, USA"처럼 나라를 붙여 씁니다. 붙은
    그대로는 목록에 없으니, 못 찾으면 쉼표·괄호 앞 이름으로 한 번 더 찾습니다.
    """

    written = str(text or "").strip()
    if not written:
        return None
    head = re.split(r"[,(/]", written)[0].strip()
    if head and head != written:
        tried: list[str] = []
        place = _place(written, mode, role, tried)
        if place:
            notes.extend(tried)
            return place
        return _place(head, mode, role, notes)
    return _place(written, mode, role, notes)


def _references(raw: dict) -> str:
    """선박명·항차·B/L 번호는 우리 칸에 자리가 없어 '기타 참조'에 모아 둡니다.

    출항일과 선박명은 스케줄을 고르면 새로 정해집니다. 그래도 받은 서류와
    맞춰 볼 수 있게 남겨 둡니다. 사람이 보고 지우거나 고칠 수 있습니다.
    """

    parts = [(label, _clean(raw.get(key), 80)) for key, label in
             (("vessel_name", "VESSEL"), ("voyage_no", "VOY"), ("bl_no", "B/L NO"))]
    return " / ".join(f"{label} {value}" for label, value in parts if value)


def to_form(raw: dict) -> dict:
    """AI가 읽은 값을 서류 작성 화면의 칸 이름으로 옮깁니다. (검증을 거친 값만)"""

    notes: list[str] = []
    mode = _pick(raw.get("transport_mode"), {"SEA", "AIR"}) or "SEA"
    fields: dict[str, str] = {"transport_mode": mode}

    shipper, consignee, notify = (_party(raw.get(key))
                                  for key in ("shipper", "consignee", "notify_party"))
    fields.update({
        "exporter_name": shipper["name"], "exporter_address": shipper["address"],
        "buyer_name": consignee["name"], "buyer_address": consignee["address"],
        "buyer_country": consignee["country"],
        "notify_party": ", ".join(part for part in (notify["name"], notify["address"]) if part),
        "payment_terms": _payment_terms(raw.get("payment_terms")),
        "container_no": _clean(raw.get("container_no"), 100),
        "shipping_marks": _clean(raw.get("shipping_marks"), 500),
        "other_references": _references(raw),
    })

    incoterms = _pick(raw.get("incoterms"), INCOTERMS)
    if raw.get("incoterms") and not incoterms:
        notes.append(f"Incoterms '{raw['incoterms']}'는 Incoterms 2020 조건이 아니라 비워 두었습니다.")
    fields["incoterms"] = incoterms

    currency = _pick(raw.get("currency"), _currencies())
    if raw.get("currency") and not currency:
        notes.append(f"통화 '{raw['currency']}'는 고를 수 있는 통화가 아니라 비워 두었습니다.")
    fields["currency"] = currency

    fields["requested_departure_date"] = _date(raw.get("shipment_date"), notes, "선적일")

    for role, key in (("origin", "port_of_loading"), ("destination", "port_of_discharge")):
        place = _port(raw.get(key), mode, role, notes)
        if place:
            fields[f"{role}_code"] = place["code"]
            fields[f"{role}_name"] = f"{place['name']} ({place['code']})"

    items = raw.get("items") if isinstance(raw.get("items"), list) else []
    if len(items) > MAX_ITEMS:
        notes.append(f"품목이 {len(items)}줄이라 앞의 {MAX_ITEMS}줄만 채웠습니다.")
        items = items[:MAX_ITEMS]
    lines = [line for line in (_item(item, notes, no) for no, item in enumerate(items, 1)) if line]

    _check_amounts(lines, raw.get("total_amount"), notes)
    if lines and not any(line.get("length_cm") for line in lines):
        notes.append("포장 치수(가로·세로·높이)는 서류에 없어 비워 두었습니다. "
                     "CBM 계산과 스케줄 조회에 필요하니 직접 적어 주세요.")

    for text in (raw.get("unreadable") or [])[:5]:
        if isinstance(text, str) and text.strip():
            notes.append(f"읽지 못한 칸: {text.strip()[:200]}")

    return {"fields": {key: value for key, value in fields.items() if value},
            "items": lines, "notes": notes}


def _check_amounts(lines: list[dict], total, notes: list) -> None:
    """품목 금액은 모두 있거나 모두 없어야 합니다. (document_start_service와 같은 규칙)"""

    with_amount = [line for line in lines if line.get("amount")]
    if with_amount and len(with_amount) != len(lines):
        notes.append(f"품목 {len(lines)}줄 중 {len(with_amount)}줄만 금액이 읽혔습니다. "
                     "금액은 모든 줄에 적거나 모두 비워야 서류가 만들어집니다.")
        return
    if not with_amount or total in (None, ""):
        return
    try:
        written = sum(float(line["amount"]) for line in with_amount)
        stated = float(total)
    except (TypeError, ValueError):
        return
    if abs(written - stated) > max(0.01, stated * 0.001):
        notes.append(f"품목 금액의 합({written:,.2f})이 서류의 합계({stated:,.2f})와 다릅니다. "
                     "줄마다 금액을 다시 확인해 주세요.")


def _summary(raw: dict, form: dict) -> list[dict]:
    """무엇을 읽었는지 사람이 한눈에 보게. 칸에 넣지 못한 값도 보여 줍니다."""

    fields = form["fields"]
    rows = [
        ("Shipper", _party(raw.get("shipper"))["name"]),
        ("Consignee", _party(raw.get("consignee"))["name"]),
        ("Notify Party", fields.get("notify_party", "")),
        ("Incoterms", " ".join(part for part in (fields.get("incoterms", ""),
                                                 _clean(raw.get("incoterms_place"), 80)) if part)),
        ("통화 · 합계", " ".join(part for part in (fields.get("currency", ""),
                                               _amount(raw.get("total_amount"), "합계", [])) if part)),
        ("POL", fields.get("origin_name") or _clean(raw.get("port_of_loading"), 80)),
        ("POD", fields.get("destination_name") or _clean(raw.get("port_of_discharge"), 80)),
        ("Vessel", " ".join(part for part in (_clean(raw.get("vessel_name"), 80),
                                              _clean(raw.get("voyage_no"), 40)) if part)),
        ("품목", f"{len(form['items'])}줄" if form["items"] else ""),
    ]
    return [{"label": label, "value": value} for label, value in rows if value]


def _missing(form: dict) -> list[str]:
    """아직 비어 있어 사람이 채워야 하는 필수 칸. 목록은 서류 화면과 같은 곳에서 옵니다."""

    checklist = document_start_service.checklist()
    fields, items = form["fields"], form["items"]
    missing = [field["label"] for group in checklist["groups"] for field in group["fields"]
               if field.get("required") and not fields.get(field["name"])]
    first = items[0] if items else {}
    missing += [f"품목 {field['label']}" for field in checklist["item_fields"]
                if field.get("required") and not first.get(field["name"])]
    return missing


def extract(filename: str, data: bytes) -> dict:
    """파일 하나를 읽어 서류 작성 화면이 그대로 쓰는 초안을 돌려줍니다."""

    if not available():
        raise ServiceError("AI 키(AI_API_KEY)가 없어 서류를 읽을 수 없습니다. "
                           "칸을 직접 채워 주세요.", "API_AUTH_FAILED")
    text, images = read_upload(filename, data)
    text, images, protect_notes = _protect(text, images)
    raw = _scrub(_ask_ai(text, images))
    form = to_form(raw)
    notes = protect_notes + form.pop("notes")
    kind = raw.get("document_type") if raw.get("document_type") in DOCUMENT_LABELS else "other"
    return {
        "document_type": kind,
        "document_label": DOCUMENT_LABELS[kind],
        "form": form,
        "summary": _summary(raw, form),
        # 운송 모드는 늘 들어가고, 항구는 코드와 보이는 이름 두 칸이라 하나로 셉니다.
        "filled": (sum(1 for key in form["fields"]
                       if key != "transport_mode" and not key.endswith("_name"))
                   + sum(len(line) for line in form["items"])),
        "missing": _missing(form),
        "notes": notes,
        # HS CODE 간편 검색 창이 열릴 때 검색창에 넣을 품명들.
        "hs_queries": [line["product_description"] for line in form["items"]
                       if line.get("product_description") and not line.get("hs_code")][:MAX_ITEMS],
        "source": "api",
    }
