from contextlib import contextmanager

import pytest
from fastapi import Request
from fastapi.responses import Response

from app.main import app, health, metrics_and_access_log, shutdown, startup


def _request(path="/test"):
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
            "root_path": "",
        }
    )


def test_startup_shutdown_and_healthy_database(monkeypatch):
    calls = []

    class DB:
        def execute(self, _statement):
            calls.append("execute")

    @contextmanager
    def session():
        yield DB()

    monkeypatch.setattr("app.main.Base.metadata.create_all", lambda _engine: calls.append("schema"))
    monkeypatch.setattr("app.main.SessionLocal", session)
    monkeypatch.setattr("app.main.shutdown_telemetry", lambda provider: calls.append(("shutdown", provider)))
    app.state.otel_tracer_provider = "provider"

    startup()
    result = health()
    shutdown()

    assert calls[0] == "schema"
    assert "execute" in calls
    assert ("shutdown", "provider") in calls
    assert result["status"] == "UP"


@pytest.mark.asyncio
async def test_metrics_middleware_reraises_exception():
    async def fail(_request):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await metrics_and_access_log(_request(), fail)


@pytest.mark.asyncio
async def test_metrics_middleware_success_without_route():
    async def ok(_request):
        return Response("ok", status_code=202)

    response = await metrics_and_access_log(_request("/unmatched"), ok)
    assert response.status_code == 202
