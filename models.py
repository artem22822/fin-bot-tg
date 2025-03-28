from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, Float, DateTime, func
from config import DATABASE_URL

Base = declarative_base()

engine = create_async_engine(DATABASE_URL, future=True, echo=True)
AsyncSessionLocal  = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

class Expense(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    amount_usd = Column(Float, nullable=True)
    date = Column(DateTime, default=func.now())
