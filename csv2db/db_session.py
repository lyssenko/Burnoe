import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = f"sqlite:///{os.path.join(BASE_DIR, 'burnoe.db')}"
engine = create_engine(DB_PATH, echo=False)
SessionLocal = sessionmaker(bind=engine)
