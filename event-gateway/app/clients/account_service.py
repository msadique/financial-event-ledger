import asyncio, random, time
from dataclasses import dataclass
import httpx
from app.core.config import Settings, get_settings
from app.core.tracing import current_trace_id

class AccountServiceUnavailable(Exception): pass
class CircuitOpen(AccountServiceUnavailable): pass

@dataclass
class CircuitBreaker:
    failure_threshold:int
    recovery_seconds:float
    failures:int=0
    opened_at:float|None=None
    def allow(self):
        if self.opened_at is None: return
        if time.monotonic()-self.opened_at>=self.recovery_seconds: return
        raise CircuitOpen("account service circuit is open")
    def success(self): self.failures=0; self.opened_at=None
    def failure(self):
        self.failures+=1
        if self.failures>=self.failure_threshold: self.opened_at=time.monotonic()

class AccountServiceClient:
    def __init__(self, settings:Settings|None=None, transport=None):
        self.settings=settings or get_settings()
        self.breaker=CircuitBreaker(self.settings.circuit_breaker_failure_threshold,self.settings.circuit_breaker_recovery_seconds)
        self.transport=transport
    async def _request(self, method, path, **kwargs):
        self.breaker.allow(); last=None
        for attempt in range(self.settings.account_service_max_attempts):
            try:
                async with httpx.AsyncClient(base_url=self.settings.account_service_url,timeout=self.settings.account_service_timeout_seconds,transport=self.transport) as client:
                    response=await client.request(method,path,headers={"X-Trace-ID":current_trace_id()},**kwargs)
                if response.status_code in {502,503,504}:
                    raise httpx.HTTPStatusError("transient downstream error",request=response.request,response=response)
                self.breaker.success(); return response
            except (httpx.TimeoutException,httpx.ConnectError,httpx.HTTPStatusError) as exc:
                last=exc; self.breaker.failure()
                if attempt+1>=self.settings.account_service_max_attempts: break
                await asyncio.sleep((0.05*(2**attempt))+random.uniform(0,0.03))
        raise AccountServiceUnavailable(str(last))
    async def apply_transaction(self, payload): return await self._request("POST",f"/accounts/{payload['accountId']}/transactions",json=payload)
    async def get_balance(self, account_id): return await self._request("GET",f"/accounts/{account_id}/balance")

_client=AccountServiceClient()
def get_account_client(): return _client
