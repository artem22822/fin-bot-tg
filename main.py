from fastapi import FastAPI, HTTPException, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from models import Expense, AsyncSessionLocal
import requests
from datetime import datetime
from pydantic import BaseModel
from sqlalchemy.future import select

app = FastAPI()


class ExpenseCreate(BaseModel):
    name: str
    amount: float
    date: str


class ExpenseUpdate(BaseModel):
    name: str
    amount: float


async def get_bd_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


@app.post('/expense/', status_code=status.HTTP_201_CREATED)
async def create_expense(ex: ExpenseCreate, db: AsyncSession = Depends(get_bd_session)):
    exch_rate = requests.get(url="https://api.exchangerate-api.com/v4/latest/UAH")

    if exch_rate.status_code == 200:
        exch_rate = exch_rate.json().get('rates', {}).get("USD", 1)

        amount_usd = ex.amount * exch_rate

        date_obj = datetime.strptime(ex.date, '%d.%m.%Y')
        expense = Expense(name=ex.name, amount=ex.amount, amount_usd=amount_usd, date=date_obj)

        async with db:
            db.add(expense)
            await db.commit()
            await db.refresh(expense)
        return {'message': 'Expense created successfully', 'expense': expense}


@app.get('/expense/{start_date}/{end_date}/')
async def get_period_expenses(start_date: str, end_date: str, db: AsyncSession = Depends(get_bd_session)):
    start_date = datetime.strptime(start_date, "%d.%m.%Y")
    end_date = datetime.strptime(end_date, "%d.%m.%Y")

    query = select(Expense).where(Expense.date.between(start_date, end_date))
    result = await db.execute(query)
    expenses = result.scalars().all()
    if not expenses:
        raise HTTPException(status_code=404, detail="Expense not found")
    return expenses


@app.get('/expense/all/')
async def get_period_expenses(db: AsyncSession = Depends(get_bd_session)):
    query = select(Expense)
    result = await db.execute(query)
    expenses = result.scalars().all()
    if not expenses:
        raise HTTPException(status_code=404, detail="Expense not found")
    return expenses


@app.get('/expense/{expense_id}/')
async def get_expense_by_id(expense_id: int, db: AsyncSession = Depends(get_bd_session)):
    query = select(Expense).where(Expense.id == expense_id)
    result = await db.execute(query)
    expense = result.scalars().first()

    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    return expense


@app.put('/expense/update/{expense_id}/')
async def update_expense(expense_id: int, update_data: ExpenseUpdate, db: AsyncSession = Depends(get_bd_session)):
    query = select(Expense).where(Expense.id == expense_id)
    result = await db.execute(query)
    expense = result.scalars().first()

    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    exch_rate = requests.get(url="https://api.exchangerate-api.com/v4/latest/UAH")

    if exch_rate.status_code == 200:
        exch_rate = exch_rate.json().get('rates', {}).get("USD", 1)

        amount_usd = update_data.amount * exch_rate
    expense.name = update_data.name
    expense.amount = update_data.amount
    expense.amount_usd = amount_usd

    await db.commit()
    await db.refresh(expense)

    return {"message": "Expense updated successfully", "updated_expense": expense}


@app.delete('/expense/delete/{expense_id}/')
async def delete_expense(expense_id: int, db: AsyncSession = Depends(get_bd_session)):
    query = select(Expense).where(Expense.id == expense_id)
    result = await db.execute(query)
    expense = result.scalars().first()

    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    await db.delete(expense)
    await db.commit()

    return {"message": "Expense deleted successfully"}
