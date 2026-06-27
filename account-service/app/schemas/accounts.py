from datetime import datetime
from decimal import Decimal
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, field_validator

class TransactionType(str, Enum): CREDIT="CREDIT"; DEBIT="DEBIT"

class TransactionCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    event_id: str = Field(alias="eventId", min_length=1, max_length=128)
    account_id: str = Field(alias="accountId", min_length=1, max_length=128)
    type: TransactionType
    amount: Decimal = Field(gt=0, max_digits=19, decimal_places=4)
    currency: str = Field(min_length=3, max_length=3)
    event_timestamp: datetime = Field(alias="eventTimestamp")
    @field_validator("currency")
    @classmethod
    def currency_upper(cls, v):
        v=v.upper()
        if not v.isalpha(): raise ValueError("currency must contain three letters")
        return v
    @field_validator("event_timestamp")
    @classmethod
    def timezone_required(cls, v):
        if v.tzinfo is None: raise ValueError("eventTimestamp must include timezone")
        return v

class TransactionResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    event_id: str = Field(alias="eventId")
    account_id: str = Field(alias="accountId")
    applied: bool
    idempotent_replay: bool = Field(alias="idempotentReplay")
    balance: Decimal
    currency: str
    applied_at: datetime = Field(alias="appliedAt")

class TransactionView(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    event_id: str = Field(alias="eventId")
    type: str
    amount: Decimal
    currency: str
    event_timestamp: datetime = Field(alias="eventTimestamp")
    applied_at: datetime = Field(alias="appliedAt")

class BalanceResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    account_id: str = Field(alias="accountId")
    currency: str
    balance: Decimal
    updated_at: datetime = Field(alias="updatedAt")

class AccountResponse(BalanceResponse):
    recent_transactions: list[TransactionView] = Field(alias="recentTransactions")
