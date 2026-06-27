from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class AuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    audit_id: str = Field(alias="auditId")
    action: str
    outcome: str
    trace_id: str = Field(alias="traceId")
    event_id: str | None = Field(alias="eventId")
    account_id: str | None = Field(alias="accountId")
    details: dict | None = Field(validation_alias="details_json", serialization_alias="details")
    created_at: datetime = Field(alias="createdAt")
