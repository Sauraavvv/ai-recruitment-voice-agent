import pytest
import structlog

from app.config import AppEnv, ConfigError
from app.tests.conftest import TEST_SECRET, make_settings
from app.utils.log import mask_phone, redact_sensitive


def test_missing_core_variable_is_named() -> None:
    with pytest.raises(ConfigError) as exc_info:
        make_settings(database_url=None)
    assert "DATABASE_URL" in str(exc_info.value)


def test_empty_string_counts_as_missing() -> None:
    with pytest.raises(ConfigError) as exc_info:
        make_settings(redis_url="")
    assert "REDIS_URL: is required" in str(exc_info.value)


def test_short_secret_rejected() -> None:
    with pytest.raises(ConfigError) as exc_info:
        make_settings(app_secret_key="too-short")
    assert "APP_SECRET_KEY" in str(exc_info.value)
    assert "too-short" not in str(exc_info.value)


def test_sync_database_driver_rejected() -> None:
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        make_settings(database_url="postgresql://u:p@localhost/db")


def test_secrets_are_masked_in_repr() -> None:
    settings = make_settings(openai_api_key="sk-test-should-not-leak")
    rendered = repr(settings) + str(settings.model_dump())
    assert TEST_SECRET not in rendered
    assert "sk-test-should-not-leak" not in rendered
    assert "postgres:postgres" not in rendered


def test_production_rejects_placeholder_secret() -> None:
    with pytest.raises(ConfigError, match="placeholder"):
        make_settings(
            app_env=AppEnv.PRODUCTION,
            app_secret_key="change-me-change-me-change-me-change-me",
            public_backend_url="https://api.example.org",
        )


def test_production_requires_https_backend_url() -> None:
    with pytest.raises(ConfigError, match="PUBLIC_BACKEND_URL"):
        make_settings(
            app_env=AppEnv.PRODUCTION,
            app_secret_key="Zq8v2Lr6Tn1Xw4Pb9Ks3Hd7Fm5Jc0Ya8",
            public_backend_url="http://api.example.org",
        )


def test_provider_configuration_flags() -> None:
    settings = make_settings(openai_api_key="sk-x", openai_model="some-model")
    flags = settings.provider_configuration()
    assert flags["openai"] is True
    assert flags["exotel"] is False


def test_redaction_processor_hides_secret_fields() -> None:
    event = {"event": "x", "api_key": "abc", "Authorization": "Bearer y", "candidate_id": "123"}
    redacted = redact_sensitive(None, "info", dict(event))
    assert redacted["api_key"] == "[redacted]"
    assert redacted["Authorization"] == "[redacted]"
    assert redacted["candidate_id"] == "123"


def test_startup_log_contains_no_secret_values(capsys: pytest.CaptureFixture[str]) -> None:
    from app.utils.log import configure_logging, get_logger

    settings = make_settings(openai_api_key="sk-test-should-not-leak")
    configure_logging("INFO")
    get_logger("test").info("startup", providers_configured=settings.provider_configuration())
    structlog.reset_defaults()
    output = capsys.readouterr().out
    assert "sk-test-should-not-leak" not in output
    assert TEST_SECRET not in output


@pytest.mark.parametrize(
    ("raw", "masked"),
    [
        ("+919876543210", "+91******3210"),
        ("9876543210", "******3210"),
        ("123", "***"),
        (None, None),
    ],
)
def test_mask_phone(raw: str | None, masked: str | None) -> None:
    assert mask_phone(raw) == masked
