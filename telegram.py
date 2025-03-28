from config import TOKEN
import logging
import requests
import aiofiles
import aiohttp
import pandas as pd
import asyncio
import re
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from datetime import datetime
from models import Expense, AsyncSessionLocal
from sqlalchemy.future import select
from aiogram.types import FSInputFile

bot = Bot(token=TOKEN)
dp = Dispatcher()

API_URL = "http://localhost:8000/expense/"

logging.basicConfig(level=logging.INFO)


class ExpenseForm(StatesGroup):
    waiting_for_name = State()
    waiting_for_date = State()
    waiting_for_amount = State()
    waiting_for_period_date = State()
    waiting_for_id = State()
    waiting_for_update_id = State()
    waiting_for_new_amount = State()
    waiting_for_new_name = State()


async def get_all_expenses():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Expense))
        expenses = result.scalars().all()
        return expenses


add_button = '➕ Додати витрату'
view_button = '🔎 Показати всі витрати'
del_button = '🗑️ Видалити витрату'
update_button = '✔️ Оновити витрату'

builder = ReplyKeyboardBuilder()
builder.button(text=add_button)
builder.button(text=view_button)
builder.button(text=del_button)
builder.button(text=update_button)
builder.adjust(1, 1, 1)

menu_keyboard = builder.as_markup(resize_keyboard=True)


@dp.message(Command('start'))
async def start_handler(message: Message):
    await message.answer(
        "Вітаю! Я бот для контролю твоїх витрат.\n"
        'Оберіть Дію:',
        reply_markup=menu_keyboard,
    )


# ADD BUTTON
@dp.message(F.text == add_button)
async def add_expense_step1(message: Message, state: FSMContext):
    await message.answer('Введіть назву витрати', reply_markup=ReplyKeyboardRemove())
    await state.set_state(ExpenseForm.waiting_for_name)


@dp.message(ExpenseForm.waiting_for_name)
async def add_expense_step2(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer('Введіть дату витрати DD.MM.YYYY:')
    await state.set_state(ExpenseForm.waiting_for_date)


@dp.message(ExpenseForm.waiting_for_date)
async def add_expense_step3(message: Message, state: FSMContext):
    date_pattern = r"^\d{2}\.\d{2}\.\d{4}$"
    if not re.match(date_pattern, message.text):
        await message.answer("Некоректний формат дати! Введіть дату в форматі DD.MM.YYYY:")
        return

    await state.update_data(date=message.text)
    await message.answer("Введіть суму в  UAH (Приклад: 150.50)")
    await state.set_state(ExpenseForm.waiting_for_amount)


@dp.message(ExpenseForm.waiting_for_amount)
async def add_expense_finish(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("Некоректний формат суми! Введіть число (Наприклад: 150.50):")
        return

    user_data = await state.get_data()
    expense_data = {
        "name": user_data["name"],
        "date": user_data["date"],
        "amount": amount
    }

    response = requests.post(API_URL, json=expense_data, headers={"Content-Type": "application/json"})
    print(response, "RESPONSE")
    if response.status_code == 201:
        await message.answer("✅ Витрата успішно додана!", reply_markup=menu_keyboard)
    else:
        await message.answer("❌ Помилка при додаванні витрати. Спробуйте ще раз.", reply_markup=menu_keyboard)

    await state.clear()


# VIEW BUTTON
@dp.message(F.text == view_button)
async def get_expenses_step1(message: Message, state: FSMContext):
    await message.answer('Введіть дату з якої хочете отримати витрати!Приклад DD.MM.YYYY-DD.MM.YYYY',
                         reply_markup=ReplyKeyboardRemove())
    await state.set_state(ExpenseForm.waiting_for_period_date)


@dp.message(ExpenseForm.waiting_for_period_date)
async def get_expenses_step2(message: Message, state: FSMContext):
    date_pattern = r"^(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d{2}\.\d{2}\.\d{4})$"
    match = re.match(date_pattern, message.text)

    if not match:
        await message.answer('Некоректний формат! Введіть дату в форматі: **DD.MM.YYYY-DD.MM.YYYY**')
        return

    start_date_str, end_date_str = match.groups()

    try:
        start_date = datetime.strptime(start_date_str, "%d.%m.%Y")
        end_date = datetime.strptime(end_date_str, "%d.%m.%Y")
    except ValueError:
        await message.answer('Помилка обробки дат. Перевірте формат і спробуйте знову.')
        return

    if start_date > end_date:
        await message.answer('Початкова дата не може бути більша за кінцеву! Введіть знову.')
        return

    await state.update_data(start_date=start_date, end_date=end_date)

    await message.answer('Генерую звіт...')

    await generate_expense_report(message, start_date, end_date, state)


async def generate_expense_report(message: Message, start_date: datetime, end_date: datetime, state: FSMContext):
    api_url = f"{API_URL}{start_date.strftime('%d.%m.%Y')}/{end_date.strftime('%d.%m.%Y')}/"

    async with aiohttp.ClientSession() as session:
        async with session.get(api_url) as response:
            if response.status == 404:
                await message.answer('За вказаний період витрати не знайдені.',reply_markup=menu_keyboard)
                await state.clear()
                return

            if response.status != 200:
                await message.answer(f"Помилка запиту: {response.status}",reply_markup=menu_keyboard)
                return

            expenses = await response.json()

    if not expenses:
        await message.answer('За вказаний період витрат нема.',reply_markup=menu_keyboard)
        await state.clear()
        return

    data = [(exp['name'], exp['amount'], exp['amount_usd'], exp["date"]) for exp in expenses]
    df = pd.DataFrame(data, columns=["Назва", "Сума (₴)", "Сума ($)", "Дата"])

    total_amount = sum(exp['amount'] for exp in expenses)
    total_usd = sum(exp['amount_usd'] for exp in expenses)

    df.loc[len(df)] = ["Итого", total_amount, total_usd, ""]

    file_path = "expenses_report.xlsx"
    async with aiofiles.open(file_path, "wb") as f:
        df.to_excel(file_path, index=False)

    file = FSInputFile(file_path)
    await message.answer_document(
        file, caption=f"Звіт за період {start_date.strftime('%d.%m.%Y')} - "
                      f"{end_date.strftime('%d.%m.%Y')}\n\nЗагальна сума: {total_amount}₴ ({total_usd:.2f}$)",
        reply_markup=menu_keyboard
    )

    await state.clear()


# DELETE BUTTON
@dp.message(F.text == del_button)
async def get_expenses_all_step1(message: Message, state: FSMContext):
    await message.answer('Генерую звіт...', reply_markup=ReplyKeyboardRemove())
    api_url = f"{API_URL}all/"

    async with aiohttp.ClientSession() as session:
        async with session.get(api_url) as response:
            if response.status == 404:
                await message.answer('За вказаний період витрати не знайдені.',reply_markup=menu_keyboard)
                await state.clear()
                return

            if response.status != 200:
                await message.answer(f"Помилка запиту: {response.status}",reply_markup=menu_keyboard)
                await state.clear()
                return

            expenses = await response.json()

    if not expenses:
        await message.answer("Список витрат пустий.", reply_markup=menu_keyboard)
        return

    data = [(exp['id'], exp['name'], exp['amount'], exp['amount_usd'], exp['date']) for exp in expenses]
    df = pd.DataFrame(data, columns=["ID", "Назва", "Сума (₴)", "Сума ($)", "Дата"])

    file_path = "expenses_all_report.xlsx"
    async with aiofiles.open(file_path, "wb") as f:
        df.to_excel(file_path, index=False)

        file = FSInputFile(file_path)
        await message.answer_document(file, caption=f"All expenses")
        await message.answer("Введіть ID витрати, яку хочете Видалити!:")
        await state.set_state(ExpenseForm.waiting_for_id)


@dp.message(ExpenseForm.waiting_for_id)
async def delete_expense(message: Message, state: FSMContext):
    try:
        expense_id = int(message.text)
        api_url = f"{API_URL}delete/{expense_id}/"
        async with aiohttp.ClientSession() as session:
            async with session.delete(api_url) as response:
                if response.status == 404:
                    await message.answer(f"Витрата з ID {expense_id} не знайдена.",reply_markup=menu_keyboard)
                elif response.status == 200:
                    await message.answer(f"Витрата з ID {expense_id} була успішно видалена.",reply_markup=menu_keyboard)
                else:
                    await message.answer(f"Сталася помилка: {response.status}", reply_markup=menu_keyboard)

    except ValueError:
        await message.answer("Введіть коректний ID.", reply_markup=menu_keyboard)

    await state.clear()


# UPDATE BUTTON
@dp.message(F.text == update_button)
async def get_expenses_all_update_step1(message: Message, state: FSMContext):
    await message.answer('Генерую звіт...', reply_markup=ReplyKeyboardRemove())
    api_url = f"{API_URL}all/"
    async with aiohttp.ClientSession() as session:
        async with session.get(api_url) as response:
            if response.status == 404:
                await message.answer('За вказаний період витрати не знайдені.', reply_markup=menu_keyboard)
                await state.clear()
                return

            if response.status != 200:
                await message.answer(f"Помилка запиту: {response.status}", reply_markup=menu_keyboard)
                return

            expenses = await response.json()

    if not expenses:
        await message.answer("Список витрат пустий.")
        return

    data = [(exp['id'], exp['name'], exp['amount'], exp['amount_usd'], exp['date']) for exp in expenses]
    df = pd.DataFrame(data, columns=["ID", "Назва", "Сума (₴)", "Сума ($)", "Дата"])

    file_path = "expenses_all_report.xlsx"
    async with aiofiles.open(file_path, "wb") as f:
        df.to_excel(file_path, index=False)

        file = FSInputFile(file_path)
        await message.answer_document(file, caption=f"All expenses")
        await message.answer("Введіть ID витрати, яку хочете змінити:")
        await state.set_state(ExpenseForm.waiting_for_update_id)


@dp.message(ExpenseForm.waiting_for_update_id)
async def get_expense_info(message: Message, state: FSMContext):
    try:
        expense_id = int(message.text)
        api_url = f"{API_URL}{expense_id}/"

        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as response:
                if response.status == 404:
                    await message.answer("Помилка: запис з таким ID не знайдено.\n Введіть ID ще раз")
                    return

                if response.status != 200:
                    await message.answer(f"Помилка  запиту: {response.status}",reply_markup=menu_keyboard)
                    return

                expense = await response.json()

        await message.answer(f"Результат :\n"
                             f"ID: {expense['id']}\n"
                             f"Назва: {expense['name']}\n"
                             f"Сума: {expense['amount']}₴ / {expense['amount_usd']}$\n"
                             f"Дата: {expense['date'][:10]}\n\n"
                             "Введіть нову назву...:")

        await state.update_data(expense_id=expense["id"])
        await state.set_state(ExpenseForm.waiting_for_new_name)

    except ValueError:
        await message.answer("Введіть правильне ID.",reply_markup=menu_keyboard)


@dp.message(ExpenseForm.waiting_for_new_name)
async def update_expense_name(message: Message, state: FSMContext):
    new_name = message.text
    if new_name:
        await state.update_data(new_name=new_name)
        await message.answer("Введіть нову суму для витрати (в UAH):")
        await state.set_state(ExpenseForm.waiting_for_new_amount)
    else:
        await message.answer("Введіть коректну назву для витрати.")


@dp.message(ExpenseForm.waiting_for_new_amount)
async def update_expense_amount(message: Message, state: FSMContext):
    try:
        new_amount = float(message.text)
        data = await state.get_data()
        expense_id = data.get("expense_id")
        new_name = data.get("new_name")

        update_data = {
            "name": new_name,
            "amount": new_amount
        }

        async with aiohttp.ClientSession() as session:
            async with session.put(f"{API_URL}update/{expense_id}/", json=update_data) as response:
                if response.status == 404:
                    await message.answer("Помилка: такої витрати не існує.",reply_markup=menu_keyboard)
                elif response.status == 200:
                    await message.answer(f"✅ Витрата з ID {expense_id} успішно оновлена.",reply_markup=menu_keyboard)
                else:
                    await message.answer(f"Помилка оновлення: {response.status}",reply_markup=menu_keyboard)

        await state.clear()
    except ValueError:
        await message.answer("Введіть  коректну суму.", reply_markup=menu_keyboard )


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
