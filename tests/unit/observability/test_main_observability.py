from fastapi.testclient import TestClient

from main import app


def test_metrics_endpoint_returns_prometheus_text():
    response = TestClient(app).get("/metrics")
    assert response.status_code == 200
    assert "chat_requests_total" in response.text or "python_info" in response.text


def test_liveness_does_not_require_dependencies():
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
