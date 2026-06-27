import logging
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.db.models import Account, Transaction
from app.repositories.accounts import AccountRepository
from app.repositories.audit import AuditRepository
from app.schemas.accounts import TransactionCreate, TransactionResult

logger = logging.getLogger(__name__)


def _utc_naive(value):
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def same_transaction(tx: Transaction, command: TransactionCreate) -> bool:
    return (
        tx.account_id == command.account_id
        and tx.type == command.type.value
        and Decimal(tx.amount) == command.amount
        and tx.currency == command.currency
        and _utc_naive(tx.event_timestamp) == _utc_naive(command.event_timestamp)
    )


class AccountService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AccountRepository(db)
        self.audit = AuditRepository(db)

    def apply(self, account_id: str, command: TransactionCreate) -> tuple[TransactionResult, bool]:
        if account_id != command.account_id:
            self.audit.record("TRANSACTION_REJECTED", "FAILURE", event_id=command.event_id, account_id=account_id, details={"reason": "account id mismatch"})
            raise HTTPException(422, detail={"code": "ACCOUNT_ID_MISMATCH", "message": "URL accountId must match payload accountId"})

        existing = self.repo.get_transaction(command.event_id)
        if existing:
            if not same_transaction(existing, command):
                self.audit.record("TRANSACTION_CONFLICT_REJECTED", "FAILURE", event_id=command.event_id, account_id=account_id)
                raise HTTPException(409, detail={"code": "EVENT_ID_CONFLICT", "message": "eventId already exists with different transaction data"})
            account = self.repo.get_account(account_id)
            self.audit.record("TRANSACTION_REPLAYED", "REPLAY", event_id=command.event_id, account_id=account_id)
            logger.info("transaction replayed", extra={"eventId": command.event_id, "accountId": account_id})
            return self._result(existing, account, True), False

        account = self.repo.get_account(account_id)
        account_created = account is None
        if account_created:
            account = Account(account_id=account_id, currency=command.currency, balance=Decimal("0"))
            self.db.add(account)
        elif account.currency != command.currency:
            self.audit.record("TRANSACTION_REJECTED", "FAILURE", event_id=command.event_id, account_id=account_id, details={"reason": "currency mismatch"})
            raise HTTPException(409, detail={"code": "CURRENCY_MISMATCH", "message": "event currency does not match account currency"})

        previous_balance = Decimal(account.balance)
        delta = command.amount if command.type.value == "CREDIT" else -command.amount
        account.balance = previous_balance + delta
        account.updated_at = datetime.now(timezone.utc)
        tx = Transaction(
            event_id=command.event_id,
            account_id=account_id,
            type=command.type.value,
            amount=command.amount,
            currency=command.currency,
            event_timestamp=command.event_timestamp,
        )
        self.db.add(tx)
        if account_created:
            self.audit.record("ACCOUNT_CREATED", "SUCCESS", account_id=account_id, event_id=command.event_id, commit=False)
        self.audit.record(
            "BALANCE_UPDATED",
            "SUCCESS",
            account_id=account_id,
            event_id=command.event_id,
            details={"previousBalance": str(previous_balance), "delta": str(delta), "newBalance": str(account.balance)},
            commit=False,
        )
        self.audit.record("TRANSACTION_APPLIED", "SUCCESS", account_id=account_id, event_id=command.event_id, commit=False)

        try:
            self.db.commit()
            self.db.refresh(tx)
            self.db.refresh(account)
        except IntegrityError:
            self.db.rollback()
            existing = self.repo.get_transaction(command.event_id)
            if existing and same_transaction(existing, command):
                account = self.repo.get_account(account_id)
                self.audit.record("TRANSACTION_REPLAYED", "REPLAY", event_id=command.event_id, account_id=account_id)
                return self._result(existing, account, True), False
            self.audit.record("TRANSACTION_CONFLICT_REJECTED", "FAILURE", event_id=command.event_id, account_id=account_id)
            raise HTTPException(409, detail={"code": "EVENT_ID_CONFLICT", "message": "eventId already exists"})

        logger.info("transaction applied", extra={"eventId": command.event_id, "accountId": account_id})
        return self._result(tx, account, False), True

    @staticmethod
    def _result(tx, account, replay):
        return TransactionResult(
            eventId=tx.event_id,
            accountId=tx.account_id,
            applied=True,
            idempotentReplay=replay,
            balance=account.balance,
            currency=account.currency,
            appliedAt=tx.applied_at,
        )
