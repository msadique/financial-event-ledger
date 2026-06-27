import os
os.environ["DATABASE_URL"]="sqlite:///:memory:"
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from app.db.session import Base, get_db
from app.main import app

engine=create_engine("sqlite://", connect_args={"check_same_thread":False}, poolclass=StaticPool)
TestingSession=sessionmaker(bind=engine, expire_on_commit=False)
Base.metadata.create_all(engine)
def override_db():
    db=TestingSession()
    try: yield db
    finally: db.close()
app.dependency_overrides[get_db]=override_db

@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine); yield

@pytest.fixture
def client(): return TestClient(app)
