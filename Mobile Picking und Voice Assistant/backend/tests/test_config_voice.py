from app.config import settings


def test_voice_model_settings_exist():
    assert settings.llm_voice_model == "qwen2.5:1.5b"
    assert settings.llm_voice_timeout_ms == 4000
