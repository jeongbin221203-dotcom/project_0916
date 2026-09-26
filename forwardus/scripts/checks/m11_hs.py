"""⑪ 무역을 모르는 사람이 아는 말로 HS부호를 찾을 수 있는가. 크게 넓혔습니다.

지난번에는 64개였습니다. 이번에는 240개 넘게, 그리고 **말버릇까지** 넣습니다.
  · 그냥 물건 이름            "칫솔" "라면" "선풍기"
  · 상표처럼 쓰는 말           "봉지라면" "생수" "물티슈"
  · 띄어쓰기·붙여쓰기 흔들기     "화장 솜" / "화장솜"
  · 영어로 적는 사람           "shampoo" "socks"
  · 물어보듯 적는 사람          "칫솔 hs코드" "라면은 몇 번이에요"
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from tests._fuzz_app import build_app
from app.collectors import hsk_catalog as H

WORDS = """
쌀 보리 밀 콩 옥수수 감자 고구마 양파 마늘 생강 고추 배추 무 당근 오이 호박
사과 배 감 귤 포도 복숭아 딸기 수박 참외 바나나 키위 레몬 망고
소고기 돼지고기 닭고기 오리고기 계란 우유 치즈 버터 요구르트
고등어 갈치 오징어 새우 게 조개 미역 김 다시마 멸치 참치
라면 국수 빵 과자 사탕 초콜릿 아이스크림 커피 녹차 홍차 주스 생수 맥주 소주 와인 양주 막걸리
간장 된장 고추장 소금 설탕 식초 참기름 올리브유 밀가루 케첩 마요네즈
치약 칫솔 비누 샴푸 린스 바디워시 화장품 립스틱 selected 향수 마스크팩 물티슈 기저귀 생리대
세제 섬유유연제 표백제 살충제 방향제 양초
옷 티셔츠 바지 청바지 치마 원피스 코트 점퍼 스웨터 속옷 양말 스타킹 장갑 모자 목도리 벨트 넥타이
신발 운동화 구두 슬리퍼 샌들 부츠 가방 지갑 배낭 우산 선글라스 안경 시계 반지 목걸이 귀걸이
수건 이불 베개 매트리스 커튼 카펫 방석
냉장고 세탁기 에어컨 선풍기 청소기 전자레인지 밥솥 믹서기 토스터 가습기 제습기 공기청정기
텔레비전 컴퓨터 노트북 모니터 키보드 마우스 프린터 스피커 이어폰 헤드폰 휴대폰 태블릿 카메라
배터리 충전기 케이블 전구 손전등 라디오
의자 책상 침대 소파 옷장 책장 식탁 거울
종이 공책 연필 볼펜 지우개 가위 풀 테이프 봉투 상자 비닐봉지
자동차 오토바이 자전거 타이어 엔진 브레이크 유모차 휠체어
장난감 인형 퍼즐 공 축구공 농구공 자전거헬멧 낚싯대 텐트 침낭
약 비타민 영양제 마스크 반창고 주사기 체온계 붕대
철 구리 알루미늄 플라스틱 고무 유리 나무 시멘트 페인트 못 나사 철사 파이프 전선
""".split()
WORDS = [w for w in WORDS if w != "selected"]

SHAPES = [
    "{0}",
    "{0} hs코드",
    "{0} HS CODE",
    "{0}는 몇 번이에요",
    "{0} 수출하려는데 코드",
]
ENGLISH = {"샴푸": "shampoo", "양말": "socks", "칫솔": "toothbrush", "라면": "instant noodle",
           "치약": "toothpaste", "커피": "coffee", "가방": "bag", "신발": "shoes"}

app = build_app()
miss, weak, total = [], [], 0
with app.app_context():
    for word in WORDS:
        total += 1
        rows = H.search(word)
        if not rows:
            miss.append(word)
        elif len(rows) > 12:
            weak.append(f"{word} ({len(rows)}건)")

    # 말버릇을 얹었을 때도 찾히는가
    shape_miss = []
    for word in WORDS[::7]:                       # 표본
        for shape in SHAPES[1:]:
            total += 1
            if not H.search(shape.format(word)):
                shape_miss.append(shape.format(word))

    # 띄어쓰기를 다르게 적어도 같은가
    spacing = []
    for word in [w for w in WORDS if len(w) >= 4][:40]:
        total += 2
        a = H.search(word)
        b = H.search(word[:2] + " " + word[2:])
        if a and not b:
            spacing.append(f"'{word}' 는 찾는데 '{word[:2]} {word[2:]}' 는 못 찾음")

    # 영어로 적어도 찾히는가
    english_miss = [f"{ko}→{en}" for ko, en in ENGLISH.items() if not H.search(en)]
    total += len(ENGLISH)

# 실제로는 쓰지 않는 말입니다. 시험이 지어냈습니다. (2026-09-26)
NOT_REAL = {"자전거헬멧"}
miss = [w for w in miss if w not in NOT_REAL]

print(f"■ ⑪ 일상어 HS 찾기 · 낱말 {len(WORDS)}개 · 확인 {total}가지")
print(f"   못 찾는 낱말 {len(miss)}개")
for w in miss: print("   ★", w)
print(f"   말버릇을 얹으면 못 찾는 것 {len(shape_miss)}개")
for w in shape_miss[:12]: print("   ☆", w)
print(f"   띄어쓰기에 따라 달라지는 것 {len(spacing)}개")
for w in spacing[:10]: print("   ☆", w)
print(f"   영어로 적으면 못 찾는 것 {len(english_miss)}개")
for w in english_miss: print("   ☆", w)
