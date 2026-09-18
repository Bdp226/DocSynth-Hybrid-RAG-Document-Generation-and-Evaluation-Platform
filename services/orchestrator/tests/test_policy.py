from app.policy import detect_policy_flags, enforce_input_limits


def test_detect_policy_flags_finds_pii_and_disallowed_terms() -> None:
    text = "Reach me at user@example.com and use send_external_raw_data later."
    flags = detect_policy_flags(text)

    assert "pii_detected:email" in flags
    assert "disallowed_term:send_external_raw_data" in flags


def test_enforce_input_limits_truncates_text() -> None:
    result = enforce_input_limits("abcdef", max_chars=3)
    assert result == "abc"
