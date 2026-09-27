"""새로고침·로고를 누르면 화면은 처음으로, 대화는 물어보고 되살립니다.

나눈 대화가 말없이 사라지면 "방금 물어본 게 어디 갔지" 하게 됩니다. 반대로 말없이
되살아나면 새로 시작하려던 사람이 앞 이야기에 묶입니다. 그래서 **물어봅니다.**
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parent.parent
STORE = (ROOT / "app/static/js/chat_store.js").read_text(encoding="utf-8")
HOME = (ROOT / "app/static/js/home.js").read_text(encoding="utf-8")


def test_보관함은_창을_닫아도_남는다():
    """지금 보는 대화는 탭(sessionStorage), 보관함은 브라우저(localStorage)에 둡니다."""

    assert "const KEEP_KEY" in STORE and "window.localStorage.setItem(KEEP_KEY" in STORE
    # 주고받은 말이 있을 때만 보관합니다. 인사만 있는 것은 보관할 이유가 없습니다.
    keep = STORE[STORE.index("function keep(state)"):STORE.index("function readKept")]
    assert 'row.role === "user"' in keep


def test_보이는_대화만_비우는_길과_아주_지우는_길이_따로다():
    """로고·새로고침은 화면만 비웁니다. '새 대화'는 보관함과 서버 기억까지 지웁니다."""

    assert "clearVisible(source)" in STORE
    visible = STORE[STORE.index("clearVisible(source)"):STORE.index("subscribe(fn)")]
    assert "forgetKept" not in visible                 # 보관함은 남깁니다

    clear = STORE[STORE.index("clear(source)"):STORE.index("clearVisible(source)")]
    assert "forgetKept()" in clear                     # 새 대화는 보관함도 비웁니다
    assert "/api/chat-memory" in clear                 # 서버 기억도 지웁니다


def test_들어오면_묻고_고르게_한다():
    block = HOME[HOME.index("function offerKept"):HOME.index("showAction(current)")]
    assert "지난 대화" in block and "남아 있습니다" in block
    assert "data-kept-open" in block and "data-kept-drop" in block
    # 이어서 보기 → 보관함에서 되살립니다. 새로 시작 → 보관함을 비웁니다.
    assert "chat.restoreKept(SOURCE)" in block
    assert "chat.forgetKept()" in block
    # 물어볼 것이 있으면 예전처럼 자동으로 되살리지 않습니다.
    assert "if (!offerKept()) restore();" in block


def test_화면에_그릴_모양이_있다():
    css = (ROOT / "app/static/css/home.css").read_text(encoding="utf-8")
    assert ".home_kept" in css and ".home_kept_buttons" in css


def test_골라서_불러올_수_있다():
    """지난 대화 다섯 번 중 하나만 이어 가고 싶을 때가 있습니다.

    전부 불러오면 상관없는 말이 섞이고, 새로 시작하면 다 잃습니다.
    질문 하나와 그 답을 한 묶음으로 보여 주고, 고른 것만 되살립니다.
    """

    # 보관함을 묶음으로 나눠 주는 창구가 있어야 화면이 목록을 그립니다.
    assert "keptTurns()" in STORE
    assert "function turnsOf" in STORE and "function pickTurns" in STORE
    # 고른 번호를 넘기면 그것만, 안 넘기면 예전처럼 전부.
    assert "restoreKept(source, pick)" in STORE
    assert "Array.isArray(pick) ? pickTurns(kept.messages, pick) : kept.messages" in STORE


def test_질문만_빼고_답을_남기지_않는다():
    """질문만 골라내면 답이 남의 질문 밑에 붙습니다. 묶음으로 다뤄야 합니다."""

    turns = STORE[STORE.index("function turnsOf"):STORE.index("function pickTurns")]
    # 물어본 말이 나오면 새 묶음, 아니면 앞 묶음에 딸립니다.
    assert 'message.role === "user"' in turns
    assert "turns[turns.length - 1].rest.push(message)" in turns


def test_화면에_골라서_단추가_있다():
    block = HOME[HOME.index("function offerKept"):HOME.index("showAction(current)")]
    assert "data-kept-pick" in block and "data-kept-go" in block
    # 하나도 안 골랐으면 아무 일도 하지 않습니다.
    assert "if (!pick.length) return;" in block
