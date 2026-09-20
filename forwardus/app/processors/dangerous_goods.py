"""위험물(Dangerous Goods) 분류와 보내는 방법 안내.

급(class) 구분은 UN 위험물 운송 권고(UN Model Regulations)를 따르고, 해상은
IMDG Code(국제해상위험물규칙), 항공은 IATA DGR(ICAO 기술기준)을 씁니다. 같은
물건이라도 해상은 실을 수 있고 항공은 못 싣는 경우가 많아 급마다 나눠 적습니다.

여기 적은 내용은 "무엇을 준비해야 하는지"를 알리는 안내입니다. 실제 허용
여부·수량 한도·포장 등급은 물질마다 다르고 선사·항공사마다 더 엄격한 기준을
두므로, 마지막 확인은 반드시 선사/항공사와 도착국 규정으로 합니다.
"""

from __future__ import annotations

from app.processors.korean import josa

# UN 위험물 9개 급. examples는 수출 현장에서 실제로 자주 나오는 품목입니다.
DG_CLASSES = {
    "1": {
        "label": "1급 · 화약류",
        "english": "Explosives",
        "examples": "화약, 폭죽, 탄약, 에어백 팽창기, 안전뇌관",
        "air": "forbidden",
        "air_note": "여객기는 물론 화물기도 원칙적으로 실을 수 없습니다."
                    " 1.4S 등 일부만 예외적으로 허용되며 항공사 사전 승인이 반드시 필요합니다.",
        "sea_note": "IMDG에 따라 다른 화물과 격리해 싣습니다. 화약류 취급 허가를 받은 터미널만 가능합니다.",
    },
    "2.1": {
        "label": "2.1급 · 인화성 가스",
        "english": "Flammable gases",
        "examples": "부탄가스, LPG, 라이터, 인화성 에어로졸(스프레이)",
        "air": "restricted",
        "air_note": "여객기 탑재가 금지되거나 수량이 크게 제한됩니다. 화물기 전용으로만 보내는 경우가 많습니다.",
        "sea_note": "갑판 적재(on deck)로 지정되는 경우가 많습니다.",
    },
    "2.2": {
        "label": "2.2급 · 비인화성·비독성 가스",
        "english": "Non-flammable, non-toxic gases",
        "examples": "질소, 헬륨, 산소, 소화기, 탄산가스",
        "air": "allowed",
        "air_note": "위험물 중에서는 비교적 제약이 적지만 신고와 UN 규격 용기는 그대로 필요합니다.",
        "sea_note": "용기 압력·밸브 보호 상태를 점검합니다.",
    },
    "2.3": {
        "label": "2.3급 · 독성 가스",
        "english": "Toxic gases",
        "examples": "염소, 무수암모니아, 산화에틸렌",
        "air": "forbidden",
        "air_note": "여객기는 금지이고 화물기도 대부분 실을 수 없습니다.",
        "sea_note": "격리 요건이 가장 엄격한 급에 속합니다. 선사 사전 승인이 필요합니다.",
    },
    "3": {
        "label": "3급 · 인화성 액체",
        "english": "Flammable liquids",
        "examples": "페인트, 신너, 접착제, 알코올, 향수·화장품(알코올 함량 높은 것), 잉크",
        "air": "restricted",
        "air_note": "인화점에 따라 포장등급(PG I·II·III)이 갈리고 1개 포장당 허용량이 정해져 있습니다."
                    " 수출이 가장 잦은 급이라 항공사별 한도를 미리 확인해야 합니다.",
        "sea_note": "수출 현장에서 가장 많이 나오는 급입니다. 인화점 자료(MSDS)로 포장등급을 정합니다.",
    },
    "4.1": {
        "label": "4.1급 · 가연성 고체",
        "english": "Flammable solids",
        "examples": "성냥, 유황, 니트로셀룰로스, 금속분말",
        "air": "restricted",
        "air_note": "자기반응성 물질은 온도 관리가 필요해 항공 운송이 제한됩니다.",
        "sea_note": "열원과 떨어뜨려 적재합니다.",
    },
    "4.2": {
        "label": "4.2급 · 자연발화성 물질",
        "english": "Substances liable to spontaneous combustion",
        "examples": "백린, 일부 활성탄, 유지가 묻은 섬유 폐기물",
        "air": "restricted",
        "air_note": "공기와 닿으면 스스로 발화해 화물기 전용으로도 승인이 어렵습니다.",
        "sea_note": "밀폐·불활성 포장이 필요합니다.",
    },
    "4.3": {
        "label": "4.3급 · 물과 반응하는 물질",
        "english": "Substances which emit flammable gases in contact with water",
        "examples": "나트륨, 칼슘카바이드, 마그네슘 분말",
        "air": "restricted",
        "air_note": "방수 포장이 필수이며 허용 수량이 매우 적습니다.",
        "sea_note": "해상은 습기가 많아 방수 포장과 격리가 특히 중요합니다.",
    },
    "5.1": {
        "label": "5.1급 · 산화성 물질",
        "english": "Oxidizing substances",
        "examples": "과산화수소, 표백제, 질산암모늄 비료, 과망간산칼륨",
        "air": "restricted",
        "air_note": "농도에 따라 금지되기도 합니다. (예: 고농도 과산화수소)",
        "sea_note": "인화성 물질과 반드시 격리합니다.",
    },
    "5.2": {
        "label": "5.2급 · 유기과산화물",
        "english": "Organic peroxides",
        "examples": "경화제, 수지 촉매(MEKP 등)",
        "air": "restricted",
        "air_note": "온도 관리가 필요한 품목은 항공 운송이 어렵습니다.",
        "sea_note": "온도조절이 필요한 물질은 냉장 컨테이너와 사전 승인이 필요합니다.",
    },
    "6.1": {
        "label": "6.1급 · 독성 물질",
        "english": "Toxic substances",
        "examples": "살충제·농약, 니코틴, 비소화합물, 청산염",
        "air": "restricted",
        "air_note": "식품·의약품과 같은 항공기에 실을 수 없어 적재 위치가 제한됩니다.",
        "sea_note": "식품류와 격리해 적재합니다.",
    },
    "6.2": {
        "label": "6.2급 · 전염성 물질",
        "english": "Infectious substances",
        "examples": "진단용 검체, 배양균, 의료폐기물, 백신 일부",
        "air": "restricted",
        "air_note": "카테고리 A(UN2814·UN2900)는 특별 포장(P620)과 사전 승인이 필요합니다.",
        "sea_note": "해상보다 항공으로 보내는 경우가 많습니다.",
    },
    "7": {
        "label": "7급 · 방사성 물질",
        "english": "Radioactive material",
        "examples": "의료용 방사성 동위원소, 산업용 비파괴검사 선원",
        "air": "restricted",
        "air_note": "원자력안전위원회 승인과 항공사 개별 승인이 모두 필요합니다.",
        "sea_note": "원자력안전법에 따른 운반 신고가 함께 필요합니다.",
    },
    "8": {
        "label": "8급 · 부식성 물질",
        "english": "Corrosive substances",
        "examples": "황산·염산 등 산류, 수산화나트륨, 배터리액, 일부 세정제",
        "air": "restricted",
        "air_note": "누출 시 기체를 손상시켜 포장 기준이 엄격합니다. 이중 포장과 흡수재가 필요합니다.",
        "sea_note": "금속 컨테이너 부식을 막기 위해 받침·흡수재를 함께 넣습니다.",
    },
    "9": {
        "label": "9급 · 기타 위험물",
        "english": "Miscellaneous dangerous goods",
        "examples": "리튬이온·리튬메탈 배터리, 드라이아이스, 자성 물질, 환경유해물질, 온도조절 물질",
        "air": "restricted",
        "air_note": "리튬 배터리는 별도 포장지침(PI 965~970)을 따릅니다."
                    " 배터리만 따로 보내는 경우 충전량을 30% 이하로 맞추고 여객기 탑재가 금지됩니다.",
        "sea_note": "리튬 배터리는 해상이 수량 제한이 덜해 대량 운송에 주로 씁니다.",
    },
}

# 항공 적재 가능 여부를 한 줄로 표시할 때 쓰는 말
AIR_STATUS_LABELS = {
    "forbidden": "항공 운송 사실상 불가",
    "restricted": "항공은 조건부 · 수량 제한",
    "allowed": "항공 운송 가능",
}

# 운송수단과 상관없이 공통으로 필요한 것
COMMON_STEPS = [
    "물질안전보건자료(MSDS/SDS)를 영문으로 준비합니다. 여기에 적힌 UN번호·급·포장등급이 모든 서류의 기준이 됩니다.",
    "UN 규격 용기에 담고 용기에 찍힌 UN 표시를 확인합니다. 일반 상자는 쓸 수 없습니다.",
    "위험물 라벨(급 표찰)과 UN번호·정식운송품명(PSN)을 포장 겉면에 붙입니다.",
    "위험물 신고서(Shipper's Declaration for Dangerous Goods)를 작성해 선사·항공사에 제출합니다.",
]

SEA_STEPS = [
    "선사에 위험물 사전 승인(DG approval)을 받아야 부킹이 확정됩니다. 일반 화물보다 며칠 더 걸립니다.",
    "컨테이너에 실을 때 컨테이너수납검사증(CTU Packing Certificate)을 함께 냅니다.",
    "서류 마감이 일반 화물보다 빠릅니다. 출항 예정일에서 하루 이틀 앞당겨 잡으세요.",
]
AIR_STEPS = [
    "위험물 신고서는 IATA DGR 교육을 이수한 사람만 작성할 수 있습니다. 포워더나 전문 업체에 맡기는 것이 일반적입니다.",
    "항공사마다 받아 주는 급과 수량이 달라 부킹 전에 항공사 승인을 먼저 받습니다.",
    "여객기(PAX)와 화물기(CAO)에 실을 수 있는 수량이 다릅니다. 화물기 전용이면 운항 편이 줄어 일정이 길어집니다.",
]

# 근거 규정과 공식 확인처
REFERENCES = [
    {"label": "IMDG Code (국제해상위험물규칙) · IMO", "url": "https://www.imo.org/en/OurWork/Safety/Pages/DangerousGoods-default.aspx"},
    {"label": "IATA 위험물 규정(DGR) 안내", "url": "https://www.iata.org/en/programs/cargo/dgr/"},
    {"label": "국가법령정보센터 · 위험물 선박운송 및 저장규칙", "url": "https://www.law.go.kr/LSW/lsSc.do?query=위험물선박운송및저장규칙"},
]


def classes() -> list[dict]:
    """화면의 위험물 등급 선택 목록."""

    return [{"code": code, **info} for code, info in DG_CLASSES.items()]


def guide(dg_class: str, transport_mode: str, country_name: str = "") -> dict:
    """고른 등급과 운송수단에 맞춰 무엇을 어떻게 준비할지 정리합니다."""

    info = DG_CLASSES.get((dg_class or "").strip())
    if not info:
        return {"available": False,
                "message": "위험물 등급을 고르면 보내는 방법을 안내합니다."}

    is_air = (transport_mode or "SEA").upper() == "AIR"
    status = info["air"] if is_air else "allowed"
    where = f"{josa(country_name, '로')} " if country_name else ""
    return {
        "available": True,
        "code": dg_class,
        "label": info["label"],
        "english": info["english"],
        "examples": info["examples"],
        "mode": "AIR" if is_air else "SEA",
        "rule": "IATA DGR(항공위험물규정)" if is_air else "IMDG Code(국제해상위험물규칙)",
        "status": status,
        "status_label": AIR_STATUS_LABELS[status] if is_air else "해상 운송 가능",
        "mode_note": info["air_note"] if is_air else info["sea_note"],
        "steps": COMMON_STEPS + (AIR_STEPS if is_air else SEA_STEPS),
        "destination_note": (
            f"{where}보낼 때는 도착국 세관·항만이 따로 두는 반입 제한도 확인해야 합니다."
            " 같은 급이라도 나라마다 허가·수량 기준이 다릅니다." if country_name else
            "도착지를 고르면 그 나라에서 확인할 곳을 함께 안내합니다."),
        "references": REFERENCES,
    }
