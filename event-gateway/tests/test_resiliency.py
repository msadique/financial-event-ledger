import pytest
from app.clients.account_service import CircuitBreaker,CircuitOpen

def test_circuit_breaker_opens_and_recovers(monkeypatch):
    now=[100.0]; monkeypatch.setattr("app.clients.account_service.time.monotonic",lambda:now[0])
    cb=CircuitBreaker(failure_threshold=2,recovery_seconds=10)
    cb.failure(); cb.allow(); cb.failure()
    with pytest.raises(CircuitOpen): cb.allow()
    now[0]=111.0; cb.allow(); cb.success(); cb.allow()
