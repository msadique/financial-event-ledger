import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx

from app.clients.account_service import AccountServiceClient, get_account_client
from app.core.config import Settings
from app.main import app


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_full_gateway_to_account_service_flow(client, tmp_path):
    port = _free_port()
    account_dir = Path(__file__).resolve().parents[2] / "account-service"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{tmp_path / 'account-integration.db'}"
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=account_dir,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.3).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            raise AssertionError("Account Service did not become healthy")

        settings = Settings(
            account_service_url=f"http://127.0.0.1:{port}",
            account_service_timeout_seconds=1,
            account_service_max_attempts=1,
        )
        real_client = AccountServiceClient(settings=settings)
        app.dependency_overrides[get_account_client] = lambda: real_client

        event = {
            "eventId": "evt-integration",
            "accountId": "acct-integration",
            "type": "CREDIT",
            "amount": "125.50",
            "currency": "USD",
            "eventTimestamp": "2026-05-15T14:02:11Z",
        }
        created = client.post("/events", json=event, headers={"X-Trace-ID": "integration-trace"})
        assert created.status_code == 201
        assert created.json()["processingStatus"] == "APPLIED"

        balance = client.get("/accounts/acct-integration/balance")
        assert balance.status_code == 200
        assert balance.json()["balance"] == "125.5000"

        replay = client.post("/events", json=event)
        assert replay.status_code == 200

        balance_after_replay = client.get("/accounts/acct-integration/balance")
        assert balance_after_replay.json()["balance"] == "125.5000"
    finally:
        app.dependency_overrides.pop(get_account_client, None)
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
