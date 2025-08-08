# app/db.py
import os
from databases import Database
from sqlalchemy import MetaData, Table, Column, Integer, String, DateTime, text
from sqlalchemy import create_engine
import datetime

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:pass@localhost:5432/plivo")

database = Database(DATABASE_URL)
metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("email", String, unique=True, nullable=False),
    Column("password_hash", String, nullable=False),
    Column("created_at", DateTime, server_default=text("now()"))
)

# helper to create tables at startup if they do not exist (useful for Railway dev)
def create_tables_if_not_exist():
    engine = create_engine(DATABASE_URL)
    metadata.create_all(engine)
