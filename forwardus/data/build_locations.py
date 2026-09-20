"""Build data/mock/locations.json from the official UN/LOCODE code list.

Sources
- UN/LOCODE code list (UNECE, mirrored by the Frictionless Data project)
- World Port Index / NGA Pub 150 (harbour size, used to pick each country's
  main trade ports)
- OurAirports (공항 IATA 코드·명칭·규모)
- airline-route-data (국내 공항발 직항 노선 여부)
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

from airport_names_ko import AIRPORT_NAMES_KO

DATA_DIR = Path(__file__).resolve().parent
RAW_DIR = DATA_DIR / "raw"
OUTPUT = DATA_DIR / "mock" / "locations.json"
# 직접 입력한 항구 이름을 실제 코드로 바꾸기 위한 전체 색인 (분류 여부와 무관).
INDEX_OUTPUT = DATA_DIR / "mock" / "unlocode_ports.json"

UNLOCODE_URL = "https://raw.githubusercontent.com/datasets/un-locode/main/data/code-list.csv"
ISO_URL = "https://raw.githubusercontent.com/lukes/ISO-3166-Countries-with-Regional-Codes/master/all/all.json"
KOREAN_COUNTRY_URL = "https://raw.githubusercontent.com/umpirsky/country-list/master/data/ko/country.json"
WPI_URL = "https://msi.nga.mil/api/publications/world-port-index?output=json"
AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
ROUTES_URL = "https://raw.githubusercontent.com/Jonty/airline-route-data/main/airline_routes.json"

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
    "KRPTK": ("평택항", "national"),
    "KRTJI": ("당진항", "national"),
    # 지방관리무역항
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

# 국내 항만 연간 물동량 (만 톤). 목록을 물동량이 많은 항만부터 보여주는 데 씁니다.
# 출처: 해양수산부 항만 물동량 통계 및 보도자료.
#   부산 46,348 / 광양 27,200 / 인천 14,782 (2024년 연간)
#   울산 19,260 / 평택·당진 10,036 (2025년 비컨테이너 기준)
#   동해·묵호 2,812 (2025년 연간)
#   대산 9,010 (대산지방해양수산청 항만소개)
# 나머지 국가관리무역항(포항·군산·목포·마산·여수·경인·장항)은 공개된 연간 수치를
# 확인하지 못해 비워 둡니다. 값이 없으면 목록에서 뒤쪽에 표시됩니다.
KOREA_PORT_VOLUME_MT = {
    "KRPUS": 46348,
    "KRKAN": 27200,
    "KRUSN": 19260,
    "KRINC": 14782,
    "KRPTK": 10036,
    "KRTSN": 9010,
    "KRTGH": 2812,
    "KRMUK": 2812,
}

# 부두·터미널과 모항의 관계. 물동량은 모항 값을 따르고, 목록에서는 모항 다음에 옵니다.
KOREA_PORT_PARENT = {
    "KRBNP": "KRPUS", "KRKCN": "KRPUS",
    "KRONS": "KRUSN", "KRMIP": "KRUSN",
    "KRSHG": "KRKPO", "KRDBL": "KRMOK",
    "KRYOC": "KRYOS", "KRTJI": "KRPTK",
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
# 항공화물 거점 공항.
# - KE: 대한항공 화물이 취항한다고 공식 소개 페이지에 밝힌 도시
#   (cargo.koreanair.com, 2025.08 기준 25개국 44개 도시)
# - HUB: 전 세계 항공화물 처리량 상위 공항과 특송사 허브
# 여객 노선만 있는 공항과 구분해 목록 위에 표시합니다.
KOREAN_AIR_CARGO = {
    "LAX", "JFK", "ORD", "SFO",              # 북미
    "GDL",                                    # 중남미
    "LHR", "FRA", "AMS", "VIE", "OSL", "ZAZ", "BUD",  # 유럽
    "NRT", "KIX", "CGO",                      # 동북아
    "SIN", "SGN", "HAN",                      # 동남아
}
GLOBAL_CARGO_HUBS = {
    # 북미
    "MEM", "SDF", "ANC", "CVG", "MIA", "ATL", "DFW", "IAH", "YYZ", "MEX",
    # 중남미
    "GRU", "VCP", "BOG", "LIM", "SCL", "PTY",
    # 유럽
    "LUX", "LGG", "HHN", "EMA", "STN", "CDG", "BRU", "MXP", "MAD", "ZRH", "IST", "LEJ", "CGN",
    # 중동·아프리카
    "DXB", "DWC", "DOH", "AUH", "RUH", "JED", "BAH", "SHJ", "CAI", "JNB", "NBO", "ADD", "LOS", "CMN",
    # 아시아
    "HKG", "PVG", "PEK", "CAN", "SZX", "TAO", "TSN", "XIY", "HGH", "NKG", "WUH", "CKG", "TFU",
    "TPE", "KHH", "HND", "NGO", "FUK", "KKJ", "KUL", "BKK", "CGK", "MNL", "CEB", "PNH",
    "DEL", "BOM", "BLR", "MAA", "DAC", "CMB",
    # 오세아니아
    "SYD", "MEL", "BNE", "AKL",
}
CARGO_HUBS = KOREAN_AIR_CARGO | GLOBAL_CARGO_HUBS

# 국내 공항. 이 공항들에서 직항편이 있는 해외 공항을 "직항 연결"로 표시합니다.
KOREA_AIRPORTS = {"ICN", "GMP", "PUS", "CJU", "TAE", "CJJ", "MWX", "YNY"}

# 국가별 대표 관문 공항. AIRPORT_OVERRIDES에 없는 국가에서 이 공항이 먼저
# 보이도록 순서를 앞당깁니다.
PRIMARY_AIRPORTS = {
    "PRG", "BUD", "BTS", "OTP", "SOF", "ZAG", "BEG", "VIE", "ZRH", "DUB", "LIS", "ATH",
    "ARN", "OSL", "HEL", "CPH", "LOS", "CMN", "ALG", "TUN", "ADD", "DAR", "EBB", "ACC",
    "TLV", "AMM", "BGW", "IKA", "KWI", "BAH", "MCT", "KHI", "ISB", "DAC", "CMB", "KTM",
    "RGN", "VTE", "KTI", "UBN", "GYD", "ALA", "NQZ", "TAS", "EZE", "SCL", "LIM", "BOG",
    "PTY", "GUA", "SJO", "SDQ", "SAP", "NAN", "FCO", "LGW", "ORY", "CGH", "LED", "TAS",
}

# 한글 표기와 국가별 노출 순서를 지정하는 공항. 나머지 공항은 OurAirports의
# 대형공항(large_airport) 전체를 그대로 싣습니다.
# 값은 (한글명, 영문명 참고용, 국가코드, 국가 내 순위).
AIRPORT_OVERRIDES = {
    "ICN": ("인천국제공항", "Incheon International Airport", "KR", 1),
    "PUS": ("김해국제공항", "Gimhae International Airport", "KR", 3),
    "GMP": ("김포국제공항", "Gimpo International Airport", "KR", 2),
    "CJU": ("제주국제공항", "Jeju International Airport", "KR", 4),
    "TAE": ("대구국제공항", "Daegu International Airport", "KR", 5),
    "CJJ": ("청주국제공항", "Cheongju International Airport", "KR", 6),
    # 광주공항(KWJ)은 국제선이 없는 국내선 전용 공항이라 제외합니다.
    "MWX": ("무안국제공항", "Muan International Airport", "KR", 7),
    "YNY": ("양양국제공항", "Yangyang International Airport", "KR", 8),
    "LAX": ("로스앤젤레스국제공항", "Los Angeles International Airport", "US", 1),
    "JFK": ("뉴욕 JFK 국제공항", "John F. Kennedy International Airport", "US", 2),
    "ORD": ("시카고 오헤어 국제공항", "Chicago O Hare International Airport", "US", 3),
    "SFO": ("샌프란시스코국제공항", "San Francisco International Airport", "US", 7),
    "SEA": ("시애틀 타코마 국제공항", "Seattle-Tacoma International Airport", "US", 8),
    "ATL": ("애틀랜타국제공항", "Hartsfield-Jackson Atlanta International Airport", "US", 5),
    "DFW": ("댈러스포트워스국제공항", "Dallas/Fort Worth International Airport", "US", 6),
    "MIA": ("마이애미국제공항", "Miami International Airport", "US", 4),
    "YVR": ("밴쿠버국제공항", "Vancouver International Airport", "CA", 2),
    "YYZ": ("토론토 피어슨 국제공항", "Toronto Pearson International Airport", "CA", 1),
    "MEX": ("멕시코시티국제공항", "Mexico City International Airport", "MX", 1),
    "GRU": ("상파울루 과룰류스 국제공항", "Sao Paulo/Guarulhos International Airport", "BR", 1),
    "PVG": ("상하이 푸둥 국제공항", "Shanghai Pudong International Airport", "CN", 1),
    "CAN": ("광저우 바이윈 국제공항", "Guangzhou Baiyun International Airport", "CN", 2),
    "PEK": ("베이징 서우두 국제공항", "Beijing Capital International Airport", "CN", 3),
    "SZX": ("선전 바오안 국제공항", "Shenzhen Baoan International Airport", "CN", 4),
    "HGH": ("항저우 샤오산 국제공항", "Hangzhou Xiaoshan International Airport", "CN", 5),
    "CGO": ("정저우 신정 국제공항", "Zhengzhou Xinzheng International Airport", "CN", 6),
    "CKG": ("충칭 장베이 국제공항", "Chongqing Jiangbei International Airport", "CN", 7),
    "TFU": ("청두 톈푸 국제공항", "Chengdu Tianfu International Airport", "CN", 8),
    "TAO": ("칭다오 자오둥 국제공항", "Qingdao Jiaodong International Airport", "CN", 9),
    "SHA": ("상하이 훙차오 국제공항", "Shanghai Hongqiao International Airport", "CN", 10),
    "XMN": ("샤먼 가오치 국제공항", "Xiamen Gaoqi International Airport", "CN", 11),
    "NKG": ("난징 루커우 국제공항", "Nanjing Lukou International Airport", "CN", 12),
    "TSN": ("톈진 빈하이 국제공항", "Tianjin Binhai International Airport", "CN", 13),
    "PKX": ("베이징 다싱 국제공항", "Beijing Daxing International Airport", "CN", 14),
    "HKG": ("홍콩국제공항", "Hong Kong International Airport", "HK", 1),
    "TPE": ("타이완 타오위안 국제공항", "Taiwan Taoyuan International Airport", "TW", 1),
    "NRT": ("나리타국제공항", "Narita International Airport", "JP", 1),
    "HND": ("하네다공항", "Tokyo Haneda Airport", "JP", 3),
    "KIX": ("간사이국제공항", "Kansai International Airport", "JP", 2),
    "NGO": ("주부 센트레아 국제공항", "Chubu Centrair International Airport", "JP", 4),
    "FUK": ("후쿠오카공항", "Fukuoka Airport", "JP", 5),
    "SIN": ("싱가포르 창이공항", "Singapore Changi Airport", "SG", 1),
    "BKK": ("수완나품국제공항", "Suvarnabhumi Airport", "TH", 1),
    "SGN": ("떤선녓국제공항", "Tan Son Nhat International Airport", "VN", 1),
    "HAN": ("노이바이국제공항", "Noi Bai International Airport", "VN", 2),
    "KUL": ("쿠알라룸푸르국제공항", "Kuala Lumpur International Airport", "MY", 1),
    "CGK": ("수카르노하타국제공항", "Soekarno-Hatta International Airport", "ID", 1),
    "MNL": ("니노이 아키노 국제공항", "Ninoy Aquino International Airport", "PH", 1),
    "DEL": ("인디라 간디 국제공항", "Indira Gandhi International Airport", "IN", 1),
    "BOM": ("차트라파티 시바지 국제공항", "Chhatrapati Shivaji International Airport", "IN", 2),
    "MAA": ("첸나이국제공항", "Chennai International Airport", "IN", 3),
    "DXB": ("두바이국제공항", "Dubai International Airport", "AE", 1),
    "AUH": ("아부다비국제공항", "Abu Dhabi International Airport", "AE", 2),
    "DOH": ("하마드국제공항", "Hamad International Airport", "QA", 1),
    "RUH": ("킹 칼리드 국제공항", "King Khalid International Airport", "SA", 1),
    "IST": ("이스탄불공항", "Istanbul Airport", "TR", 1),
    "FRA": ("프랑크푸르트공항", "Frankfurt Airport", "DE", 1),
    "MUC": ("뮌헨공항", "Munich Airport", "DE", 2),
    "AMS": ("암스테르담 스히폴공항", "Amsterdam Airport Schiphol", "NL", 1),
    "LHR": ("런던 히스로공항", "London Heathrow Airport", "GB", 1),
    "CDG": ("파리 샤를드골공항", "Paris Charles de Gaulle Airport", "FR", 1),
    "LUX": ("룩셈부르크공항", "Luxembourg Airport", "LU", 1),
    "LGG": ("리에주공항", "Liege Airport", "BE", 1),
    "BRU": ("브뤼셀공항", "Brussels Airport", "BE", 2),
    "MAD": ("마드리드 바라하스공항", "Adolfo Suarez Madrid-Barajas Airport", "ES", 1),
    "MXP": ("밀라노 말펜사공항", "Milan Malpensa Airport", "IT", 1),
    "WAW": ("바르샤바 쇼팽공항", "Warsaw Chopin Airport", "PL", 1),
    "SVO": ("셰레메티예보국제공항", "Sheremetyevo International Airport", "RU", 1),
    "CAI": ("카이로국제공항", "Cairo International Airport", "EG", 1),
    "JNB": ("요하네스버그 OR탐보 국제공항", "O. R. Tambo International Airport", "ZA", 1),
    "NBO": ("조모 케냐타 국제공항", "Jomo Kenyatta International Airport", "KE", 1),
    "SYD": ("시드니공항", "Sydney Airport", "AU", 1),
    "MEL": ("멜버른공항", "Melbourne Airport", "AU", 2),
    "BNE": ("브리즈번공항", "Brisbane Airport", "AU", 3),
    "AKL": ("오클랜드공항", "Auckland Airport", "NZ", 1),
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
            "direct_from_korea": None,
            "cargo_hub": False,
            "korean_air_cargo": False,
            "transfer_via": [],
            "gateway_only": False,
            "port_class": KOREA_TRADE_PORTS.get(code, (None, None))[1],
            "note": PORT_NOTES.get(code, ""),
            "size_rank": None,
            "cargo_volume_mt": KOREA_PORT_VOLUME_MT.get(KOREA_PORT_PARENT.get(code, code)),
            "is_terminal": code in KOREA_PORT_PARENT,
            "port_group": KOREA_PORT_PARENT.get(code, code),
            "major": code in display_names or harbor_size in MAIN_HARBOR_SIZES,
        })

    locations.extend(build_airports(country_info))

    attach_transfer_hub_names(locations)
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
        not (item["kind"] == "airport" and item["cargo_hub"] and item["direct_from_korea"]),
        item["direct_from_korea"] is False,
        item["size_rank"] or 99,
        -(item["cargo_volume_mt"] or 0),
        item["port_group"],
        item["is_terminal"],
        HARBOR_SIZE_RANK.get(item["harbor_size"], 9),
        item["code"],
    ))
    return locations


# 환승 공항에 안내할 경유 후보 수.
MAX_TRANSFER_HUBS = 3


def load_route_data() -> tuple[set[str], dict[str, list[str]]]:
    """국내 직항 공항 목록과, 환승 공항별 경유 후보를 만듭니다.

    경유 후보는 "국내에서 직항으로 갈 수 있고, 그곳에서 목적 공항까지
    다시 직항편이 있는" 공항입니다. 운항 항공사 수가 많은 곳을 먼저 둡니다.
    """

    data = json.loads(download(ROUTES_URL, "airline_routes.json"))
    direct = {route["iata"] for code in KOREA_AIRPORTS
              for route in data.get(code, {}).get("routes", [])} - KOREA_AIRPORTS

    transfers: dict[str, list[str]] = {}
    for iata, airport in data.items():
        if iata in direct or iata in KOREA_AIRPORTS:
            continue
        hubs = [(len(route.get("carriers", [])), route["iata"])
                for route in airport.get("routes", []) if route["iata"] in direct]
        hubs.sort(key=lambda item: (-item[0], item[1]))
        if hubs:
            transfers[iata] = [code for _, code in hubs[:MAX_TRANSFER_HUBS]]
    return direct, transfers


def build_airports(country_info: dict[str, dict]) -> list[dict]:
    """정기편이 다니는 IATA 공항 목록 (OurAirports 기준).

    대형공항(large_airport)은 모두 싣고, 중형공항은 화물 거점으로 직접 지정한
    공항(AIRPORT_OVERRIDES)만 포함합니다.
    """

    rows = list(csv.DictReader(io.StringIO(
        download(AIRPORTS_URL, "ourairports_airports.csv").decode("utf-8", "replace"))))
    direct_routes, transfer_hubs = load_route_data()

    airports = []
    seen = set()
    for row in rows:
        iata = row["iata_code"].strip().upper()
        country_code = row["iso_country"].strip().upper()
        info = country_info.get(country_code)
        if not iata or iata in seen or not info:
            continue
        if row["scheduled_service"] != "yes":
            continue
        is_large = row["type"] == "large_airport"
        override = AIRPORT_OVERRIDES.get(iata)
        if not is_large and not override:
            continue
        seen.add(iata)

        name_en = row["name"].strip()
        city = (row["municipality"] or "").strip()
        name_ko = override[0] if override else AIRPORT_NAMES_KO.get(iata, "")
        airports.append({
            "code": iata,
            "name": name_ko or name_en,
            "name_en": name_en,
            "city": city or name_en,
            "city_en": city or name_en,
            "country": info["name"],
            "country_en": info["name_en"],
            "country_code": country_code,
            "region": info["region"],
            "kind": "airport",
            "status": "",
            "harbor_size": None,
            "port_class": None,
            "note": "",
            "cargo_volume_mt": None,
            "is_terminal": False,
            "port_group": iata,
            # 직접 지정한 순서를 먼저 쓰고, 나머지는 대형 -> 중형 순입니다.
            "size_rank": (override[3] if override
                          else 10 if iata in PRIMARY_AIRPORTS
                          else 50 if is_large else 60),
            # 국내 공항에서 직항편이 있는지. 없으면 경유 후보를 함께 보여줍니다.
            # 국내 공항은 출발지이므로 판정 대상이 아닙니다(None).
            "direct_from_korea": None if country_code == "KR" else iata in direct_routes,
            "cargo_hub": iata in CARGO_HUBS,
            "korean_air_cargo": iata in KOREAN_AIR_CARGO,
            "transfer_via": ([] if country_code == "KR" or iata in direct_routes
                             else transfer_hubs.get(iata, [])),
            "gateway_only": False,
            "major": is_large or bool(override),
        })

    wrong_country = [code for code, value in AIRPORT_OVERRIDES.items()
                     if code in seen and value[2] != next(a["country_code"] for a in airports if a["code"] == code)]
    missing = sorted(set(AIRPORT_OVERRIDES) - seen)
    if missing:
        print(f"경고: OurAirports에 없는 공항 코드 {len(missing)}개 -> {', '.join(missing)}")
    if wrong_country:
        print(f"경고: 국가 코드가 다른 공항 {len(wrong_country)}개 -> {', '.join(wrong_country)}")
    unknown_ko = sorted(set(AIRPORT_NAMES_KO) - seen)
    if unknown_ko:
        print(f"경고: 한글 표기만 있고 데이터에 없는 공항 {len(unknown_ko)}개 -> {', '.join(unknown_ko)}")
    return airports


def attach_transfer_hub_names(locations: list[dict]) -> None:
    """경유 후보 코드를 [코드, 이름] 형태로 바꾸고, 국제선이 없는 공항은
    같은 나라의 관문 공항을 안내합니다. (예: 상파울루 콩고냐스 -> 과룰류스)"""

    airports = [item for item in locations if item["kind"] == "airport"]
    names = {item["code"]: item["name"] for item in airports}

    # 나라별 대체 관문: 직항 > 화물 거점 > 경유 안내가 있는 공항 순.
    gateways: dict[str, dict] = {}
    for item in airports:
        current = gateways.get(item["country_code"])
        score = (item["direct_from_korea"], item["cargo_hub"], bool(item["transfer_via"]),
                 -(item["size_rank"] or 99))
        if not current or score > current["score"]:
            gateways[item["country_code"]] = {"score": score, "item": item}

    for item in airports:
        if item["direct_from_korea"] is None:
            continue  # 국내 공항(출발지)에는 환승 안내를 붙이지 않습니다.
        if item["transfer_via"]:
            item["transfer_via"] = [[code, names.get(code, code)] for code in item["transfer_via"]
                                    if code in names]
            continue
        if item["direct_from_korea"]:
            continue
        # 국제선 노선 자체가 없는 공항: 같은 나라 관문 공항을 이용합니다.
        gateway = gateways.get(item["country_code"], {}).get("item")
        if gateway and gateway["code"] != item["code"]:
            item["transfer_via"] = [[gateway["code"], gateway["name"]]]
            item["gateway_only"] = True


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
    airports = [item for item in items if item["kind"] == "airport"]
    direct = [a for a in airports if a["direct_from_korea"]]
    with_hub = [a for a in airports if a["transfer_via"]]
    cargo = [a for a in airports if a["cargo_hub"]]
    print(f"  공항 {len(airports):,}곳 (국가 {len({a['country_code'] for a in airports})}개국) "
          f"· 국내 직항 연결 {len(direct)}곳 · 화물 거점 {len(cargo)}곳 · 경유 안내 {len(with_hub)}곳")
    print(f"  주요 항구 {len(mains):,}곳 / 기타 항구 {len(ports) - len(mains):,}곳 "
          f"(주요 항구 보유 국가 {len({item['country_code'] for item in mains}):,}개국)")
    without_main = {item["country_code"] for item in ports} - {item["country_code"] for item in mains}
    if without_main:
        print(f"  주요 항구 미분류 국가 {len(without_main)}곳: {', '.join(sorted(without_main))}")
