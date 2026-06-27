from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.repositories.audit import AuditRepository
from app.schemas.audit import AuditResponse

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/events/{event_id}", response_model=list[AuditResponse], response_model_by_alias=True)
def audit_for_event(event_id: str, db: Session = Depends(get_db)):
    return AuditRepository(db).for_event(event_id)
