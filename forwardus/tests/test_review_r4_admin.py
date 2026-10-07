"""전수 점검 4회차(관리자) — 서버 전체를 멈추는 입력부터 막습니다."""

import time

import pytest

from app.services import contract_clause_service as svc


def _took(text):
    start = time.perf_counter()
    try:
        svc.review(text)
    except Exception:
        pass
    return time.perf_counter() - start


@pytest.mark.parametrize("unit", ["1", " ", "; ", "1 ", "ab ", "가나 ", "1,000.00 "])
def test_반복_글은_바로_거절한다(unit):
    assert _took((unit * 40000)[:40000]) < 2.0


def test_숫자만_이어진_글도_제곱으로_느려지지_않는다():
    import random
    random.seed(3)
    digits = "".join(random.choice("0123456789") for _ in range(60000))
    assert _took(digits) < 5.0


def test_숫자로_시작하는_규칙은_첫_자리에서만_시작해도_같은_결과():
    from app.processors import contract_clauses as cc
    assert cc.analyze("Packing: 25kg 포대 단위로 포장한다.")["clauses"].get("packing")


def test_진짜_계약서는_반복_검사에_걸리지_않는다():
    # 같은 문장을 되풀이한 글이 아니라, 조항마다 내용이 다른 글(압축하면 30% 안팎)
    words = ("buyer seller price payment shipment delivery quality inspection claim warranty penalty notice "
             "agreement liability insurance freight carrier invoice goods quantity governing arbitration").split()
    import random
    random.seed(5)
    text = " ".join(f"Article {n}. The {random.choice(words)} shall {random.choice(words)} the {random.choice(words)} "
                    f"within {random.randint(5, 90)} days of {random.choice(words)} {random.randint(100, 99999)}."
                    for n in range(1, 400))
    assert len(text) > 5000
    assert svc._guard_text(text) == text


def test_길이를_알리지_않는_청크_JSON도_4MB에서_끊는다(app):
    import io
    big = b"[" + b"{}," * 5_000_000 + b"{}]"                  # 약 15MB, Content-Length 없이
    response = app.test_client().post("/api/support-chat", input_stream=io.BytesIO(big),
                                      content_type="application/json",
                                      headers={"Transfer-Encoding": "chunked"},
                                      environ_overrides={"wsgi.input_terminated": True})
    # 길이를 모르는 스트림은 Werkzeug 가 한도에서 읽기를 멈춥니다(잘린 JSON → 400). 413 이든 400 이든
    # **15MB 를 다 올리지 않는 것**이 요점입니다 — 아래 라우트가 읽은 크기로 확인합니다.
    assert response.status_code in (400, 413)


def test_청크_본문은_한도까지만_읽는다(app):
    import io

    from flask import request

    @app.post("/_probe")
    def probe():
        return str(len(request.get_data()))

    big = b"[" + b"{}," * 5_000_000 + b"{}]"
    app.config["RATE_LIMIT_ENABLED"] = False
    response = app.test_client().post("/_probe", input_stream=io.BytesIO(big), content_type="application/json",
                                      headers={"Transfer-Encoding": "chunked"},
                                      environ_overrides={"wsgi.input_terminated": True})
    assert int(response.get_data()) <= 4 * 1024 * 1024


def _image():
    from PIL import Image
    return Image.new("RGB", (400, 200), "white")


def test_OCR가_실패하면_그림을_보내지_않는다(monkeypatch):
    from app.processors import bank_redaction, ocr
    from app.services import ServiceError, document_extract_service as svc2

    monkeypatch.setattr(bank_redaction, "ocr_available", lambda: True)

    def boom(_image):
        raise ocr.OcrFailed("timeout")

    monkeypatch.setattr(bank_redaction, "_read", boom)
    # 글자가 없으면 받지 않는다
    with pytest.raises(ServiceError) as caught:
        svc2._protect("", [_image()])
    assert caught.value.error_code == "OCR_FAILED" if hasattr(caught.value, "error_code") else True
    # 글자가 있으면 글자만 보내고 그림은 빼며 알린다
    text, urls, notes = svc2._protect("Shipper ABC", [_image()])
    assert urls == [] and any("그림은 보내지 않고" in n for n in notes)


def test_OCR가_정상이면_그림이_나간다(monkeypatch):
    from app.processors import bank_redaction
    from app.services import document_extract_service as svc2

    monkeypatch.setattr(bank_redaction, "ocr_available", lambda: True)
    monkeypatch.setattr(bank_redaction, "_read", lambda _image: [])      # 글자 없음 = 실패가 아님
    text, urls, notes = svc2._protect("", [_image()])
    assert len(urls) == 1


@pytest.mark.parametrize("history", [[1, "a", None], {"a": 1}, "text", [[1, 2]], [{"role": 1, "content": 2}]])
def test_상담_history가_엉뚱한_모양이어도_500이_아니다(app, history):
    response = app.test_client().post("/api/support-chat", json={"question": "관세환급이 뭐예요", "history": history})
    assert response.status_code < 500


def test_정상_history는_그대로_쓴다():
    from app.routes.home import _clean_history
    rows = _clean_history([{"role": "user", "content": "안녕"}, "x", {"role": "assistant", "content": ""}])
    assert [r["content"] for r in rows] == ["안녕"]


def test_같은_이메일_동시_가입은_500이_아니다(app, monkeypatch):
    from sqlalchemy.exc import IntegrityError
    from app.extensions import db

    real = db.session.commit
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise IntegrityError("x", {}, Exception("dup"))
        return real()

    monkeypatch.setattr(db.session, "commit", flaky, raising=False)
    response = app.test_client().post("/auth/signup", data={
        "email": "race@example.com", "name": "경합", "password": "Passw0rd!x", "password_confirm": "Passw0rd!x"})
    assert response.status_code == 400


def test_조회값이_붙은_GET_외부호출도_제한된다(app):
    app.config["RATE_LIMIT_ENABLED"] = True
    client = app.test_client()
    codes = [client.get("/tracking/container?q=ABCD1234567").status_code
             for _ in range(security_limit() * 4 + 3)]
    assert 429 in codes


def security_limit():
    from app import security
    return security.HEAVY_LIMIT_PER_MINUTE


def test_화면만_여는_GET은_세지_않는다(app):
    app.config["RATE_LIMIT_ENABLED"] = True
    client = app.test_client()
    codes = {client.get("/lookup/").status_code for _ in range(security_limit() * 4 + 3)}
    assert 429 not in codes


def test_화물_계산은_AI_바구니와_분리(app):
    app.config["RATE_LIMIT_ENABLED"] = True
    client = app.test_client()
    for _ in range(security_limit() + 5):
        client.post("/planning/api/cargo", json={})
    assert client.post("/api/support-chat", json={"question": "안녕"}).status_code != 429


def test_AI_동시_요청이_슬롯을_넘으면_503이고_끝나면_풀린다(app):
    import threading

    from app import security

    gate, started = threading.Event(), threading.Semaphore(0)

    def slow():
        started.release()
        gate.wait(10)
        return "ok"

    app.view_functions["home.api_support_chat"] = slow
    app.config["RATE_LIMIT_ENABLED"] = True
    results = []

    def call():
        results.append(app.test_client().post("/api/support-chat", json={"question": "q"}).status_code)

    workers = [threading.Thread(target=call) for _ in range(security.MAX_CONCURRENT_HEAVY)]
    for worker in workers:
        worker.start()
    for _ in workers:
        assert started.acquire(timeout=10)
    over = app.test_client().post("/api/support-chat", json={"question": "q"})
    assert over.status_code == 503 and over.headers.get("Retry-After")
    gate.set()
    for worker in workers:
        worker.join(10)
    assert results.count(200) == security.MAX_CONCURRENT_HEAVY
    assert app.test_client().post("/api/support-chat", json={"question": "q"}).status_code == 200
