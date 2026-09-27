"""FAQ 100건을 벡터로 만들어 둡니다. (한 번만, 고칠 때 다시)

    python -m scripts.faq_embed            data/faq/faq_vectors.json 만들기
    python -m scripts.faq_embed --check    지금 벡터가 지금 지식베이스와 맞는지만 보기

왜 필요한가
  낱말 검색만으로는 "배에 실은 다음부터는 누가 책임지나요?"가 FOB/CIF FAQ에 닿지 않습니다.
  겹치는 낱말이 없기 때문입니다. 뜻으로 찾으려면 벡터가 필요합니다.

무엇을 담나
  FAQ마다 question + 유사질문 3개 + 키워드를 한 덩어리로 만들어 한 벌씩 임베딩합니다.
  kb_version을 같이 적어 두고, 지식베이스가 바뀌면 faq_index가 이 파일을 쓰지 않습니다.
  (오래된 벡터로 엉뚱한 FAQ를 찾는 것보다 낱말 검색으로 돌아가는 편이 낫습니다)

비용
  text-embedding-3-small · 100건 한 번에 몇 천 토큰. 질문 쪽은 한 번 물을 때 한 줄입니다.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.collectors import ai_client  # noqa: E402
from app.services import faq_index  # noqa: E402

VECTOR_PATH = faq_index.DATA_DIR / "faq_vectors.json"
BATCH = 50


def text_of(faq: dict) -> str:
    return " / ".join([faq.get("question", ""),
                       " ".join(faq.get("question_variants") or []),
                       " ".join(faq.get("keywords") or []),
                       faq.get("short_answer", "")[:200]])


def main() -> int:
    state = faq_index.load(force=True)
    rows, version = state["rows"], faq_index.kb_version()
    if not rows:
        print("FAQ가 없습니다. 먼저 python -m scripts.faq_build 를 돌리세요.")
        return 1

    if "--check" in sys.argv:
        if not VECTOR_PATH.exists():
            print("벡터 파일이 없습니다.")
            return 1
        saved = json.loads(VECTOR_PATH.read_text(encoding="utf-8"))
        same = saved.get("kb_version") == version
        print(f"벡터 {len(saved.get('vectors', {}))}건 · 지식베이스와 "
              f"{'맞습니다' if same else '어긋납니다 (다시 만드세요)'}")
        return 0 if same else 1

    if not ai_client.available():
        print("AI_API_KEY가 없어 벡터를 만들 수 없습니다. 낱말 검색만 씁니다.")
        return 1

    vectors: dict[str, list] = {}
    for start in range(0, len(rows), BATCH):
        chunk = rows[start:start + BATCH]
        result = ai_client.embed([text_of(faq) for faq in chunk], timeout=60)
        if not result["success"]:
            print("실패:", result["message"])
            return 1
        for faq, vector in zip(chunk, result["data"]):
            vectors[faq["id"]] = [round(value, 6) for value in vector]
        print(f"  {start + len(chunk)}/{len(rows)}")

    VECTOR_PATH.write_text(json.dumps(
        {"kb_version": version, "model": ai_client.EMBED_MODEL,
         "built_on": date.today().isoformat(), "dim": len(next(iter(vectors.values()))),
         "vectors": vectors}, ensure_ascii=False), encoding="utf-8")
    size = VECTOR_PATH.stat().st_size / 1024 / 1024
    print(f"저장했습니다. {len(vectors)}건 · {size:.1f}MB · kb_version {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
