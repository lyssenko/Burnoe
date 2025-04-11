from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DB_PATH = 'sqlite:///burnoe.db'
engine = create_engine(DB_PATH, echo=False)
SessionLocal = sessionmaker(bind=engine)
