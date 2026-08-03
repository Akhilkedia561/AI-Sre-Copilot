"""Tests for individual tools using mocked HTTP responses."""

import json
from unittest.mock import patch, MagicMock

from app.tools.prometheus_tool import PrometheusTool
from app.tools.loki_tool import LokiTool
from app.tools.deployment_tool import DeploymentTool


def _mock_http(status_code: int, json_payload: dict):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = json_payload
    mock_response.raise_for_status = MagicMock()
    mock_client.__enter__.return_value.get.return_value = mock_response
    return mock_client


def test_prometheus_tool_success():
    payload = {
        "status": "success",
        "data": {
            "result": [
                {"metric": {"job": "prometheus"}, "value": [1234567890, "1"]},
            ]
        },
    }
    tool = PrometheusTool("http://p.test:9090")
    with patch("app.tools.prometheus_tool.httpx.Client", return_value=_mock_http(200, payload)):
        result = tool.run("up")
    data = json.loads(result)
    assert data["count"] == 1
    assert data["series"][0]["labels"]["job"] == "prometheus"


def test_prometheus_tool_no_data():
    payload = {"status": "success", "data": {"result": []}}
    tool = PrometheusTool("http://p.test:9090")
    with patch("app.tools.prometheus_tool.httpx.Client", return_value=_mock_http(200, payload)):
        result = tool.run("nonexistent_metric")
    assert json.loads(result)["result"] == "no_data"


def test_loki_tool_success():
    payload = {
        "status": "success",
        "data": {
            "result": [
                {
                    "stream": {"container": "demoapp", "level": "error"},
                    "values": [["1700000000000000000", "database timeout"]],
                }
            ]
        },
    }
    tool = LokiTool("http://l.test:3100")
    with patch("app.tools.loki_tool.httpx.Client", return_value=_mock_http(200, payload)):
        result = tool.run('{container="demoapp"} |= "error"')
    data = json.loads(result)
    assert data["count"] == 1
    assert "database timeout" in data["lines"][0]["line"]


def test_deployment_tool_known_service():
    tool = DeploymentTool()
    result = tool.run("demoapp", lookback_hours=1)
    data = json.loads(result)
    assert data["service"] == "demoapp"
    assert data["count"] >= 1
    assert any("payment" in d["message"] for d in data["deployments"])


def test_deployment_tool_unknown_service_returns_empty():
    tool = DeploymentTool()
    result = tool.run("service-that-does-not-exist")
    assert json.loads(result)["result"] == "no_recent_deployments"
