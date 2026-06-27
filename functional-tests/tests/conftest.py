import os
import uuid
import httpx
import pytest

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8080")
ACCOUNT_URL = os.getenv("ACCOUNT_URL", "http://localhost:8081")

@pytest.fixture(scope="session")
def gateway():
    with httpx.Client(base_url=GATEWAY_URL, timeout=5.0) as client:
        yield client

@pytest.fixture(scope="session")
def account():
    with httpx.Client(base_url=ACCOUNT_URL, timeout=5.0) as client:
        yield client

@pytest.fixture
def unique_id():
    return uuid.uuid4().hex[:12]
