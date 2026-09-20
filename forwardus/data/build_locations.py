"""Build data/mock/locations.json from the official UN/LOCODE code list.

Sources
- UN/LOCODE code list (UNECE, mirrored by the Frictionless Data project)
- ISO 3166 country list with regions (for schedule region mapping)
- Korean country names

Usage:
    python data/build_locations.py

Port and airport codes come from UN/LOCODE, so they are not invented. Korean
display names are only applied to the major ports listed in KOREAN_NAMES;
other locations keep their romanized UN/LOCODE name.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import httpx

DATA_DIR = Path(__file__).resolve().parent
RAW_DIR = DATA_DIR / "raw"
OUTPUT = DATA_DIR / "mock" / "locations.json"

UNLOCODE_URL = "https://raw.githubusercontent.com/datasets/un-locode/main/data/code-list.csv"
ISO_URL = "https://raw.githubusercontent.com/lukes/ISO-3166-Countries-with-Regional-Codes/master/all/all.json"
KOREAN_COUNTRY_URL = "https://raw.githubusercontent.com/umpirsky/country-list/master/data/ko/country.json"

# UN/LOCODE function codes: 1 = seaport, 4 = airport.
PORT_FUNCTION = "1"
AIRPORT_FUNCTION = "4"

# ISO sub-region → schedule region used by data/mock/schedules.json.
SUB_REGION_TO_REGION = {
    "Eastern Asia": "asia",
    "South-eastern Asia": "asia",
    "Southern Asia": "asia",
    "Central Asia": "asia",
    "Western Asia": "middle_east",
    "Northern Europe": "europe",
    "Southern Europe": "europe",
    "Eastern Europe": "europe",
    "Western Europe": "europe",
    "Northern Africa": "africa",
    "Sub-Saharan Africa": "africa",
    "Northern America": "americas",
    "Latin America and the Caribbean": "americas",  # 남미는 INTERMEDIATE_REGION에서 분리
    "Australia and New Zealand": "oceania",
    "Melanesia": "oceania",
    "Micronesia": "oceania",
    "Polynesia": "oceania",
}
# ISO intermediate-region overrides: South America is far longer than North
# America on the Asia route, so it gets its own schedule region.
INTERMEDIATE_REGION_TO_REGION = {"South America": "south_america"}
DEFAULT_REGION = "asia"

# Korean display names, keyed by UN/LOCODE. Major ports are listed first in
# search results. build_locations.py warns when a code is not in the dataset.
KOREAN_NAMES = {
    # 국내 무역항 (코드는 UN/LOCODE 확인값)
    "KRPUS": "부산항", "KRBNP": "부산신항", "KRKCN": "감천항(부산)", "KRINC": "인천항",
    "KRGIN": "경인항", "KRPTK": "평택항", "KRTJI": "당진항", "KRTSN": "대산항",
    "KRKAN": "광양항", "KRYOS": "여수항", "KRUSN": "울산항", "KRONS": "온산항(울산)",
    "KRMIP": "미포항(울산)", "KRKPO": "포항항", "KRSHG": "포항신항", "KRMAS": "마산항",
    "KRCHF": "진해항", "KRTYG": "통영항", "KRSCP": "삼천포항", "KROKP": "옥포항",
    "KRKHN": "고현항", "KRCHG": "장항항", "KRBOR": "보령항", "KRKUV": "군산항",
    "KRMOK": "목포항", "KRDBL": "대불항", "KRWND": "완도항", "KRTGH": "동해항",
    "KRMUK": "묵호항", "KRSUK": "삼척항", "KROKK": "옥계항", "KRSHO": "속초항",
    "KRGRP": "구룡포항", "KRCHA": "제주항", "KRSPO": "서귀포항", "KRHDO": "하동항",
    "KRTAN": "태안항", "KRSEL": "서울항",
    # 주요 해외 항만
    "USLAX": "로스앤젤레스항", "USLGB": "롱비치항", "USNYC": "뉴욕·뉴저지항",
    "USSEA": "시애틀항", "USSAV": "서배너항", "USHOU": "휴스턴항", "USOAK": "오클랜드항",
    "CAVAN": "밴쿠버항", "MXZLO": "만사니요항",
    "CNSGH": "상하이항", "CNSHG": "상하이항 터미널", "CNNBO": "닝보항", "CNNBG": "닝보항 터미널",
    "CNSNZ": "선전항", "CNYTN": "옌톈 터미널(선전)", "CNSHK": "서커우 터미널(선전)",
    "CNQIN": "칭다오항", "CNTNJ": "톈진항", "CNTXG": "톈진신강 터미널",
    "CNGGZ": "광저우항", "CNXAM": "샤먼항", "CNDAL": "다롄항",
    "HKHKG": "홍콩항", "TWKHH": "가오슝항", "TWKEL": "지룽항",
    "JPTYO": "도쿄항", "JPYOK": "요코하마항", "JPOSA": "오사카항", "JPUKB": "고베항",
    "JPNGO": "나고야항", "JPHKT": "하카타항", "JPSMZ": "시미즈항",
    "SGSIN": "싱가포르항", "MYPKG": "포트클랑항", "MYTPP": "탄중펠레파스항",
    "VNSGN": "호찌민항", "VNHPH": "하이퐁항", "VNCMT": "까이멥항", "VNDAD": "다낭항",
    "THLCH": "램차방항", "THBKK": "방콕항", "IDJKT": "자카르타(탄중프리옥)항",
    "PHMNL": "마닐라항", "INNSA": "나바셰바항", "INMAA": "첸나이항", "INMUN": "문드라항",
    "BDCGP": "치타공항", "PKKHI": "카라치항", "LKCMB": "콜롬보항",
    "AEJEA": "제벨알리항", "AEAUH": "아부다비항", "SAJED": "제다항", "SADMM": "담맘항",
    "DEHAM": "함부르크항", "DEBRV": "브레머하펜항", "NLRTM": "로테르담항",
    "BEANR": "안트베르펜항", "GBFXT": "펠릭스토항", "GBLON": "런던항",
    "FRLEH": "르아브르항", "ESVLC": "발렌시아항", "ESALG": "알헤시라스항",
    "ESBCN": "바르셀로나항", "ITGOA": "제노바항", "ITGIT": "조이아타우로항",
    "GRPIR": "피레우스항", "PLGDN": "그단스크항", "RULED": "상트페테르부르크항",
    "RUVVO": "블라디보스토크항", "TRAMR": "암발리항", "TRIZM": "이즈미르항",
    "EGPSD": "포트사이드항", "MAPTM": "탕헤르메드항", "ZADUR": "더반항",
    "AUSYD": "시드니항", "AUMEL": "멜버른항", "AUBNE": "브리즈번항",
    "NZAKL": "오클랜드항", "BRSSZ": "산투스항", "CLSAI": "산안토니오항",
    "PECLL": "카야오항", "PABLB": "발보아항",
}

# Major cargo airports (IATA code → Korean name). UN/LOCODE airport rows are
# noisy, so international airports used for air freight are curated here.
MAJOR_AIRPORTS = {
    "ICN": ("인천국제공항", "Incheon International Airport", "KR"),
    "PUS": ("김해국제공항", "Gimhae International Airport", "KR"),
    "GMP": ("김포국제공항", "Gimpo International Airport", "KR"),
    "CJU": ("제주국제공항", "Jeju International Airport", "KR"),
    "TAE": ("대구국제공항", "Daegu International Airport", "KR"),
    "CJJ": ("청주국제공항", "Cheongju International Airport", "KR"),
    "KWJ": ("광주공항", "Gwangju Airport", "KR"),
    "MWX": ("무안국제공항", "Muan International Airport", "KR"),
    "YNY": ("양양국제공항", "Yangyang International Airport", "KR"),
    "LAX": ("로스앤젤레스국제공항", "Los Angeles International Airport", "US"),
    "JFK": ("뉴욕 JFK 국제공항", "John F. Kennedy International Airport", "US"),
    "ORD": ("시카고 오헤어 국제공항", "Chicago O Hare International Airport", "US"),
    "SFO": ("샌프란시스코국제공항", "San Francisco International Airport", "US"),
    "SEA": ("시애틀 타코마 국제공항", "Seattle-Tacoma International Airport", "US"),
    "ATL": ("애틀랜타국제공항", "Hartsfield-Jackson Atlanta International Airport", "US"),
    "DFW": ("댈러스포트워스국제공항", "Dallas/Fort Worth International Airport", "US"),
    "MIA": ("마이애미국제공항", "Miami International Airport", "US"),
    "YVR": ("밴쿠버국제공항", "Vancouver International Airport", "CA"),
    "YYZ": ("토론토 피어슨 국제공항", "Toronto Pearson International Airport", "CA"),
    "MEX": ("멕시코시티국제공항", "Mexico City International Airport", "MX"),
    "GRU": ("상파울루 과룰류스 국제공항", "Sao Paulo/Guarulhos International Airport", "BR"),
    "PVG": ("상하이푸둥국제공항", "Shanghai Pudong International Airport", "CN"),
    "PEK": ("베이징 서우두 국제공항", "Beijing Capital International Airport", "CN"),
    "CAN": ("광저우 바이윈 국제공항", "Guangzhou Baiyun International Airport", "CN"),
    "SZX": ("선전 바오안 국제공항", "Shenzhen Baoan International Airport", "CN"),
    "TAO": ("칭다오 자오둥 국제공항", "Qingdao Jiaodong International Airport", "CN"),
    "HKG": ("홍콩국제공항", "Hong Kong International Airport", "HK"),
    "TPE": ("타이완 타오위안 국제공항", "Taiwan Taoyuan International Airport", "TW"),
    "NRT": ("나리타국제공항", "Narita International Airport", "JP"),
    "HND": ("하네다공항", "Tokyo Haneda Airport", "JP"),
    "KIX": ("간사이국제공항", "Kansai International Airport", "JP"),
    "NGO": ("주부 센트레아 국제공항", "Chubu Centrair International Airport", "JP"),
    "FUK": ("후쿠오카공항", "Fukuoka Airport", "JP"),
    "SIN": ("싱가포르 창이공항", "Singapore Changi Airport", "SG"),
    "BKK": ("수완나품국제공항", "Suvarnabhumi Airport", "TH"),
    "SGN": ("떤선녓국제공항", "Tan Son Nhat International Airport", "VN"),
    "HAN": ("노이바이국제공항", "Noi Bai International Airport", "VN"),
    "KUL": ("쿠알라룸푸르국제공항", "Kuala Lumpur International Airport", "MY"),
    "CGK": ("수카르노하타국제공항", "Soekarno-Hatta International Airport", "ID"),
    "MNL": ("니노이 아키노 국제공항", "Ninoy Aquino International Airport", "PH"),
    "DEL": ("인디라 간디 국제공항", "Indira Gandhi International Airport", "IN"),
    "BOM": ("차트라파티 시바지 국제공항", "Chhatrapati Shivaji International Airport", "IN"),
    "MAA": ("첸나이국제공항", "Chennai International Airport", "IN"),
    "DXB": ("두바이국제공항", "Dubai International Airport", "AE"),
    "AUH": ("아부다비국제공항", "Abu Dhabi International Airport", "AE"),
    "DOH": ("하마드국제공항", "Hamad International Airport", "QA"),
    "RUH": ("킹 칼리드 국제공항", "King Khalid International Airport", "SA"),
    "IST": ("이스탄불공항", "Istanbul Airport", "TR"),
    "FRA": ("프랑크푸르트공항", "Frankfurt Airport", "DE"),
    "MUC": ("뮌헨공항", "Munich Airport", "DE"),
    "AMS": ("암스테르담 스히폴공항", "Amsterdam Airport Schiphol", "NL"),
    "LHR": ("런던 히스로공항", "London Heathrow Airport", "GB"),
    "CDG": ("파리 샤를드골공항", "Paris Charles de Gaulle Airport", "FR"),
    "LUX": ("룩셈부르크공항", "Luxembourg Airport", "LU"),
    "LGG": ("리에주공항", "Liege Airport", "BE"),
    "BRU": ("브뤼셀공항", "Brussels Airport", "BE"),
    "MAD": ("마드리드 바라하스공항", "Adolfo Suarez Madrid-Barajas Airport", "ES"),
    "MXP": ("밀라노 말펜사공항", "Milan Malpensa Airport", "IT"),
    "WAW": ("바르샤바 쇼팽공항", "Warsaw Chopin Airport", "PL"),
    "SVO": ("셰레메티예보국제공항", "Sheremetyevo International Airport", "RU"),
    "CAI": ("카이로국제공항", "Cairo International Airport", "EG"),
    "JNB": ("요하네스버그 OR탐보 국제공항", "O. R. Tambo International Airport", "ZA"),
    "NBO": ("조모 케냐타 국제공항", "Jomo Kenyatta International Airport", "KE"),
    "SYD": ("시드니공항", "Sydney Airport", "AU"),
    "MEL": ("멜버른공항", "Melbourne Airport", "AU"),
    "BNE": ("브리즈번공항", "Brisbane Airport", "AU"),
    "AKL": ("오클랜드공항", "Auckland Airport", "NZ"),
}


def download(url: str, filename: str) -> bytes:
    """Download once and cache under data/raw/."""

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cached = RAW_DIR / filename
    if cached.exists():
        return cached.read_bytes()
    content = httpx.get(url, timeout=120, follow_redirects=True).content
    cached.write_bytes(content)
    return content


def title_case(name: str) -> str:
    return " ".join(word if word.isupper() and len(word) <= 3 else word.title() for word in name.split())


def build() -> list[dict]:
    unlocode = list(csv.DictReader(io.StringIO(download(UNLOCODE_URL, "unlocode_code_list.csv").decode("utf-8", "replace"))))
    iso = json.loads(download(ISO_URL, "iso_3166_regions.json"))
    korean_country = json.loads(download(KOREAN_COUNTRY_URL, "country_names_ko.json"))

    country_info = {
        row["alpha-2"]: {
            "name_en": row["name"],
            "name": korean_country.get(row["alpha-2"], row["name"]),
            "region": INTERMEDIATE_REGION_TO_REGION.get(
                row.get("intermediate-region") or "",
                SUB_REGION_TO_REGION.get(row.get("sub-region") or "", DEFAULT_REGION),
            ),
        }
        for row in iso
    }

    locations = []
    seen = set()

    for row in unlocode:
        country_code = row["Country"]
        info = country_info.get(country_code)
        if not info or PORT_FUNCTION not in (row["Function"] or ""):
            continue
        code = f"{country_code}{row['Location']}"
        if code in seen:
            continue
        seen.add(code)
        name_en = title_case(row["NameWoDiacritics"] or row["Name"])
        locations.append({
            "code": code,
            "name": KOREAN_NAMES.get(code, name_en),
            "name_en": name_en,
            "city": row["Name"],
            "city_en": name_en,
            "country": info["name"],
            "country_en": info["name_en"],
            "country_code": country_code,
            "region": info["region"],
            "kind": "port",
            "major": code in KOREAN_NAMES,
        })

    for iata, (name_ko, name_en, country_code) in MAJOR_AIRPORTS.items():
        info = country_info.get(country_code)
        locations.append({
            "code": iata,
            "name": name_ko,
            "name_en": name_en,
            "city": name_ko,
            "city_en": name_en,
            "country": info["name"],
            "country_en": info["name_en"],
            "country_code": country_code,
            "region": info["region"],
            "kind": "airport",
            "major": True,
        })

    locations.sort(key=lambda item: (item["kind"], item["country_code"], not item["major"], item["code"]))
    return locations


if __name__ == "__main__":
    items = build()
    unmatched = sorted(set(KOREAN_NAMES) - {item["code"] for item in items})
    if unmatched:
        print(f"경고: UN/LOCODE에 없는 코드 {len(unmatched)}개 -> {', '.join(unmatched)}")
    OUTPUT.write_text(json.dumps(items, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    ports = [item for item in items if item["kind"] == "port"]
    print(f"{OUTPUT}: {len(items):,} locations "
          f"(ports {len(ports):,} / airports {len(items) - len(ports):,}, "
          f"countries {len({item['country_code'] for item in items}):,})")
