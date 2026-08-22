from app.security.redaction import redact_object, redact_text


def test_redacts_api_keys_from_text_and_nested_objects() -> None:
    secret = "sk-example-secret-123456"
    assert secret not in redact_text(f"request failed api_key={secret}")
    redacted = redact_object({"api_key": secret, "nested": [f"Authorization: {secret}"]})
    assert secret not in str(redacted)
    assert redacted["api_key"] == "[REDACTED]"

