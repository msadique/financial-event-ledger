import httpx
from app.clients.account_service import AccountServiceUnavailable,get_account_client
from app.main import app
BASE={"eventId":"evt-1","accountId":"acct-1","type":"CREDIT","amount":"100.00","currency":"USD","eventTimestamp":"2026-05-15T14:02:11Z","metadata":{"source":"test"}}
class SuccessClient:
    calls=[]
    async def apply_transaction(self,payload):
        self.calls.append(payload); return httpx.Response(201,json={"applied":True},request=httpx.Request("POST","http://account"))
    async def get_balance(self,account_id): return httpx.Response(200,json={"accountId":account_id,"balance":"100.0000","currency":"USD"},request=httpx.Request("GET","http://account"))
class FailingClient:
    async def apply_transaction(self,payload): raise AccountServiceUnavailable("down")
    async def get_balance(self,account_id): raise AccountServiceUnavailable("down")

def test_submit_duplicate_and_list_order(client):
    fake=SuccessClient(); fake.calls=[]; app.dependency_overrides[get_account_client]=lambda:fake
    assert client.post("/events",json=BASE).status_code==201
    replay=client.post("/events",json=BASE); assert replay.status_code==200; assert len(fake.calls)==1
    early={**BASE,"eventId":"evt-0","eventTimestamp":"2026-05-15T10:00:00Z"}; client.post("/events",json=early)
    items=client.get("/events?account=acct-1").json()["items"]
    assert [x["eventId"] for x in items]==["evt-0","evt-1"]

def test_conflicting_duplicate(client):
    app.dependency_overrides[get_account_client]=lambda:SuccessClient(); client.post("/events",json=BASE)
    assert client.post("/events",json={**BASE,"amount":"101"}).status_code==409

def test_validation(client):
    app.dependency_overrides[get_account_client]=lambda:SuccessClient()
    assert client.post("/events",json={**BASE,"amount":"0"}).status_code==422
    assert client.post("/events",json={**BASE,"type":"OTHER"}).status_code==422

def test_downstream_failure_keeps_local_reads_available(client):
    app.dependency_overrides[get_account_client]=lambda:FailingClient()
    response=client.post("/events",json=BASE); assert response.status_code==503
    stored=client.get("/events/evt-1"); assert stored.status_code==200; assert stored.json()["processingStatus"]=="FAILED"
    assert client.get("/accounts/acct-1/balance").status_code==503

def test_trace_id_returned_and_propagated(client):
    fake=SuccessClient(); fake.calls=[]; app.dependency_overrides[get_account_client]=lambda:fake
    response=client.post("/events",json=BASE,headers={"X-Trace-ID":"trace-123"})
    assert response.headers["X-Trace-ID"]=="trace-123"
