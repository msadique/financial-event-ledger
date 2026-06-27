from datetime import datetime, timezone
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.clients.account_service import AccountServiceClient, AccountServiceUnavailable
from app.db.models import Event
from app.repositories.events import EventRepository
from app.schemas.events import EventCreate

def _utc_naive(value):
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)

def same_event(e:Event,c:EventCreate):
    return (e.account_id==c.account_id and e.type==c.type.value and Decimal(e.amount)==c.amount and
            e.currency==c.currency and _utc_naive(e.event_timestamp)==_utc_naive(c.event_timestamp) and (e.metadata_json or None)==c.metadata)
class EventService:
    def __init__(self,db:Session,client:AccountServiceClient): self.db=db; self.repo=EventRepository(db); self.client=client
    async def submit(self,command:EventCreate):
        existing=self.repo.get(command.event_id)
        if existing:
            if not same_event(existing,command): raise HTTPException(409,detail={"code":"EVENT_ID_CONFLICT","message":"eventId already exists with different event data"})
            return existing,False
        event=Event(event_id=command.event_id,account_id=command.account_id,type=command.type.value,amount=command.amount,
                    currency=command.currency,event_timestamp=command.event_timestamp,metadata_json=command.metadata,processing_status="PENDING")
        try: self.repo.add(event)
        except IntegrityError:
            self.db.rollback(); existing=self.repo.get(command.event_id)
            if existing and same_event(existing,command): return existing,False
            raise HTTPException(409,detail={"code":"EVENT_ID_CONFLICT","message":"eventId already exists"})
        payload={"eventId":command.event_id,"accountId":command.account_id,"type":command.type.value,"amount":str(command.amount),
                 "currency":command.currency,"eventTimestamp":command.event_timestamp.isoformat()}
        try:
            response=await self.client.apply_transaction(payload)
            if response.status_code>=400:
                event.processing_status="FAILED"; event.updated_at=datetime.now(timezone.utc); self.repo.save(event)
                detail=response.json() if response.headers.get("content-type","").startswith("application/json") else {"message":response.text}
                raise HTTPException(response.status_code,detail=detail)
            event.processing_status="APPLIED"
        except AccountServiceUnavailable:
            event.processing_status="FAILED"; event.updated_at=datetime.now(timezone.utc); self.repo.save(event)
            raise HTTPException(503,detail={"code":"ACCOUNT_SERVICE_UNAVAILABLE","message":"Account processing is temporarily unavailable","retryable":True})
        event.updated_at=datetime.now(timezone.utc); self.repo.save(event); return event,True
