"""Build data/mock/locations.json from the official UN/LOCODE code list.

Sources
- UN/LOCODE code list (UNECE, mirrored by the Frictionless Data project)
- World Port Index / NGA Pub 150 (harbour size, used to pick each country's
  main trade ports)
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
# 직접 입력한 항구 이름을 실제 코드로 바꾸기 위한 전체 색인 (분류 여부와 무관).
INDEX_OUTPUT = DATA_DIR / "mock" / "unlocode_ports.json"

UNLOCODE_URL = "https://raw.githubusercontent.com/datasets/un-locode/main/data/code-list.csv"
ISO_URL = "https://raw.githubusercontent.com/lukes/ISO-3166-Countries-with-Regional-Codes/master/all/all.json"
KOREAN_COUNTRY_URL = "https://raw.githubusercontent.com/umpirsky/country-list/master/data/ko/country.json"
WPI_URL = "https://msi.nga.mil/api/publications/world-port-index?output=json"

# 내륙국(바다에 접하지 않는 국가)은 강·운하 항만만 있어 해상 수출 목적지가 될 수
# 없으므로 제외합니다. 항공 목적지는 MAJOR_AIRPORTS에서 따로 관리합니다.
LANDLOCKED_COUNTRIES = {
    "AD", "AF", "AM", "AT", "AZ", "BF", "BI", "BO", "BT", "BW", "BY", "CF", "CH", "CZ",
    "ET", "HU", "KG", "KZ", "LA", "LI", "LS", "LU", "MD", "MK", "ML", "MN", "MW", "NE",
    "NP", "PY", "RS", "RW", "SI", "SK", "SM", "SS", "SZ", "TD", "TJ", "TM", "UG", "UZ",
    "VA", "XK", "ZM", "ZW",
}
# 슬로베니아(SI)는 코페르항이 있는 연안국이므로 제외 대상에서 되돌립니다.
LANDLOCKED_COUNTRIES.discard("SI")

# 남극(AQ)은 연구기지 기항지라 무역항이 아닙니다.
EXCLUDED_COUNTRIES = LANDLOCKED_COUNTRIES | {"AQ"}

# 같은 항만이 옛 로마자 표기로 중복 등록된 코드입니다.
# KRTGA(Tonghae) = KRTGH(동해항), KRKWA(Kwangyang) = KRKAN(광양항)
DUPLICATE_CODES = {"KRTGA", "KRKWA"}

# UN/LOCODE function codes: 1 = seaport, 4 = airport.
PORT_FUNCTION = "1"
AIRPORT_FUNCTION = "4"

# World Port Index harbour size: L(arge), M(edium), S(mall), V(ery small).
HARBOR_SIZE_RANK = {"L": 0, "M": 1, "S": 2, "V": 3}
MAIN_HARBOR_SIZES = {"L", "M"}
# Countries without a large or medium harbour still need suggestions, so their
# biggest harbours are promoted until this many main ports exist.
MIN_MAIN_PORTS_PER_COUNTRY = 5

# UN/LOCODE status codes set by a national authority or customs. Used only for
# countries the World Port Index does not cover (e.g. Bulgaria, Barbados).
APPROVED_STATUSES = {"AA", "AC", "AI", "AS"}

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

# 해외 주요 항만의 한글 표기. build_locations.py 실행 시 UN/LOCODE에 없는 코드는
# 경고로 알려줍니다.
# 「항만법」상 무역항 31곳과 그 소속 부두·터미널.
# 값은 (한글명, 관리 주체). national = 국가관리무역항, local = 지방관리무역항.
# 국내 출발지는 이 목록만 노출하고 어항·연안항(구룡포·후포·주문진·홍도 등)은 제외합니다.
KOREA_TRADE_PORTS = {
    # 국가관리무역항과 소속 부두
    "KRGIN": ("경인항", "national"),
    "KRINC": ("인천항", "national"),
    "KRTSN": ("대산항", "national"),
    "KRCHG": ("장항항", "national"),
    "KRKUV": ("군산항", "national"),
    "KRMOK": ("목포항", "national"),
    "KRDBL": ("대불부두(목포)", "national"),
    "KRYOS": ("여수항", "national"),
    "KRYOC": ("여천부두(여수)", "national"),
    "KRKAN": ("광양항", "national"),
    "KRPUS": ("부산항", "national"),
    "KRBNP": ("부산신항", "national"),
    "KRKCN": ("감천부두(부산)", "national"),
    "KRMAS": ("마산항", "national"),
    "KRUSN": ("울산항", "national"),
    "KRONS": ("온산부두(울산)", "national"),
    "KRMIP": ("미포부두(울산)", "national"),
    "KRKPO": ("포항항", "national"),
    "KRSHG": ("포항신항", "national"),
    "KRTGH": ("동해항", "national"),
    "KRMUK": ("묵호항", "national"),
    # 지방관리무역항
    "KRPTK": ("평택항", "local"),
    "KRTJI": ("당진항", "local"),
    "KRBOR": ("보령항", "local"),
    "KRTAN": ("태안항", "local"),
    "KRSEL": ("서울항", "local"),
    "KRCHA": ("제주항", "local"),
    "KRSPO": ("서귀포항", "local"),
    "KRWND": ("완도항", "local"),
    "KRSCP": ("삼천포항", "local"),
    "KRTYG": ("통영항", "local"),
    "KROKP": ("옥포항", "local"),
    "KRKHN": ("고현항", "local"),
    "KRCHF": ("진해항", "local"),
    "KRSUK": ("삼척항", "local"),
    "KRSHO": ("속초항", "local"),
    "KROKK": ("옥계항", "local"),
    "KRHAS": ("호산항", "local"),
}

# 목록에 없는 국내 항구(연안항·어항 등)를 한글 이름으로도 찾을 수 있도록 하는 별칭.
KOREAN_PORT_ALIASES = {
    "KRGRP": "구룡포항", "KRHPO": "후포항", "KRJMJ": "주문진항", "KRULL": "울릉항",
    "KRCJA": "추자항", "KRHLM": "한림항", "KRSSP": "성산포항", "KRHDO": "홍도항",
    "KRDHS": "대흑산도항", "KRGMD": "거문도항", "KRNRD": "나로도항", "KRNDS": "녹동신항",
    "KRDCN": "대천항", "KRAWL": "애월항", "KRHSN": "화순항", "KRBIN": "비인항",
    "KRGGU": "강구항", "KRKJE": "거제항", "KRSBU": "부산남항", "KRYPD": "연평도항",
    "KRSWD": "상왕등도항", "KRGGH": "가거항리항", "KRHHP": "화흥포항", "KRJHA": "중화항",
    "KRKDO": "국도항", "KRGDO": "갈두항", "KRSGG": "송공항", "KRYGP": "용기포항",
    "KRDDO": "독도", "KRCGY": "청양", "KRANJ": "안정", "KRBUK": "부평(인천)",
}

# 목록에서 함께 보여줄 안내 문구.
PORT_NOTES = {
    "KRSEL": "법적 무역항",
}

KOREAN_NAMES = {
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


def normalize_name(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def load_harbor_sizes(unlocode_rows: list[dict]) -> dict[str, str]:
    """UN/LOCODE → World Port Index harbour size (L/M/S/V).

    Some World Port Index entries carry no UN/LOCODE, so those are matched by
    port name within the same country.
    """

    by_name: dict[tuple[str, str], str] = {}
    for row in unlocode_rows:
        if PORT_FUNCTION not in (row["Function"] or ""):
            continue
        key = (row["Country"], normalize_name(row["NameWoDiacritics"] or row["Name"]))
        by_name.setdefault(key, f"{row['Country']}{row['Location']}")

    ports = json.loads(download(WPI_URL, "world_port_index.json"))["ports"]
    sizes: dict[str, str] = {}
    for port in ports:
        size = port.get("harborSize")
        if not size:
            continue
        # Container terminals count as main ports regardless of harbour size.
        if port.get("loContainer") == "Y":
            size = "L"
        code = (port.get("unloCode") or "").replace(" ", "").upper()
        if not code:
            country = (port.get("countryCode") or "").upper()
            for name in (port.get("portName"), port.get("alternateName")):
                code = by_name.get((country, normalize_name(name)), "")
                if code:
                    break
        if not code:
            continue
        if HARBOR_SIZE_RANK.get(size, 9) < HARBOR_SIZE_RANK.get(sizes.get(code), 9):
            sizes[code] = size
    return sizes


def build_unlocode_index(unlocode_rows: list[dict]) -> dict[str, list]:
    """code → [영문명, 국가코드]. UN/LOCODE의 모든 항구를 담습니다."""

    index = {}
    for row in unlocode_rows:
        if PORT_FUNCTION not in (row["Function"] or ""):
            continue
        code = f"{row['Country']}{row['Location']}"
        if code in index or code in DUPLICATE_CODES:
            continue
        names = {**KOREAN_PORT_ALIASES, **{c: n for c, (n, _) in KOREA_TRADE_PORTS.items()}, **KOREAN_NAMES}
        entry = [title_case(row["NameWoDiacritics"] or row["Name"]), row["Country"]]
        if code in names:
            entry.append(names[code])
        index[code] = entry
    return index


def build() -> list[dict]:
    unlocode = list(csv.DictReader(io.StringIO(download(UNLOCODE_URL, "unlocode_code_list.csv").decode("utf-8", "replace"))))
    iso = json.loads(download(ISO_URL, "iso_3166_regions.json"))
    korean_country = json.loads(download(KOREAN_COUNTRY_URL, "country_names_ko.json"))
    harbor_sizes = load_harbor_sizes(unlocode)

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
        if country_code in EXCLUDED_COUNTRIES:
            continue
        code = f"{country_code}{row['Location']}"
        if code in seen or code in DUPLICATE_CODES:
            continue
        # 국내는 법정 무역항만 노출합니다 (어항·연안항 제외).
        if country_code == "KR" and code not in KOREA_TRADE_PORTS:
            continue
        seen.add(code)
        name_en = title_case(row["NameWoDiacritics"] or row["Name"])
        harbor_size = harbor_sizes.get(code)
        display_names = {**KOREAN_NAMES, **{code: name for code, (name, _) in KOREA_TRADE_PORTS.items()}}
        locations.append({
            "code": code,
            "name": display_names.get(code, name_en),
            "name_en": name_en,
            "city": row["Name"],
            "city_en": name_en,
            "country": info["name"],
            "country_en": info["name_en"],
            "country_code": country_code,
            "region": info["region"],
            "kind": "port",
            "status": row["Status"],
            "harbor_size": harbor_size,
            "port_class": KOREA_TRADE_PORTS.get(code, (None, None))[1],
            "note": PORT_NOTES.get(code, ""),
            "major": code in display_names or harbor_size in MAIN_HARBOR_SIZES,
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
            "status": "",
            "harbor_size": None,
            "port_class": None,
            "note": "",
            "major": True,
        })

    promote_main_ports(locations)
    # 항만 규모 정보가 없고 주요 항구도 아닌 곳은 제외합니다. 무역에 쓰이지 않는
    # 소규모 선착장이 대부분이며, 필요하면 화면에서 "직접 입력"으로 지정합니다.
    locations = [item for item in locations
                 if item["kind"] == "airport" or item["harbor_size"] or item["major"]]
    class_rank = {"national": 0, "local": 1}
    locations.sort(key=lambda item: (
        item["kind"],
        item["country_code"],
        not item["major"],
        class_rank.get(item["port_class"], 0),
        HARBOR_SIZE_RANK.get(item["harbor_size"], 9),
        item["code"],
    ))
    return locations


def promote_main_ports(locations: list[dict]) -> None:
    """Ensure every country offers a few main ports, even without an L/M harbour."""

    by_country: dict[str, list[dict]] = {}
    for item in locations:
        if item["kind"] == "port":
            by_country.setdefault(item["country_code"], []).append(item)

    for ports in by_country.values():
        mains = [port for port in ports if port["major"]]
        if len(mains) >= MIN_MAIN_PORTS_PER_COUNTRY:
            continue
        # Prefer harbours the World Port Index knows about, biggest first.
        rest = sorted(
            (port for port in ports if not port["major"] and port["harbor_size"]),
            key=lambda port: (HARBOR_SIZE_RANK[port["harbor_size"]], port["name_en"]),
        )
        if not rest and not mains:
            # No World Port Index data for this country: fall back to the codes
            # a national authority or customs approved, skipping XXX placeholders.
            rest = sorted(
                (port for port in ports
                 if port["status"] in APPROVED_STATUSES and not port["code"].endswith("XXX")),
                key=lambda port: port["name_en"],
            )
        for port in rest[:MIN_MAIN_PORTS_PER_COUNTRY - len(mains)]:
            port["major"] = True


def write_unlocode_index() -> int:
    rows = list(csv.DictReader(io.StringIO(
        download(UNLOCODE_URL, "unlocode_code_list.csv").decode("utf-8", "replace"))))
    index = build_unlocode_index(rows)
    INDEX_OUTPUT.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return len(index)


if __name__ == "__main__":
    index_size = write_unlocode_index()
    items = build()
    known_codes = {item["code"] for item in items} | set(json.loads(INDEX_OUTPUT.read_text(encoding="utf-8")))
    unmatched = sorted((set(KOREAN_NAMES) | set(KOREA_TRADE_PORTS) | set(PORT_NOTES)
                        | set(KOREAN_PORT_ALIASES)) - known_codes)
    if unmatched:
        print(f"경고: UN/LOCODE에 없는 코드 {len(unmatched)}개 -> {', '.join(unmatched)}")
    OUTPUT.write_text(json.dumps(items, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    ports = [item for item in items if item["kind"] == "port"]
    mains = [item for item in ports if item["major"]]
    print(f"{OUTPUT}: {len(items):,} locations "
          f"(ports {len(ports):,} / airports {len(items) - len(ports):,}, "
          f"countries {len({item['country_code'] for item in items}):,})")
    print(f"{INDEX_OUTPUT}: 전체 UN/LOCODE 항구 색인 {index_size:,}개")
    print(f"  주요 항구 {len(mains):,}곳 / 기타 항구 {len(ports) - len(mains):,}곳 "
          f"(주요 항구 보유 국가 {len({item['country_code'] for item in mains}):,}개국)")
    without_main = {item["country_code"] for item in ports} - {item["country_code"] for item in mains}
    if without_main:
        print(f"  주요 항구 미분류 국가 {len(without_main)}곳: {', '.join(sorted(without_main))}")
