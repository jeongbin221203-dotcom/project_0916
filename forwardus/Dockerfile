# FORWARDUS 배포 이미지
#
# 왜 도커로 바꿨나
#   render.yaml 이 쓰던 python 런타임은 `pip install` 만 할 수 있습니다.
#   그런데 이 프로그램은 **pip 로 못 까는 것 두 가지**가 있어야 제대로 돕니다.
#
#     1) Tesseract OCR      사진·스캔 서류의 글자를 읽고, 그림 속 계좌번호를 칠합니다.
#                           없으면 사진 서류를 아예 못 받습니다(안전하게 거절).
#     2) 한글 글꼴          서류 PDF 를 그립니다.
#                           없으면 **모든 서류 만들기가 멈춥니다.**
#                           (네모로 찍힌 서류를 내주면 은행·세관에서 반송되므로,
#                            일부러 만들지 않고 멈추게 해 두었습니다)
#
#   docs/ocr_setup.md 에 "배포 서버에도 같은 3단계가 필요합니다"라고 적어 두었는데
#   render.yaml 에는 그 3단계가 없었습니다. (2026-09-27 확인)

FROM python:3.12-slim

# tesseract-ocr / -kor / -eng   글자 읽기. 무역서류는 한글 이름표 + 영문 값이 섞입니다.
# fonts-nanum                   서류 PDF 의 한글. document_form.py 가 찾는 바로 그 경로에 깔립니다
#                               (/usr/share/fonts/truetype/nanum/NanumGothic.ttf)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-kor \
        tesseract-ocr-eng \
        fonts-nanum \
    && rm -rf /var/lib/apt/lists/*

# Debian bookworm 의 Tesseract 5 가 언어 데이터를 두는 곳.
# app/processors/ocr.py 가 이 값을 먼저 봅니다.
ENV TESSDATA_DIR=/usr/share/tesseract-ocr/5/tessdata \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# requirements 를 먼저 넣습니다. 코드만 바뀐 배포에서 pip 단계를 건너뜁니다.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# **이미지를 만들 때** 확인합니다.
#
# 여기서 틀리면 배포가 아니라 빌드가 실패합니다. 사진을 못 읽거나 서류를 못 만드는
# 서버가 조용히 떠 있는 일이 없습니다 — 지금까지가 정확히 그 상태였습니다.
RUN tesseract --list-langs 2>&1 | grep -qx 'kor' \
    && python -c "import sys; from app.processors import document_form as d; sys.exit(0 if d.fonts_ready() else 1)" \
    && echo "OCR 한국어 · 한글 글꼴 둘 다 확인됨"

# Render 가 $PORT 를 줍니다. exec 꼴로 쓰면 $PORT 가 안 풀리므로 shell 꼴로 둡니다.
# --timeout 은 AI 서류 읽기(최대 90초)보다 넉넉해야 합니다. 짧으면 큰 PDF 를
# 읽는 도중에 일꾼이 끊겨 "읽지 못했습니다"가 됩니다.
CMD gunicorn --bind "0.0.0.0:${PORT:-10000}" \
    --workers 2 --threads 4 --timeout 150 \
    --access-logfile - --error-logfile - \
    "app:create_app()"
