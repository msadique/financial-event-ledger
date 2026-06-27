def test_both_services_are_healthy(gateway, account):
    assert gateway.get("/health").status_code == 200
    assert account.get("/health").status_code == 200
    assert gateway.get("/metrics").status_code == 200
    assert account.get("/metrics").status_code == 200
