from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import Event
class EventRepository:
    def __init__(self,db:Session): self.db=db
    def get(self,event_id): return self.db.get(Event,event_id)
    def list_for_account(self,account_id,limit,offset):
        stmt=select(Event).where(Event.account_id==account_id).order_by(Event.event_timestamp.asc(),Event.event_id.asc()).limit(limit).offset(offset)
        return list(self.db.scalars(stmt))
    def add(self,event): self.db.add(event); self.db.commit(); self.db.refresh(event); return event
    def save(self,event): self.db.add(event); self.db.commit(); self.db.refresh(event); return event
