import sys

import pytest

from arranger import config
from arranger.config import Settings
from arranger.therefore import Therefore


@pytest.fixture(autouse=True)
def clean_config_environment(monkeypatch):
    for key in [
        "THEREFORE_BASE_URL",
        "THEREFORE_TENANT",
        "BACKUP_ENABLED",
        "DEBUG_LOGGING",
        "BACKUP_DIR",
        "HOST",
        "PORT",
        "PROCESSING_TIMEOUT_SECONDS",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_automatic_dotenv_loading_and_backup_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "application_dir", lambda: tmp_path)
    (tmp_path / ".env").write_text(
        '# Application configuration\nTHEREFORE_BASE_URL="https://example.test/restun"\n'
        "THEREFORE_TENANT=example\nPORT=8877\n"
    )
    settings = Settings.from_env()
    assert settings.base_url == "https://example.test/restun"
    assert settings.tenant == "example"
    assert settings.port == 8877
    assert settings.backup_dir is None
    assert settings.debug_logging is False
    assert not (tmp_path / "var").exists()


def test_environment_then_cli_override_file_values(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("THEREFORE_BASE_URL=https://file.test/restun\nPORT=8001\nBACKUP_ENABLED=true\n")
    monkeypatch.setenv("PORT", "8002")
    settings = Settings.from_env(path)
    assert settings.port == 8002
    settings = Settings.from_env(path, {"PORT": 8003, "BACKUP_ENABLED": "false"})
    assert settings.port == 8003
    assert settings.backup_dir is None


def test_explicit_file_and_relative_backup_path_are_independent_of_working_directory(
    tmp_path, monkeypatch
):
    folder = tmp_path / "config"
    folder.mkdir()
    elsewhere = tmp_path / "working"
    elsewhere.mkdir()
    path = folder / "custom.env"
    path.write_text(
        "THEREFORE_BASE_URL=https://example.test/restun\nBACKUP_ENABLED=true\nBACKUP_DIR=originals\n"
    )
    monkeypatch.chdir(elsewhere)
    settings = Settings.from_env(path)
    assert settings.backup_dir == folder / "originals"


def test_frozen_app_reads_dotenv_beside_executable_not_working_directory(tmp_path, monkeypatch):
    folder = tmp_path / "install"
    folder.mkdir()
    working = tmp_path / "working"
    working.mkdir()
    (folder / ".env").write_text("THEREFORE_BASE_URL=https://expected.test/restun\n")
    (working / ".env").write_text("THEREFORE_BASE_URL=https://wrong.test/restun\n")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(folder / "annotation-arranger.exe"))
    monkeypatch.chdir(working)
    assert Settings.from_env().base_url == "https://expected.test/restun"


def test_missing_configuration_has_no_tenant_specific_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "application_dir", lambda: tmp_path)
    with pytest.raises(ValueError, match="Set THEREFORE_BASE_URL"):
        Settings.from_env()
    with pytest.raises(ValueError, match="does not exist"):
        Settings.from_env(tmp_path / "missing.env")


@pytest.mark.parametrize(
    "values",
    [
        {"THEREFORE_BASE_URL": "http://example.test/restun"},
        {"THEREFORE_BASE_URL": "https://user:pass@example.test/restun"},
        {"THEREFORE_BASE_URL": "https://example.test/restun?token=bad"},
        {"BACKUP_ENABLED": "typo"},
        {"DEBUG_LOGGING": "typo"},
        {"PORT": "0"},
        {"PROCESSING_TIMEOUT_SECONDS": "-1"},
    ],
)
def test_invalid_settings_fail_before_serving(tmp_path, values):
    path = tmp_path / ".env"
    path.write_text("THEREFORE_BASE_URL=https://example.test/restun\n")
    with pytest.raises(ValueError):
        Settings.from_env(path, values)


def test_cloud_tenant_can_be_inferred_and_on_premise_tenant_is_optional(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "THEREFORE_BASE_URL=https://example-tenant.thereforeonline.com/theservice/v0001/restun\n"
    )
    assert Settings.from_env(path).tenant == "example-tenant"
    settings = Settings.from_env(path, {"THEREFORE_BASE_URL": "https://server.example.test/restun"})
    assert settings.tenant == ""
    client = Therefore(settings.base_url, settings.tenant, "token")
    try:
        assert "TenantName" not in client.client.headers
    finally:
        client.close()


@pytest.mark.parametrize(
    "value,expected", [("true", True), ("false", False), ("1", True), ("off", False)]
)
def test_debug_logging_config(tmp_path, monkeypatch, value, expected):
    path = tmp_path / ".env"
    path.write_text(f"THEREFORE_BASE_URL=https://example.test/restun\nDEBUG_LOGGING={value}\n")
    assert Settings.from_env(path).debug_logging is expected
    monkeypatch.setenv("DEBUG_LOGGING", "false")
    assert Settings.from_env(path).debug_logging is False
