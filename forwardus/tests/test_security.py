

def test_줄이_꺾인_계좌와_SWIFT도_가린다():
    """PDF에서 읽은 글은 줄이 꺾입니다.

    줄을 하나씩만 보던 때는 "SWIFT: DEUT DE\nFF 500"이 **한 글자도 안 가려진
    채로** 남았습니다. 계좌·SWIFT는 어떤 경우에도 남기지 않기로 한 자리입니다.
    (2026-09-26)
    """

    from app.processors import bank_redaction

    for text in ("Account: DE89 3704 0044\n0532 0130 00",
                 "SWIFT: DEUT DE\nFF 500",
                 "BIC\nHVBKKRSE"):
        masked, found = bank_redaction.redact(text, everywhere=True)
        assert found, text
        assert "DEUT" not in masked and "0532" not in masked and "HVBKKRSE" not in masked


def test_회사명과_선박명은_가리지_않는다():
    """글 전체를 훑었더니 "SAMPLE CO."가 SWIFT로 잡혔습니다.

    새는 것보다 멀쩡한 값을 지우는 편이 더 나쁩니다. 은행 줄과 바로 다음
    줄만 붙여 봅니다.
    """

    from app.processors import bank_redaction

    text = ("COMMERCIAL INVOICE\nShipper: SAMPLE CO.\n"
            "VESSEL HMM ALGECIRAS V.2145W\nCIF YOKOHAMA JAPAN\nSWIFT: HVBKKRSE")
    masked, _ = bank_redaction.redact(text, everywhere=True)
    assert "SAMPLE CO." in masked
    assert "HMM ALGECIRAS" in masked
    assert "CIF YOKOHAMA JAPAN" in masked
    assert "HVBKKRSE" not in masked
