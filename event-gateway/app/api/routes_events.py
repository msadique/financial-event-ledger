from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.clients.account_service import AccountServiceClient, get_account_client
from app.db.session import get_db
from app.repositories.events import EventRepository
from app.schemas.events import EventCreate, EventListResponse, EventResponse
from app.services.event_service import EventService

router = APIRouter(tags=["events"])


@router.post("/events", response_model=EventResponse, response_model_by_alias=True)
async def submit_event(
    command: EventCreate,
    response: Response,
    db: Session = Depends(get_db),
    client: AccountServiceClient = Depends(get_account_client),
):
    event, created = await EventService(db, client).submit(command)
    if created:
        response.status_code = 202 if event.processing_status == "QUEUED" else 201
        response.headers["Location"] = f"/events/{event.event_id}"
    else:
        response.status_code = 200
        response.headers["Idempotent-Replay"] = "true"
    return event


@router.get("/events/{event_id}", response_model=EventResponse, response_model_by_alias=True)
def get_event(event_id: str, db: Session = Depends(get_db)):
    event = EventRepository(db).get(event_id)
    if not event:
        raise HTTPException(
            404,
            detail={"code": "EVENT_NOT_FOUND", "message": "event not found"},
        )
    return event


@router.get("/events", response_model=EventListResponse, response_model_by_alias=True)
def list_events(
    account: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    items = EventRepository(db).list_for_account(account, limit, offset)
    return EventListResponse(
        accountId=account,
        items=items,
        count=len(items),
        limit=limit,
        offset=offset,
    )
