from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator
class EventType(str,Enum): CREDIT="CREDIT"; DEBIT="DEBIT"
class ProcessingStatus(str,Enum): PENDING="PENDING"; QUEUED="QUEUED"; APPLIED="APPLIED"; FAILED="FAILED"
class EventCreate(BaseModel):
    model_config=ConfigDict(populate_by_name=True)
    event_id:str=Field(alias="eventId", min_length=1,max_length=128)
    account_id:str=Field(alias="accountId", min_length=1,max_length=128)
    type:EventType
    amount:Decimal=Field(gt=0,max_digits=19,decimal_places=4)
    currency:str=Field(min_length=3,max_length=3)
    event_timestamp:datetime=Field(alias="eventTimestamp")
    metadata:dict[str,Any]|None=None
    @field_validator("currency")
    @classmethod
    def currency_upper(cls,v):
        v=v.upper()
        if not v.isalpha(): raise ValueError("currency must contain three letters")
        return v
    @field_validator("event_timestamp")
    @classmethod
    def timezone_required(cls,v):
        if v.tzinfo is None: raise ValueError("eventTimestamp must include timezone")
        return v
class EventResponse(BaseModel):
    model_config=ConfigDict(from_attributes=True,populate_by_name=True)
    event_id:str=Field(alias="eventId")
    account_id:str=Field(alias="accountId")
    type:str
    amount:Decimal
    currency:str
    event_timestamp:datetime=Field(alias="eventTimestamp")
    metadata:dict|None=Field(validation_alias="metadata_json", serialization_alias="metadata")
    processing_status:str=Field(alias="processingStatus")
    created_at:datetime=Field(alias="createdAt")
    updated_at:datetime=Field(alias="updatedAt")
class EventListResponse(BaseModel):
    model_config=ConfigDict(populate_by_name=True)
    account_id:str=Field(alias="accountId")
    items:list[EventResponse]
    count:int
    limit:int
    offset:int
