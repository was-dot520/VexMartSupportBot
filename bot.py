import os
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Update,
)
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage


# =========================================================
# VEXMART SUPPORT 0.1.1
# =========================================================

BOT_VERSION = "0.1.1"

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Несколько администраторов через запятую:
# ADMIN_IDS=123456789,987654321,555555555
ADMIN_IDS = {
    int(admin_id.strip())
    for admin_id in os.getenv("ADMIN_IDS", "").split(",")
    if admin_id.strip()
}

PORT = int(os.getenv("PORT", "10000"))

RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

VEXMART_CHANNEL = "https://t.me/VexMart"

DATABASE = "support.db"

WEBHOOK_PATH = "/webhook"


# =========================================================
# ПРОВЕРКА НАСТРОЕК
# =========================================================

if not BOT_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN")

if not ADMIN_IDS:
    raise RuntimeError("Не задан ADMIN_IDS")

if not RENDER_EXTERNAL_URL:
    raise RuntimeError(
        "Не задан RENDER_EXTERNAL_URL. "
        "Render должен предоставить его автоматически."
    )


WEBHOOK_URL = (
    RENDER_EXTERNAL_URL.rstrip("/")
    + WEBHOOK_PATH
)


# =========================================================
# БАЗА ДАННЫХ
# =========================================================

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


def create_ticket(
    user_id: int,
    username: str,
    text: str
):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO tickets
        (user_id, username, text, status)
        VALUES (?, ?, ?, 'open')
        """,
        (
            user_id,
            username,
            text
        )
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


def get_user_tickets(user_id: int):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, text, status
        FROM tickets
        WHERE user_id = ?
        ORDER BY id DESC
    """, (user_id,))

    tickets = cursor.fetchall()

    conn.close()

    return tickets


# =========================================================
# СОСТОЯНИЯ
# =========================================================

class UserStates(StatesGroup):
    waiting_for_ticket = State()


class AdminStates(StatesGroup):
    waiting_for_reply = State()


# =========================================================
# КЛАВИАТУРЫ
# =========================================================

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


# =========================================================
# BOT / DISPATCHER
# =========================================================

bot = Bot(
    token=BOT_TOKEN
)

dp = Dispatcher(
    storage=MemoryStorage()
)


# =========================================================
# /START
# =========================================================

@dp.message(CommandStart())
async def start_handler(
    message: Message,
    state: FSMContext
):
    await state.clear()

    if message.from_user.id in ADMIN_IDS:
        await message.answer(
            f"🛠️ VexMart Support {BOT_VERSION}\n\n"
            "Панель администратора:",
            reply_markup=admin_menu()
        )
    else:
        await message.answer(
            "👋 Добро пожаловать в техническую "
            "поддержку VexMart!\n\n"
            "Выберите нужное действие:",
            reply_markup=user_menu()
        )


# =========================================================
# СОЗДАНИЕ ОБРАЩЕНИЯ
# =========================================================

@dp.callback_query(F.data == "create_ticket")
async def create_ticket_start(
    callback: CallbackQuery,
    state: FSMContext
):
    await state.set_state(
        UserStates.waiting_for_ticket
    )

    await callback.message.answer(
        "📝 Опишите вашу проблему или вопрос.\n\n"
        "Отправьте сообщение следующим сообщением."
    )

    await callback.answer()


@dp.message(UserStates.waiting_for_ticket)
async def create_ticket_message(
    message: Message,
    state: FSMContext
):
    if not message.text:
        await message.answer(
            "❌ Пока что обращения можно отправлять "
            "только текстом."
        )
        return

    username = (
        message.from_user.username
        or "без username"
    )

    ticket_id = create_ticket(
        user_id=message.from_user.id,
        username=username,
        text=message.text
    )

    await state.clear()

    await message.answer(
        f"✅ Обращение #{ticket_id} создано!\n\n"
        "Ожидайте ответа технической поддержки.",
        reply_markup=user_menu()
    )

    # Уведомляем всех администраторов
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🔴 Новое обращение #{ticket_id}\n\n"
                f"👤 Пользователь: @{username}\n"
                f"🆔 ID: {message.from_user.id}\n\n"
                f"📝 {message.text}",
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
        except Exception as error:
            print(
                f"Не удалось уведомить администратора "
                f"{admin_id}: {error}"
            )


# =========================================================
# МОИ ОБРАЩЕНИЯ
# =========================================================

@dp.callback_query(F.data == "my_tickets")
async def my_tickets(
    callback: CallbackQuery
):
    tickets = get_user_tickets(
        callback.from_user.id
    )

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


# =========================================================
# АДМИН — СПИСОК ОБРАЩЕНИЙ
# =========================================================

@dp.callback_query(F.data == "admin_tickets")
async def admin_tickets(
    callback: CallbackQuery
):
    if callback.from_user.id not in ADMIN_IDS:
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

    await callback.message.answer(
        "📩 Открытые обращения:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )

    await callback.answer()


# =========================================================
# АДМИН — ОТКРЫТЬ ОБРАЩЕНИЕ
# =========================================================

@dp.callback_query(F.data.startswith("ticket_"))
async def open_ticket(
    callback: CallbackQuery
):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(
            "⛔ У вас нет доступа.",
            show_alert=True
        )
        return

    ticket_id = int(
        callback.data.split("_")[1]
    )

    ticket = get_ticket(ticket_id)

    if not ticket:
        await callback.answer(
            "❌ Обращение не найдено.",
            show_alert=True
        )
        return

    _, user_id, username, text, status = ticket

    status_text = (
        "🔴 Открыто"
        if status == "open"
        else "✅ Закрыто"
    )

    buttons = []

    if status == "open":
        buttons.append([
            InlineKeyboardButton(
                text="💬 Ответить",
                callback_data=f"reply_{ticket_id}"
            )
        ])

        buttons.append([
            InlineKeyboardButton(
                text="✅ Закрыть",
                callback_data=f"close_{ticket_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="admin_tickets"
        )
    ])

    await callback.message.answer(
        f"🆘 Обращение #{ticket_id}\n\n"
        f"👤 Пользователь: @{username}\n"
        f"🆔 ID: {user_id}\n"
        f"📌 Статус: {status_text}\n\n"
        f"📝 Обращение:\n{text}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )

    await callback.answer()


# =========================================================
# АДМИН — ОТВЕТИТЬ
# =========================================================

@dp.callback_query(F.data.startswith("reply_"))
async def reply_start(
    callback: CallbackQuery,
    state: FSMContext
):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(
            "⛔ У вас нет доступа.",
            show_alert=True
        )
        return

    ticket_id = int(
        callback.data.split("_")[1]
    )

    ticket = get_ticket(ticket_id)

    if not ticket:
        await callback.answer(
            "❌ Обращение не найдено.",
            show_alert=True
        )
        return

    await state.update_data(
        ticket_id=ticket_id
    )

    await state.set_state(
        AdminStates.waiting_for_reply
    )

    await callback.message.answer(
        f"✍️ Напишите ответ на обращение #{ticket_id}."
    )

    await callback.answer()


@dp.message(AdminStates.waiting_for_reply)
async def send_reply(
    message: Message,
    state: FSMContext
):
    if message.from_user.id not in ADMIN_IDS:
        return

    if not message.text:
        await message.answer(
            "❌ Пока что ответ можно отправить "
            "только текстом."
        )
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

    except Exception as error:
        print(
            f"Ошибка отправки ответа: {error}"
        )

        await message.answer(
            "❌ Не удалось отправить ответ.\n\n"
            "Возможно, пользователь заблокировал бота."
        )

    await state.clear()


# =========================================================
# АДМИН — ЗАКРЫТЬ ОБРАЩЕНИЕ
# =========================================================

@dp.callback_query(F.data.startswith("close_"))
async def close_ticket_handler(
    callback: CallbackQuery
):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(
            "⛔ У вас нет доступа.",
            show_alert=True
        )
        return

    ticket_id = int(
        callback.data.split("_")[1]
    )

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
            "Если у вас появится новый вопрос, "
            "создайте новое обращение.",
            reply_markup=user_menu()
        )
    except Exception as error:
        print(
            f"Не удалось уведомить пользователя: {error}"
        )

    await callback.message.answer(
        f"✅ Обращение #{ticket_id} закрыто.",
        reply_markup=admin_menu()
    )

    await callback.answer()


# =========================================================
# FASTAPI / RENDER
# =========================================================

@asynccontextmanager
async def lifespan(app: FastAPI):

    init_database()

    await bot.set_webhook(
        url=WEBHOOK_URL
    )

    print(
        f"VexMart Support {BOT_VERSION} запущен!"
    )

    print(
        f"Администраторы: {sorted(ADMIN_IDS)}"
    )

    print(
        f"Webhook: {WEBHOOK_URL}"
    )

    yield

    await bot.delete_webhook()

    await bot.session.close()


app = FastAPI(
    title="VexMart Support",
    version=BOT_VERSION,
    lifespan=lifespan
)


# =========================================================
# HEALTH CHECK
# =========================================================

@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "VexMart Support",
        "version": BOT_VERSION
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy"
    }


# =========================================================
# TELEGRAM WEBHOOK
# =========================================================

@app.post(WEBHOOK_PATH)
async def telegram_webhook(
    request: Request
):
    try:
        data = await request.json()

        update = Update.model_validate(
            data,
            context={"bot": bot}
        )

        await dp.feed_update(
            bot,
            update
        )

        return {
            "ok": True
        }

    except Exception as error:

        print(
            f"Webhook error: {error}"
        )

        raise HTTPException(
            status_code=500,
            detail="Webhook processing error"
        )


# =========================================================
# ЗАПУСК
# =========================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=PORT
    )