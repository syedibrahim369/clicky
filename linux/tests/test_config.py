from clicky.core.config import load_settings


def write_env_file(tmp_path, content):
    env_file_path = tmp_path / ".env"
    env_file_path.write_text(content)
    return env_file_path


def test_values_come_from_the_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("WHISPER_MODEL", raising=False)
    settings = load_settings(write_env_file(tmp_path, "WHISPER_MODEL=small.en\n"))
    assert settings.whisper_model == "small.en"


def test_real_environment_overrides_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("WHISPER_MODEL", "tiny.en")
    settings = load_settings(write_env_file(tmp_path, "WHISPER_MODEL=small.en\n"))
    assert settings.whisper_model == "tiny.en"


def test_missing_file_and_blank_values_use_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("WHISPER_MODEL", raising=False)
    assert load_settings(tmp_path / "absent").whisper_model == "base.en"
    assert load_settings(write_env_file(tmp_path, "WHISPER_MODEL=\n")).whisper_model == "base.en"


def test_api_key_never_appears_when_settings_are_printed(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    settings = load_settings(write_env_file(tmp_path, "GEMINI_API_KEY=secret-value\n"))
    assert settings.gemini_api_key == "secret-value"
    assert "secret-value" not in repr(settings)
    assert "secret-value" not in str(settings)
