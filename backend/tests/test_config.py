import logging
from pathlib import Path

import pytest

from app.config import (
    SESSION_SECRET_PLACEHOLDER,
    ConfigError,
    Settings,
    load_settings,
)
from app.main import create_app
from tests.conftest import FAKE_SESSION_SECRET


@pytest.mark.parametrize(
    "value",
    [
        None,  # 없음
        "",
        "   ",
        SESSION_SECRET_PLACEHOLDER,
        "short-but-not-long-enough-31chr",  # 31자
    ],
)
def test_app_refuses_to_start_with_bad_session_secret(
    clean_env: pytest.MonkeyPatch, tmp_path: Path, value: str | None
) -> None:
    clean_env.setenv("DB_PATH", str(tmp_path / "test.db"))
    if value is not None:
        clean_env.setenv("SESSION_SECRET", value)

    with pytest.raises(ConfigError) as excinfo:
        create_app()

    assert "SESSION_SECRET" in str(excinfo.value)
    if value and value.strip():
        # 값 자체는 메시지에 넣지 않는다.
        assert value not in str(excinfo.value)


def test_session_secret_min_length_32_ok(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    clean_env.setenv("DB_PATH", str(tmp_path / "test.db"))
    clean_env.setenv("SESSION_SECRET", "x" * 32)
    create_app()


def test_session_secret_not_in_repr(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("SESSION_SECRET", FAKE_SESSION_SECRET)
    settings = load_settings()
    assert FAKE_SESSION_SECRET not in repr(settings)


def test_settings_constructed_directly_are_validated() -> None:
    with pytest.raises(ConfigError):
        Settings(db_path="x.db", enable_api_docs=False, session_secret="too-short")  # noqa: S106


def test_module_app_attribute_is_lazy(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # import 만으로는 앱을 만들지 않고, `app.main:app` 을 참조할 때 설정을 검사한다
    # (uvicorn 기동 경로).
    import app.main as main_module

    main_module._app = None
    with pytest.raises(ConfigError):
        _ = main_module.app

    clean_env.setenv("SESSION_SECRET", FAKE_SESSION_SECRET)
    clean_env.setenv("DB_PATH", str(tmp_path / "test.db"))
    try:
        assert main_module.app is main_module.app
    finally:
        main_module._app = None


def test_cookie_secure_default_on(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("SESSION_SECRET", FAKE_SESSION_SECRET)
    assert load_settings().cookie_secure is True
    for value in ("1", "false", "no", "off", ""):
        clean_env.setenv("COOKIE_SECURE", value)
        assert load_settings().cookie_secure is True, value
    clean_env.setenv("COOKIE_SECURE", "0")
    assert load_settings().cookie_secure is False


def test_allowed_origins_dev(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("SESSION_SECRET", FAKE_SESSION_SECRET)
    assert load_settings().allowed_origins == frozenset()

    # SITE_DOMAIN 없음(로컬 개발): http 출처도 받는다.
    clean_env.setenv("ALLOWED_ORIGINS", " http://localhost:5173/ , ,http://127.0.0.1:5173")
    settings = load_settings()
    assert settings.production is False
    assert settings.allowed_origins == frozenset({"http://localhost:5173", "http://127.0.0.1:5173"})


def test_allowed_origins_production(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("SESSION_SECRET", FAKE_SESSION_SECRET)
    clean_env.setenv("SITE_DOMAIN", "Scrap.Example.Test")
    clean_env.setenv("ALLOWED_ORIGINS", "https://other.example.test/")
    settings = load_settings()
    assert settings.production is True
    assert settings.allowed_origins == frozenset(
        {"https://scrap.example.test", "https://other.example.test"}
    )


# ── 운영 설정 가드 (SITE_DOMAIN 있음) ────────────────────


@pytest.mark.parametrize(
    "env",
    [
        {"COOKIE_SECURE": "0"},
        {"ALLOWED_ORIGINS": "http://localhost:5173"},
        {"ALLOWED_ORIGINS": "https://ok.example.test,http://127.0.0.1:5173"},
    ],
)
def test_production_guard_refuses_dev_settings(
    clean_env: pytest.MonkeyPatch, tmp_path: Path, env: dict[str, str]
) -> None:
    clean_env.setenv("SESSION_SECRET", FAKE_SESSION_SECRET)
    clean_env.setenv("DB_PATH", str(tmp_path / "t.db"))
    clean_env.setenv("SITE_DOMAIN", "scrap.example.test")
    for key, value in env.items():
        clean_env.setenv(key, value)
    with pytest.raises(ConfigError) as excinfo:
        create_app()
    # 메시지에 도메인·출처 값이 없다.
    assert "example.test" not in str(excinfo.value)
    assert "localhost" not in str(excinfo.value)


def test_production_guard_refuses_http_site_domain(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("SESSION_SECRET", FAKE_SESSION_SECRET)
    clean_env.setenv("SITE_DOMAIN", "http://scrap.example.test")
    with pytest.raises(ConfigError):
        load_settings()


def test_dev_settings_allowed_without_site_domain(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("SESSION_SECRET", FAKE_SESSION_SECRET)
    clean_env.setenv("COOKIE_SECURE", "0")
    clean_env.setenv("ALLOWED_ORIGINS", "http://localhost:5173")
    settings = load_settings()
    assert settings.cookie_secure is False


def test_production_guard_refuses_api_docs(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    clean_env.setenv("SESSION_SECRET", FAKE_SESSION_SECRET)
    clean_env.setenv("DB_PATH", str(tmp_path / "t.db"))
    clean_env.setenv("SITE_DOMAIN", "scrap.example.test")
    clean_env.setenv("ENABLE_API_DOCS", "1")
    with pytest.raises(ConfigError) as excinfo:
        create_app()
    assert "ENABLE_API_DOCS" in str(excinfo.value)
    assert "example.test" not in str(excinfo.value)


def test_api_docs_allowed_without_site_domain(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("SESSION_SECRET", FAKE_SESSION_SECRET)
    clean_env.setenv("ENABLE_API_DOCS", "1")
    assert load_settings().enable_api_docs is True


def test_warns_when_no_allowed_origins(
    clean_env: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    clean_env.setenv("SESSION_SECRET", FAKE_SESSION_SECRET)
    clean_env.setenv("DB_PATH", str(tmp_path / "test.db"))
    with caplog.at_level(logging.WARNING, logger="app"):
        create_app()
    assert "허용 출처가 없습니다" in caplog.text
