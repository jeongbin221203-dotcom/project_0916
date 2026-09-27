"""발표 질의응답 대비 자료를 **PDF 한 장짜리 문서**로 그립니다.

왜 필요한가
  질의응답 자료를 웹 페이지로 만들어 두었는데, 그 페이지에서는 인쇄나 내려받기
  단추를 달 수 없습니다(보안상 막혀 있습니다). 발표장에서 노트북이 안 되거나
  인쇄해서 손에 들고 싶을 때 쓸 파일이 필요합니다.

어떻게 그리나
  reportlab 으로 **글자를 진짜 글자로** 넣습니다. 그래서 PDF 안에서 검색과
  복사가 됩니다.

  처음에는 Pillow 로 그림을 그려 PDF 로 저장했습니다(상업송장을 그리는 방식).
  모양은 같지만 **글자가 그림이라 검색이 안 됐습니다.** 발표장에서 질문을
  받고 낱말로 찾아야 하는 자료인데, 검색이 안 되면 쓸모가 절반입니다.
  (2026-09-27 사용자 지적)

  한글 글꼴은 document_form 이 쓰는 것과 같은 것을 찾아 PDF 에 심습니다.
  **글꼴을 못 찾으면 만들지 않고 멈춥니다.** 글자가 전부 네모로 나온 PDF 를
  만들어 두면, 인쇄해서 들고 간 뒤에야 알게 됩니다.

    python scripts/make_qna_pdf.py
    python scripts/make_qna_pdf.py --out C:/내문서/질의응답.pdf
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw

from app.processors.document_form import _font as load_font

# A4 를 150dpi 로 그립니다. 인쇄해도 글자가 또렷하고 파일이 너무 크지 않습니다.
WIDTH, HEIGHT = 1240, 1754
MARGIN = 70
LINE = 26

INK = (22, 32, 46)
BODY = (70, 86, 107)
MUTED = (122, 136, 153)
BLUE = (31, 111, 178)
AMBER = (180, 83, 9)
GREEN = (21, 128, 61)
LINE_COLOR = (226, 230, 235)
BAND = (238, 245, 252)

# (분야, [(질문, 표시, [답 줄...]), ...])
# 표시: "hard" 먼저 말하기 · "sure" 자신 있게 · "" 보통
DATA = [
    ("기술·구조", [
        ("임베딩(벡터) 쓰나요?", "sure", [
            "씁니다. 안 쓰는 것은 벡터 '데이터베이스'입니다.",
            "FAQ 100건을 text-embedding-3-small 로 미리 벡터로 만들어 두고(1536차원),",
            "낱말 점수와 0.5 : 0.5 로 섞습니다. 낱말 점수 안에서도 BM25 와 2-gram 을 섞습니다.",
            "Chroma·FAISS 같은 저장소는 두지 않았습니다 — 100건 규모에서는 JSON 파일에",
            "담아 코사인만 셈하면 충분하고, 저장소를 두면 운영할 것만 늘어납니다.",
        ]),
        ("왜 LangChain 을 통째로 쓰지 않았나요?", "", [
            "langchain-core 네 조각만 씁니다. (검색기·도구·흐름·시간 기록)",
            "langchain-openai 를 붙이면 openai SDK 가 따라오고 이미 도는 코드를 바꿔야 합니다.",
            "무엇을 조회할지는 우리가 이미 알기 때문에 AgentExecutor 는 맡길 이유가 없습니다.",
        ]),
        ("AI 가 HS코드를 정해 주나요?", "hard", [
            "아니요. 후보를 좁혀 주고 근거를 붙일 뿐입니다.",
            "품목분류는 세관이 정합니다. 어느 화면에서도 '이 부호로 신고하세요'라고",
            "말하지 않습니다. 관세청 표준품명이 글자까지 맞으면 그것을 1순위로 올립니다.",
        ]),
        ("계산은 누가 하나요? AI 가 하면 위험하지 않나요?", "sure", [
            "코드가 합니다. AI 는 숫자에 손대지 않습니다.",
            "금액·부피는 Decimal 로 셈하고, 화면이 보낸 금액도 서버가 다시 더합니다.",
            "부동소수점으로 곱하던 때는 30만 건 중 6,049건에서 1센트가 어긋났습니다.",
            "신용장은 은행이 되셈하므로 1센트 차이가 반송 사유입니다.",
        ]),
    ]),
    ("데이터·API", [
        ("API 키가 정지되면 못 쓰는 거 아닌가요?", "sure", [
            "키가 정지돼도 21가지 중 16가지가 답합니다.",
            "관세율표(11,326부호)·표준품명(2,646개)·국가코드표(254개)·품목표(11,327개)를",
            "파일로 굳혀 두었습니다. 공공데이터포털 파일 내려받기라 키가 필요 없습니다.",
            "기관을 하나씩 막아 보니 무관한 조회가 같이 죽는 일은 0건이었습니다.",
        ]),
        ("굳혀 둔 표가 낡으면 틀린 값을 보여 주는 거 아닌가요?", "hard", [
            "맞습니다. 그래서 기준일을 함께 보여 줍니다. (관세율표 2026-02-11 기준)",
            "출처를 'internal' 로 적어 방금 받은 값과 구분하고, 화면에",
            "'기관에 직접 물은 값이 아니니 신고 전에 확인하세요'를 붙입니다.",
            "관세율은 연 1회 개정이라 확인 주기를 팀이 정해야 합니다 — 약점 목록에 있습니다.",
        ]),
        ("기관이 멈추면 값을 지어내나요?", "sure", [
            "지어내지 않습니다. 출처를 넷으로 나눠 표시합니다.",
            "api(방금 받음) · stored/cache(받아 둔 값) · internal(굳혀 둔 표) · mock(예시).",
            "09-27 검사에서 받아 둔 값을 'api' 라 적던 10군데를 찾아 고쳤습니다. 지금은 0건.",
        ]),
        ("43종을 다 연결했다는데 정말인가요?", "hard", [
            "42종입니다. 빠진 하나는 HMM 선사 스케줄입니다.",
            "코드는 붙어 있고 키만 없습니다. 키를 넣으면 코드 변경 없이 실데이터로 바뀝니다.",
            "그때까지 화면에 '예시 스케줄 — API 키가 없어 추정치입니다'라고 적습니다.",
        ]),
        ("관세율이 조회 안 되는 품목이 있다고 들었는데요?", "hard", [
            "그건 우리 잘못이었습니다. 09-27 에 찾았습니다.",
            "미등재라 적어 둔 3304990000·8507600000·8708299000 은 존재하지 않는 부호였습니다.",
            "기관이 '없다'고 답한 것이 맞았고, 우리가 그걸 기관 탓으로 적어 두었습니다.",
            "실제 부호는 3304991000·8507602000·8708290000 입니다.",
        ]),
    ]),
    ("정확성·검증", [
        ("테스트는 몇 개이고 다 통과하나요?", "sure", [
            "1,668개 전부 통과합니다. 실패 0. (+ JavaScript 40개)",
            "무작위 검증 45종을 따로 돌립니다 — 퍼즈·독립 검산·정적 검사·단절 검사.",
            "아침까지 5건이 실패했는데, 굳혀 둔 표가 그 자리를 채워 전부 통과했습니다.",
        ]),
        ("한 번 통과했다고 안전한 건가요?", "", [
            "아니라고 보고 여러 번 돌립니다. 회차마다 무작위 씨앗을 바꿉니다.",
            "계산 독립 검산 1만 회·28만 가지 / 서류 간 어긋남 1만 부·5축 /",
            "모순 입력 1만 회·19가지 / 사업자번호·컨테이너번호 각 10만 개.",
        ]),
        ("실제로 무슨 오류를 찾았나요?", "sure", [
            "21건입니다. 전부 화면이 정상으로 보이던 것들입니다.",
            "금액 1센트 어긋남(30만 중 6,049건) · 글꼴 없는 서버에서 서류가 통째로 네모 ·",
            "환율 표를 검사 없이 사용 · 한국어 계약서 독소조항 10개 중 7개 미검출 ·",
            "[만들기] 두 번에 건 2개 생성 · 불소 치약을 화장품으로 안내(미국은 OTC 의약품).",
        ]),
        ("HS 검색이 정확한가요?", "sure", [
            "말버릇을 얹어 4,086회 재서 전부 100% 입니다.",
            "기업 201 · 개인 259 · 기존 196 · 일상어 226낱말에 말버릇 8가지를 얹습니다.",
            "'반도체'는 맞는데 '반도체 HS코드'라고 적으면 2807 황산이 1순위이던 것을 고쳤습니다.",
        ]),
        ("서류 검증은 다수결인가요?", "", [
            "아니요. 건의 기준값과 맞댑니다.",
            "5장 중 1장만 맞고 4장이 틀려도 틀린 4장을 지적합니다. 다수결이면 반대로 잡습니다.",
            "1만 건 검증에서 잡는 비율 100% 입니다.",
        ]),
    ]),
    ("한계·약점", [
        ("운임이 정확한가요?", "hard", [
            "추정값입니다. 실제 청구액과 다를 수 있습니다.",
            "선사가 운임을 공개하지 않아 표준단가표로 어림합니다. 화면에도 추정이라 적습니다.",
            "다음 후보는 포워더 견적을 받아 넣는 흐름이나 계약운임 입력란입니다.",
        ]),
        ("규정 정보는 믿을 수 있나요?", "hard", [
            "수출요건·미국 의약품 분류는 우리가 손으로 적은 표입니다.",
            "법이 바뀌면 사람이 고쳐야 합니다. 그래서 단정하지 않고",
            "'확인해야 할 것'으로 안내하며 조회처를 함께 답니다.",
            "관세사 검수와 개정 확인 주기를 정해야 합니다.",
        ]),
        ("AI 가 없으면 못 쓰는 건가요?", "", [
            "서류 읽기와 상담만 그렇습니다.",
            "견적·서류 작성·검증·통관 조회는 AI 없이 돕니다.",
            "비용·한도 정책은 아직 없습니다 — 운영 정책을 팀이 세워야 합니다.",
        ]),
        ("승인된 FAQ 가 0건이면 그 기능은 안 도는 거죠?", "hard", [
            "맞습니다. AI 없이 바로 답하는 경로는 아직 한 번도 돌지 않았습니다.",
            "FAQ 100건 모두 '전문가 검토 필요' 상태입니다. 미승인은 AI 에게 근거로만 넘깁니다.",
            "설계대로 안전한 쪽으로 넘어가는 것이고, 관세사 검토 패킷은 만들어 두었습니다.",
        ]),
        ("실사용자 검증은 했나요?", "hard", [
            "아직 안 했습니다.",
            "지금까지는 기계적 검증입니다 — 테스트 1,668개, 무작위 검증 45종, 실키 검사.",
            "AI 끼리 상호 검토도 미착수입니다. 이 둘이 남은 가장 큰 빈칸입니다.",
        ]),
    ]),
    ("팀·운영", [
        ("팀에서 어떤 부분을 맡았나요?", "", [
            "JB — 정확성 검증 · 서류 · 통관 · 데이터 굳히기",
            "yoonsu — LangChain 상담 체인 · FAQ 검색 · 대시보드",
            "minseol — HS 검색 · 컨테이너 조회 · 글꼴   그 밖에 JH · hyeonseo · pro0916",
            "09-27 기준 yoonsu·pro0916 은 JB 와 같게 맞춰 원격에도 올렸습니다.",
        ]),
        ("개발 기간이 12일인데 이게 가능한가요?", "hard", [
            "커밋 105건, 파이썬 파일 115개, 테스트 파일 93개입니다.",
            "AI 코딩 도구를 썼습니다. 숨길 것이 아니라 그래서 검증에 시간을 더 썼습니다 —",
            "검증 스크립트가 39개이고 여러 개가 '우리 코드가 거짓말하지 않는지'를 봅니다.",
            "실제로 그 검사들이 우리 자신의 오류 21건을 잡았습니다.",
        ]),
    ]),
    ("곤란한 질문", [
        ("이거 AI 가 만든 거 아니에요?", "hard", [
            "AI 코딩 도구를 썼습니다. 그래서 검증을 더 했습니다.",
            "빠르게 만든 코드는 그럴듯하게 틀립니다. 그걸 알기 때문에 검증을 39개 만들고,",
            "상당수를 '우리 코드가 사용자에게 거짓말하지 않는지' 보는 데 썼습니다.",
            "실제로 잡았습니다 — 받아 둔 값을 '방금 받았다'고 적던 10군데,",
            "이용자에게 '.env 에 키를 넣으세요'라고 말하던 9군데, 없는 HS부호 3건.",
        ]),
        ("그래서 이걸 실제로 써도 되나요?", "hard", [
            "관세사 검수 전에는 참고용입니다.",
            "계산(금액·CBM·운임톤)과 서류 간 대조는 믿고 쓰실 수 있습니다 —",
            "독립 검산과 대량 검증을 거쳤습니다. 통관 조회도 관세청 값 그대로입니다.",
            "규정 판단은 아직 참고용입니다. 그래서 '해도 된다/안 된다'로 답하지 않습니다.",
        ]),
        ("경쟁 서비스와 뭐가 다르죠?", "", [
            "틀린 값을 그럴듯하게 보여 주지 않는 것입니다.",
            "받지 못한 값을 '예시'라 적고, 규정은 단정하지 않고 조회처를 달고,",
            "기관이 멈춰도 며칠 전 실제 값으로 답하면서 그것이 며칠 전 값임을 밝힙니다.",
            "그리고 그게 말만이 아니라는 걸 테스트로 지킵니다.",
        ]),
        ("답을 모르는 질문을 받으면?", "sure", [
            "\"확인해 보고 알려 드리겠습니다\" 가 정답입니다.",
            "이 프로젝트의 원칙이 '모르면 모른다고 말한다' 입니다.",
            "발표자가 그걸 어기면 프로젝트 설명 자체가 무너집니다.",
            "숫자를 기억 못 하면 상세 보고서 22장에 다 있다고 말하고 넘기세요.",
        ]),
    ]),
]

FACTS = [("1,668", "테스트 전부 통과"), ("105", "커밋 (12일)"),
         ("43종", "기관 자료 (42종 연결)"), ("11,326", "관세율 부호 (키 없이)"),
         ("4,086회", "HS 정확도 100%"), ("21건", "찾아 고친 결함")]




def korean_fonts() -> tuple[str, str]:
    """PDF 에 심을 한글 글꼴을 찾습니다. 못 찾으면 멈춥니다."""

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    from app.processors.document_form import BOLD_CANDIDATES, FONT_CANDIDATES

    regular = next((path for path in FONT_CANDIDATES if Path(path).exists()), None)
    if not regular:
        raise SystemExit("한글 글꼴을 찾지 못해 만들지 않았습니다. "
                         "글자가 네모로 나온 PDF 를 인쇄해 들고 가면 그때야 압니다.")
    bold = next((path for path in BOLD_CANDIDATES if Path(path).exists()), regular)
    pdfmetrics.registerFont(TTFont("KR", regular))
    pdfmetrics.registerFont(TTFont("KR-B", bold))
    return "KR", "KR-B"


def build(out: Path) -> Path:
    """질문과 답을 A4 여러 장에 이어 적습니다."""

    from reportlab.lib.colors import Color
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    body_font, bold_font = korean_fonts()
    width, height = A4
    margin = 40
    right = width - margin

    def rgb(value):
        return Color(value[0] / 255, value[1] / 255, value[2] / 255)

    out.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(out), pagesize=A4)
    pdf.setTitle("FORWARDUS 질의응답 대비")
    pdf.setAuthor("TradeOne")

    state = {"y": height - margin, "page": 1}

    def room(need: float) -> None:
        if state["y"] - need < margin + 18:
            footer()
            pdf.showPage()
            state["page"] += 1
            state["y"] = height - margin

    def footer() -> None:
        pdf.setFont(body_font, 8)
        pdf.setFillColor(rgb(MUTED))
        pdf.drawRightString(right, margin - 12, f"{state['page']}")

    def line(text: str, size: float, color=INK, *, bold: bool = False,
             indent: float = 0, gap: float = 0) -> None:
        pdf.setFont(bold_font if bold else body_font, size)
        pdf.setFillColor(rgb(color))
        pdf.drawString(margin + indent, state["y"] - size, text)
        state["y"] -= (gap or size + 5)

    def rule() -> None:
        pdf.setStrokeColor(rgb(LINE_COLOR))
        pdf.setLineWidth(0.6)
        pdf.line(margin, state["y"], right, state["y"])
        state["y"] -= 10

    # ── 머리
    line("FORWARDUS 질의응답 대비", 21, INK, bold=True, gap=27)
    line("발표 중 손에 들고 보는 종이입니다 · 2026-09-27 기준", 9, MUTED, gap=16)
    rule()
    for row in (FACTS[:3], FACTS[3:]):
        line("     ".join(f"{number}  {label}" for number, label in row),
             10.5, BLUE, bold=True, gap=15)
    line("[먼저 말하기] 질문받기 전에 발표에서 먼저 말하는 쪽이 낫습니다."
         "     [자신 있게] 숫자 근거가 확실합니다.", 8.5, MUTED, gap=14)
    rule()
    state["y"] -= 4

    # ── 본문
    for group, rows in DATA:
        room(70)
        line(group, 13, BLUE, bold=True, gap=19)
        for question, tone, answer in rows:
            room(18 + 13 * len(answer) + 8)
            mark = {"hard": "   [먼저 말하기]", "sure": "   [자신 있게]"}.get(tone, "")
            color = {"hard": AMBER, "sure": GREEN}.get(tone, INK)
            line(f"Q. {question}{mark}", 10.5, color, bold=True, gap=15)
            for index, text in enumerate(answer):
                line(text, 9.5 if index else 10, INK if index == 0 else BODY,
                     indent=14, gap=13)
            state["y"] -= 7
        state["y"] -= 5

    room(40)
    rule()
    line("확실하지 않은 것은 \"확인해 보겠습니다\" 가 정답입니다. "
         "지어내면 그 자리에서 무너집니다.", 10, AMBER, bold=True, gap=14)
    footer()
    pdf.save()
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="질의응답 대비 자료를 PDF 로 만듭니다.")
    parser.add_argument("--out", default=str(Path.home() / "Downloads"
                                             / "FORWARDUS_질의응답.pdf"))
    args = parser.parse_args()
    path = build(Path(args.out))
    print(f"■ 만들었습니다 · {path} ({path.stat().st_size:,}바이트)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
