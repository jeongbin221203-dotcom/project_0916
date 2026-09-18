# Forwardus Flask

수출입 운송 경로, 인코텀즈, 화물 정보, 스케줄과 상세 비용을 단계별로 비교하는 Flask 기반 포워딩 견적 프로토타입입니다.

## 주요 기능

- HOME → 운송 경로 → 인코텀즈 → 화물 정보 → 스케줄 → 최종 견적 이동
- 수출 시 대한민국 출발지 자동 고정
- 수입 시 대한민국 도착지 자동 고정
- 카톤 박스, 팔레트, 목재 상자, 드럼, 플렉시블 백 지원
- CBM, R/T, 항공 청구중량 및 보험료 계산
- 운임, 서류비, 창고료, 통관비, 관세 상세 표시
- 모바일·태블릿·데스크톱 반응형 UI
- 향후 실제 API로 교체 가능한 collector / processor 분리

현재 환율, 스케줄, HS CODE와 비용 데이터는 프로토타입용 예상값입니다.

## 로컬 실행

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

macOS / Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

브라우저에서 `http://127.0.0.1:5000`을 엽니다.

## Render 배포

- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app`
- Health Check Path: `/health`

저장소의 `render.yaml`을 사용하면 위 설정이 자동 적용됩니다.

