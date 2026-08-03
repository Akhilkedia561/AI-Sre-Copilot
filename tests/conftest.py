"""Shared pytest fixtures."""

import os
import pytest


@pytest.fixture(autouse=True)
def _minimum_env(monkeypatch):
    """Ensure tests can construct Settings without a real .env file."""
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/x")
    monkeypatch.setenv("PROMETHEUS_URL", "http://prometheus.test:9090")
    monkeypatch.setenv("LOKI_URL", "http://loki.test:3100")
    monkeypatch.setenv("RUNBOOK_DIR", "runbooks")
    monkeypatch.setenv("CHROMA_PERSIST_DIR", "/tmp/chroma-test")
    yield
