from job_agent.text_identity import normalize_text, sha256_bytes


def test_normalize_text_canonicalizes_newlines_and_unicode() -> None:
    assert normalize_text("a\r\nb\rc") == "a\nb\nc"
    assert normalize_text("Cafe\u0301") == "Caf\u00e9"


def test_sha256_bytes_returns_standard_hex_digest() -> None:
    assert sha256_bytes(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223"
        "b00361a396177a9cb410ff61f20015ad"
    )
