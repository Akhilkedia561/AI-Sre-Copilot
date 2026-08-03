"""Tests for the Settings loader."""

import pytest
from app.config import Settings


def test_settings_loads_from_env():
    s = Settings()
    assert s.llm_api_key == "test-key"
    assert s.slack_webhook_url.startswith("https://hooks.slack.com")
    assert s.prometheus_url == "http://prometheus.test:9090"


def test_missing_required_setting_raises(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    with pytest.raises(Exception):
        Settings(_env_file=None)
