# 사진·스캔 서류 읽기 (Tesseract OCR) 설치

올린 서류가 **사진이거나 글자가 없는 스캔 PDF**일 때 씁니다. 두 가지 일을 합니다.

1. 글자를 읽어 AI에게 그림과 함께 넘깁니다. 숫자·영문 오탈자가 줄어듭니다.
2. **그림 속 계좌번호를 찾아 칠합니다.** 칠한 그림만 바깥(OpenAI)으로 나갑니다.

그래서 OCR이 없으면 사진·스캔 서류는 **받지 않습니다.** 가리지 못한 그림을 보내는 것보다
받지 않는 편이 안전합니다. 글자가 있는 PDF는 OCR 없이도 그대로 읽습니다.

## 설치 (3단계)

```bash
# 1) 프로그램
winget install UB-Mannheim.TesseractOCR     # Windows
brew install tesseract                      # macOS
sudo apt install tesseract-ocr              # Ubuntu

# 2) 한국어·영어 데이터 (약 37MB, git에 넣지 않습니다)
python data/setup_tessdata.py

# 3) 파이썬 패키지
pip install -r requirements.txt
```

## 확인

```bash
python -c "from app.processors import ocr; print(ocr.status())"
```

```
{'package': True, 'program': 'C:\\Program Files\\Tesseract-OCR\\tesseract.exe',
 'tessdata': '...\\forwardus\\data\\tessdata', 'languages': ['kor', 'eng'],
 'ready': True, 'korean': True}
```

`ready: True`면 끝입니다. 화면에서 사진 서류를 올려 보면 "계좌번호 N개를 가린 뒤 AI에 보냈습니다"가 뜹니다.

## 안 될 때

| 증상 | 확인할 것 |
|---|---|
| `package: False` | `pip install pytesseract` |
| `program: ''` | 프로그램이 깔렸는지. 다른 곳에 깔았으면 `.env`의 `TESSERACT_CMD`에 `tesseract.exe` 경로를 적습니다 |
| `korean: False` | `python data/setup_tessdata.py`를 다시 돌립니다. 회사망에서 막히면 `kor.traineddata`를 받아 `data/tessdata/`에 둡니다 |
| 사진을 올렸는데 거절됨 | 위 `ready`가 True인지. 서버를 다시 띄워야 반영됩니다 |

## 서버에 올릴 때

배포 서버에도 같은 3단계가 필요합니다. 도커라면 이미지에 `tesseract-ocr`와
`tesseract-ocr-kor`를 함께 넣고, 언어 데이터 경로를 `TESSDATA_DIR`로 맞추면 됩니다.
