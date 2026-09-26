"""③ 계약서 조항 판정 — 오탐·미탐. 계약서 모양을 실제에 가깝게 흔듭니다.

무엇을 잡으려는가
  미탐  진짜 있는 조항을 못 보면, 이용자는 "이 조항이 빠졌다"는 말을 듣고
        이미 있는 조항을 또 넣습니다. 더 나쁜 것은 독소조항을 못 보고 넘기는 것.
  오탐  없는 조항을 있다고 하면, 진짜 빠진 조항을 못 챙깁니다.

이번에 새로 넣은 흔들기
  PDF 에서 읽은 모양 — 줄바꿈·쪽 번호·머리글/바닥글·하이픈 줄나눔·이중 띄어쓰기
  대소문자 뒤섞기 · 전각 따옴표 · 다른 조항들 사이에 파묻기 · 목차만 있는 문서
"""
import sys, io, random, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
from app.processors import contract_clauses as C

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 3131)

# 계약서에 흔히 같이 실리지만 우리 조항이 아닌 글. 오탐을 재려고 섞습니다.
NOISE = [
    "IN WITNESS WHEREOF, the parties have executed this Contract in duplicate.",
    "This Contract shall be binding upon the successors and permitted assigns.",
    "All notices shall be in writing and sent by registered mail or e-mail.",
    "The headings herein are for convenience only and shall not affect construction.",
    "본 계약의 부속서는 본 계약의 일부를 구성한다.",
    "당사자는 본 계약을 성실히 이행한다.",
    "Seller's bank details shall be advised separately.",
    "Page 3 of 12",
    "CONFIDENTIAL — DRAFT FOR DISCUSSION ONLY",
    "Annex 1: Specification (attached)",
    "The Buyer acknowledges receipt of the sample.",
    "Quality shall conform to the sample approved by the Buyer.",
]


def page_breaks(text: str) -> str:
    """PDF 에서 읽으면 쪽 머리글·바닥글이 문장 사이에 끼어듭니다."""
    lines = text.split("\n")
    out = []
    for index, line in enumerate(lines):
        out.append(line)
        if index and index % random.randint(3, 8) == 0:
            out.append(random.choice([f"- {random.randint(1,20)} -",
                                      f"Page {random.randint(1,20)}",
                                      "SALES CONTRACT (cont'd)", ""]))
    return "\n".join(out)


def rewrap(text: str, width: int) -> str:
    """PDF 는 자기 폭대로 줄을 꺾습니다. 낱말 가운데가 꺾이기도 합니다."""
    flat = re.sub(r"[ \t]+", " ", text.replace("\n", " "))
    out, line = [], ""
    for word in flat.split(" "):
        if len(line) + len(word) + 1 > width:
            out.append(line); line = word
        else:
            line = f"{line} {word}".strip()
    out.append(line)
    return "\n".join(out)


def hyphenate(text: str) -> str:
    """긴 낱말이 줄 끝에서 하이픈으로 갈립니다. (진짜 PDF 에서 흔합니다)"""
    def cut(match):
        word = match.group(0)
        at = len(word) // 2
        return f"{word[:at]}-\n{word[at:]}"
    words = [m for m in re.finditer(r"\b[A-Za-z]{9,}\b", text)]
    if not words:
        return text
    pick = random.choice(words)
    return text[:pick.start()] + cut(pick) + text[pick.end():]


def shake(text: str) -> str:
    how = random.random()
    if how < 0.25:
        text = rewrap(text, random.choice([38, 52, 66, 80]))
    elif how < 0.40:
        text = text.replace("\n", "\n\n")
    elif how < 0.50:
        text = re.sub(r" ", "  ", text)
    if random.random() < 0.30:
        text = page_breaks(text)
    if random.random() < 0.20:
        text = hyphenate(text)
    if random.random() < 0.15:
        text = "".join(ch.upper() if random.random() < 0.5 else ch.lower() for ch in text)
    if random.random() < 0.10:
        text = text.replace('"', "“", 1).replace('"', "”", 1)
    return text


keys = [row["key"] for row in C.CLAUSES]
bad, checked = [], 0
miss = {}
false_hit = {}

for turn in range(ROUNDS):
    want = set(random.sample(keys, random.randint(0, min(6, len(keys)))))
    blocks = []
    for key in want:
        row = C.by_key(key)
        blocks.append(row["text_en"])   # text_ko 는 조언 한 줄이라 계약서가 아닙니다
    # 우리 조항이 아닌 글을 섞습니다 (오탐 측정)
    for _ in range(random.randint(0, 6)):
        blocks.append(random.choice(NOISE))
    random.shuffle(blocks)
    paper = shake("\n\n".join(blocks))

    checked += 1
    try:
        got = C.find_in(paper)
    except Exception as error:
        bad.append(f"{turn}: 죽음 {type(error).__name__} {error}")
        continue

    for key in want - got:
        miss[key] = miss.get(key, 0) + 1
    # 조항 본문끼리 말이 겹쳐 다른 조항이 함께 걸리는 것은 오탐이 아닙니다.
    # 우리 조항을 **하나도 안 넣은** 회차에서 걸린 것만 셉니다.
    if not want:
        for key in got:
            false_hit[key] = false_hit.get(key, 0) + 1

    # 빈 글·공백만 있는 글은 아무것도 나오면 안 됩니다
    checked += 2
    if C.find_in(""):
        bad.append(f"{turn}: 빈 글에서 조항이 나옴")
    if C.find_in("   \n\n\t  "):
        bad.append(f"{turn}: 공백만 있는 글에서 조항이 나옴")

print(f"■ ③ 계약서 {ROUNDS:,}부 · 확인 {checked:,}가지")
print(f"   죽음 {len(bad)}건 · 미탐 {sum(miss.values())}건 · 오탐 {sum(false_hit.values())}건")
for b in bad[:5]: print("   ★", b)
for key, count in sorted(miss.items(), key=lambda kv: -kv[1])[:10]:
    print(f"   ☆ 미탐 {count:>5}회  {key} — {C.by_key(key)['title']}")
for key, count in sorted(false_hit.items(), key=lambda kv: -kv[1])[:10]:
    print(f"   ◇ 오탐 {count:>5}회  {key} — {C.by_key(key)['title']}")
