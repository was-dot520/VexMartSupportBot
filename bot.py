import os
import sqlite3
import asyncio

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage


# =========================
# НАСТРОЙКИ
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")

# ВАЖНО:
# Здесь укажи свой Telegram ID администратора.
# Например: ADMIN_ID = 123456789
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Ссылка на Telegram-канал VexMart
VEXMART_CHANNEL = "https://t.me/VexMart"

DATABASE = "support.db"


# =========================
# ПРОВЕРКА НАСТРОЕК
# =========================

if not BOT_TOKEN:
    raise RuntimeError("Не задана переменная BOT_TOKEN")

if ADMIN_ID == 0:
    raise RuntimeError("Не задана переменная ADMIN_ID")


# =========================
# БАЗА ДАННЫХ
# =========================

def init_database():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open'
        )
    """)

    conn.commit()
    conn.close()


def create_ticket(user_id: int, username: str, text: str):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO tickets (user_id, username, text, status)
        VALUES (?, ?, ?, 'open')
        """,
        (user_id, username, text)
    )

    ticket_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return ticket_id


def get_open_tickets():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, user_id, username, text
        FROM tickets
        WHERE status = 'open'
        ORDER BY id DESC
    """)

    tickets = cursor.fetchall()

    conn.close()

    return tickets


def get_ticket(ticket_id: int):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, user_id, username, text, status
        FROM tickets
        WHERE id = ?
    """, (ticket_id,))

    ticket = cursor.fetchone()

    conn.close()

    return ticket


def close_ticket(ticket_id: int):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE tickets
        SET status = 'closed'
        WHERE id = ?
    """, (ticket_id,))

    conn.commit()
    conn.close()


# =========================
# СОСТОЯНИЯ
# =========================

class UserStates(StatesGroup):
    waiting_for_ticket = State()


class AdminStates(StatesGroup):
    waiting_for_reply = State()


# =========================
# КЛАВИАТУРЫ
# =========================

def user_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🆘 Создать обращение",
                    callback_data="create_ticket"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📋 Мои обращения",
                    callback_data="my_tickets"
                )
            ],
            [
                InlineKeyboardButton(
                    text="ℹ️ О VexMart",
                    url=VEXMART_CHANNEL
                )
            ]
        ]
    )


def admin_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📩 Обращения",
                    callback_data="admin_tickets"
                )
            ]
        ]
    )


# =========================
# BOT / DISPATCHER
# =========================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# =========================
# /start
# =========================

@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    await state.clear()

    if message.from_user.id == ADMIN_ID:
        await message.answer(
            "🛠️ VexMart Support\n\n"
            "Панель администратора:",
            reply_markup=admin_menu()
        )
    else:
        await message.answer(
            "👋 Добро пожаловать в техническую поддержку VexMart!\n\n"
            "Выберите нужное действие:",
            reply_markup=user_menu()
        )


# =========================
# СОЗДАНИЕ ОБРАЩЕНИЯ
# =========================

@dp.callback_query(F.data == "create_ticket")
async def create_ticket_start(
    callback: CallbackQuery,
    state: FSMContext
):
    await state.set_state(UserStates.waiting_for_ticket)

    await callback.message.answer(
        "📝 Опишите вашу проблему или вопрос.\n\n"
        "После отправки сообщение будет передано в техническую поддержку."
    )

    await callback.answer()


@dp.message(UserStates.waiting_for_ticket)
async def create_ticket_message(
    message: Message,
    state: FSMContext
):
    text = message.text

    if not text:
        await message.answer(
            "❌ Пожалуйста, отправьте обращение обычным текстовым сообщением."
        )
        return

    username = message.from_user.username or "без username"

    ticket_id = create_ticket(
        user_id=message.from_user.id,
        username=username,
        text=text
    )

    await state.clear()

    await message.answer(
        f"✅ Обращение #{ticket_id} создано!\n\n"
        "Ожидайте ответа технической поддержки.",
        reply_markup=user_menu()
    )

    # Уведомление администратора
    await bot.send_message(
        ADMIN_ID,
        f"🔴 Новое обращение #{ticket_id}\n\n"
        f"👤 Пользователь: @{username}\n"
        f"🆔 ID: {message.from_user.id}\n\n"
        f"📝 {text}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📩 Открыть обращения",
                        callback_data="admin_tickets"
                    )
                ]
            ]
        )
    )


# =========================
# МОИ ОБРАЩЕНИЯ
# =========================

@dp.callback_query(F.data == "my_tickets")
async def my_tickets(callback: CallbackQuery):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, text, status
        FROM tickets
        WHERE user_id = ?
        ORDER BY id DESC
    """, (callback.from_user.id,))

    tickets = cursor.fetchall()

    conn.close()

    if not tickets:
        await callback.message.answer(
            "📋 У вас пока нет обращений.",
            reply_markup=user_menu()
        )
        await callback.answer()
        return

    text = "📋 Ваши обращения:\n\n"

    for ticket_id, ticket_text, status in tickets:
        if status == "open":
            status_text = "🔴 Открыто"
        else:
            status_text = "✅ Закрыто"

        short_text = ticket_text[:60]

        if len(ticket_text) > 60:
            short_text += "..."

        text += (
            f"#{ticket_id} — {status_text}\n"
            f"📝 {short_text}\n\n"
        )

    await callback.message.answer(
        text,
        reply_markup=user_menu()
    )

    await callback.answer()


# =========================
# АДМИН: СПИСОК ОБРАЩЕНИЙ
# =========================

@dp.callback_query(F.data == "admin_tickets")
async def admin_tickets(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "⛔ У вас нет доступа.",
            show_alert=True
        )
        return

    tickets = get_open_tickets()

    if not tickets:
        await callback.message.answer(
            "📩 Открытых обращений нет.",
            reply_markup=admin_menu()
        )
        await callback.answer()
        return

    buttons = []

    for ticket_id, user_id, username, text in tickets:
        short_text = text[:35]

        if len(text) > 35:
            short_text += "..."

        buttons.append([
            InlineKeyboardButton(
                text=f"🔴 #{ticket_id} — {short_text}",
                callback_data=f"ticket_{ticket_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="🔄 Обновить",
            callback_data="admin_tickets"
        )
    ])

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=buttons
    )

    await callback.message.answer(
        "📩 Открытые обращения:",
        reply_markup=keyboard
    )

    await callback.answer()


# =========================
# АДМИН: ОТКРЫТЬ ОБРАЩЕНИЕ
# =========================

@dp.callback_query(F.data.startswith("ticket_"))
async def open_ticket(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "⛔ У вас нет доступа.",
            show_alert=True
        )
        return

    ticket_id = int(callback.data.split("_")[1])

    ticket = get_ticket(ticket_id)

    if not ticket:
        await callback.answer(
            "❌ Обращение не найдено.",
            show_alert=True
        )
        return

    _, user_id, username, text, status = ticket

    if status == "open":
        status_text = "🔴 Открыто"
    else:
        status_text = "✅ Закрыто"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Ответить",
                    callback_data=f"reply_{ticket_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Закрыть",
                    callback_data=f"close_{ticket_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="admin_tickets"
                )
            ]
        ]
    )

    await callback.message.answer(
        f"🆘 Обращение #{ticket_id}\n\n"
        f"👤 Пользователь: @{username}\n"
        f"🆔 ID: {user_id}\n"
        f"📌 Статус: {status_text}\n\n"
        f"📝 Обращение:\n{text}",
        reply_markup=keyboard
    )

    await callback.answer()


# =========================
# АДМИН: ОТВЕТ
# =========================

@dp.callback_query(F.data.startswith("reply_"))
async def reply_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "⛔ У вас нет доступа.",
            show_alert=True
        )
        return

    ticket_id = int(callback.data.split("_")[1])

    ticket = get_ticket(ticket_id)

    if not ticket:
        await callback.answer(
            "❌ Обращение не найдено.",
            show_alert=True
        )
        return

    await state.update_data(ticket_id=ticket_id)
    await state.set_state(AdminStates.waiting_for_reply)

    await callback.message.answer(
        f"✍️ Напишите ответ на обращение #{ticket_id}."
    )

    await callback.answer()


@dp.message(AdminStates.waiting_for_reply)
async def send_reply(
    message: Message,
    state: FSMContext
):
    if message.from_user.id != ADMIN_ID:
        return

    data = await state.get_data()
    ticket_id = data.get("ticket_id")

    if not ticket_id:
        await state.clear()
        return

    ticket = get_ticket(ticket_id)

    if not ticket:
        await state.clear()

        await message.answer(
            "❌ Обращение не найдено."
        )
        return

    user_id = ticket[1]

    if not message.text:
        await message.answer(
            "❌ Ответ должен быть обычным текстовым сообщением."
        )
        return

    try:
        await bot.send_message(
            user_id,
            f"💬 Ответ технической поддержки\n\n"
            f"{message.text}\n\n"
            f"📩 Обращение #{ticket_id}"
        )

        await message.answer(
            f"✅ Ответ отправлен пользователю.\n\n"
            f"📩 Обращение #{ticket_id}",
            reply_markup=admin_menu()
        )

    except Exception:
        await message.answer(
            "❌ Не удалось отправить сообщение пользователю.\n"
            "Возможно, пользователь заблокировал бота."
        )

    await state.clear()


# =========================
# АДМИН: ЗАКРЫТИЕ
# =========================

@dp.callback_query(F.data.startswith("close_"))
async def close_ticket_handler(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "⛔ У вас нет доступа.",
            show_alert=True
        )
        return

    ticket_id = int(callback.data.split("_")[1])

    ticket = get_ticket(ticket_id)

    if not ticket:
        await callback.answer(
            "❌ Обращение не найдено.",
            show_alert=True
        )
        return

    user_id = ticket[1]

    close_ticket(ticket_id)

    try:
        await bot.send_message(
            user_id,
            f"✅ Обращение #{ticket_id} закрыто.\n\n"
            "Если у вас появится новый вопрос, создайте новое обращение.",
            reply_markup=user_menu()
        )
    except Exception:
        pass

    await callback.message.answer(
        f"✅ Обращение #{ticket_id} закрыто.",
        reply_markup=admin_menu()
    )

    await callback.answer()


# =========================
# ЗАПУСК
# =========================

async def main():
    init_database()

    print("VexMart Support 0.1 запущен!")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
