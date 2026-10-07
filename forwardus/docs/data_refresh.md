# 데이터 갱신 절차

앱이 읽는 데이터는 `data/mock/*.json` 입니다. 원자료를 내려받아 `data/build_*.py` 로 만듭니다. **만든 파일은 저장소에 넣어
두므로 평소에는 다시 만들 필요가 없습니다.** 아래는 갱신이 필요할 때의 순서와 확인 방법입니다.

## 준비

```bash
cd forwardus
pip install -r requirements.txt -r data/requirements-build.txt
```

## 순서 (앞 단계의 결과를 뒤 단계가 씁니다)

| 순서 | 명령 | 하는 일 | 산출물 | 갱신 주기 |
|---|---|---|---|---|
| 1 | `python data/build_locations.py` | UN/LOCODE·World Port Index·OurAirports·노선 자료로 항구·공항 목록 생성 | `locations.json`, `unlocode_ports.json`, `country_codes.json` | 연 1회 |
| 2 | `python data/build_sea_links.py` | 한국 항구에서 나라별 직항 여부 | `sea_links.json` | 1번 뒤 |
| 3 | `python data/build_sea_routes.py` | 한국 항구 → 전 세계 항구 해상 거리·길목(searoute) | `sea_routes.json` | 1번 뒤 |
| 4 | `python data/build_extras.py` | 원자료에 없는 세계 주요 항구 추가와 그 항로 | `locations_extra.json`, `sea_routes_extra.json` | 1·3번 뒤(항구를 더할 때) |
| 5 | `python data/build_hsk.py` | HSK 10자리 품목표 | `hsk_codes.json`, `hs_codes.json` | 연 1회(개정 때) |
| 6 | `python data/build_tariff.py` | 관세청 협정세율 | `tariff_rates.json` | 연 1회 |
| 7 | `python data/build_fta.py` | FTA 협정 정보 | `fta_agreements.json` | 협정 발효 때 |
| 8 | `python data/build_standard_names.py` | 표준 품명 | `standard_names.json` | 필요할 때 |
| 9 | `python data/build_clause_topics.py` | 계약서 점검용 주제 | (코드 안 자료) | 규칙을 바꿀 때 |

`build_extras.py` 의 항구 목록은 파일 안 `EXTRA_PORTS` 입니다(실제 UN/LOCODE, 좌표는 근사값). 새 항구를 더하면
`app/collectors/primary_gateways.py` 의 대표 항구 목록에도 넣고 `tests/test_primary_gateways.py` 를 돌립니다.

## 갱신한 뒤 확인

```bash
pytest -q -m "not live and not slow" tests/test_primary_gateways.py tests/test_planning_service.py \
       tests/test_transit_calculator.py tests/test_review_r6_countries.py
```

- 항구·공항을 다시 만들면 `data/mock/locations.json` 의 코드가 바뀔 수 있습니다. 실제 UN/LOCODE 와 이 자료의 코드가 다른 항구는
  `app/collectors/location_client.py` 의 `LOCODE_ALIASES` 로 이어 둡니다(예: CNSHA → CNSGH).
- 나라별 인증·중고품·제재 안내(`country_notes_extra.py`, `used_goods.py`, `trade_controls.py`)는 코드 안 표입니다. 공식 공지가
  바뀌면 그 파일 한 곳만 고칩니다(줄마다 "확인 필요"를 남긴 이유입니다).
- 외부 API(관세청·공공데이터포털)는 키가 있어야 실제 값이 나옵니다. 키가 없으면 해당 기능만 모의(Mock) 값으로 동작하고
  화면에 "Mock"이 표시됩니다.
