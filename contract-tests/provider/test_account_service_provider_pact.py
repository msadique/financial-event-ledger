from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path
from typing import Any, Literal

import httpx
import pytest
import uvicorn
from pact import Verifier

from app.db.models import Account
from app.db.session import Base, SessionLocal, engine
from app.main import app

PACT_DIR = Path(os.getenv("PACT_DIR", "/contracts/pacts"))


def _reset_database(action: Literal["setup", "teardown"], parameters=None) -> None:
    if action == "setup":
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)


def _no_transaction_exists(
    action: Literal["setup", "teardown"],
    parameters: dict[str, Any] | None,
) -> None:
    if action == "setup":
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)


def _account_exists(
    action: Literal["setup", "teardown"],
    parameters: dict[str, Any] | None,
) -> None:
    if action != "setup":
        return
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    values = parameters or {}
    with SessionLocal() as db:
        db.add(
            Account(
                account_id=str(values.get("accountId", "acct-contract-001")),
                currency=str(values.get("currency", "USD")),
                balance=str(values.get("balance", "42.0000")),
            )
        )
        db.commit()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def provider_url():
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            if httpx.get(f"{url}/health", timeout=0.2).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("Account Service did not start for Pact verification")

    yield url

    server.should_exit = True
    thread.join(timeout=5)


def test_account_service_satisfies_gateway_pact(provider_url):
    pact_files = list(PACT_DIR.glob("*.json"))
    assert pact_files, "Consumer Pact file is missing; run the consumer contract test first"

    verifier = (
        Verifier("Account Service", host="127.0.0.1")
        .add_source(PACT_DIR)
        .add_transport(url=provider_url)
        .state_handler(
            {
                "no transaction exists": _no_transaction_exists,
                "account exists": _account_exists,
            },
            teardown=False,
        )
    )

    verifier.verify()
