from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.db.session import get_db
from app.repositories.accounts import AccountRepository
from app.schemas.accounts import AccountResponse, BalanceResponse, TransactionCreate, TransactionResult, TransactionView
from app.services.account_service import AccountService

router = APIRouter(prefix="/accounts", tags=["accounts"])

@router.post("/{account_id}/transactions", response_model=TransactionResult, response_model_by_alias=True)
def apply_transaction(account_id: str, command: TransactionCreate, response: Response, db: Session=Depends(get_db)):
    result, created = AccountService(db).apply(account_id, command)
    response.status_code = 201 if created else 200
    if not created: response.headers["Idempotent-Replay"] = "true"
    return result

@router.get("/{account_id}/balance", response_model=BalanceResponse, response_model_by_alias=True)
def get_balance(account_id: str, db: Session=Depends(get_db)):
    account=AccountRepository(db).get_account(account_id)
    if not account: raise HTTPException(404, detail={"code":"ACCOUNT_NOT_FOUND","message":"account not found"})
    return BalanceResponse(accountId=account.account_id, currency=account.currency, balance=account.balance, updatedAt=account.updated_at)

@router.get("/{account_id}", response_model=AccountResponse, response_model_by_alias=True)
def get_account(account_id: str, db: Session=Depends(get_db)):
    repo=AccountRepository(db); account=repo.get_account(account_id)
    if not account: raise HTTPException(404, detail={"code":"ACCOUNT_NOT_FOUND","message":"account not found"})
    txs=[TransactionView.model_validate(t) for t in repo.recent_transactions(account_id, get_settings().recent_transactions_limit)]
    return AccountResponse(accountId=account.account_id, currency=account.currency, balance=account.balance,
                           updatedAt=account.updated_at, recentTransactions=txs)
