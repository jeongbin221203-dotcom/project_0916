"""달을 넘길 때 부드럽게 넘어가야 합니다.

두 달이 한 번에 툭 바뀌면 무엇이 바뀐 건지 눈이 따라가지 못합니다.
넘어간 방향으로 살짝 밀어 주면 "다음 달로 갔다"가 보입니다.
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_넘긴_방향을_화면에_알려준다():
    js = (ROOT / "app/static/js/planning.js").read_text(encoding="utf-8")
    assert 'slide = "back"' in js and 'slide = "forward"' in js
    assert "renderCalendar(slide)" in js
    # 날짜를 고를 때는 움직이지 않습니다. (달이 그대로이므로)
    assert "function renderCalendar(slide" in js


def test_움직임은_CSS가_맡는다():
    css = (ROOT / "app/static/css/planning.css").read_text(encoding="utf-8")
    assert ".cal_months.cal_forward" in css and ".cal_months.cal_back" in css
    assert "@keyframes cal_in_from_right" in css and "@keyframes cal_in_from_left" in css


def test_움직임을_줄여_달라고_한_사람에게는_얹지_않는다():
    css = (ROOT / "app/static/css/planning.css").read_text(encoding="utf-8")
    block = css[css.index("@keyframes cal_in_from_right"):]
    assert "prefers-reduced-motion" in block
    reduced = block[block.index("prefers-reduced-motion"):]
    assert "animation: none" in reduced
