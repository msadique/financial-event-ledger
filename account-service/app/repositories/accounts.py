from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import Account, Transaction

class AccountRepository:
    def __init__(self, db: Session): self.db=db
    def get_account(self, account_id: str): return self.db.get(Account, account_id)
    def get_transaction(self, event_id: str): return self.db.get(Transaction, event_id)
    def recent_transactions(self, account_id: str, limit: int):
        return list(self.db.scalars(select(Transaction).where(Transaction.account_id==account_id).order_by(Transaction.event_timestamp.desc(), Transaction.event_id.desc()).limit(limit)))
