"""Логин и логаут: /login (FSM), /logout."""
from __future__ import annotations

import logging
from contextlib import suppress

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app import config
from app.runtime import sessions
from app.services.bonch_client import BonchClient, BonchLoginError
from app.states import LoginStates
from app.sessions import get_or_restore_client

log = logging.getLogger(__name__)
router = Router(name="auth")


@router.message(Command("login"))
async def cmd_login(message: Message, state: FSMContext):
    await state.set_state(LoginStates.waiting_login)
    await message.answer(
        "📧 Введи логин от ЛК (обычно это номер студенческого билета):"
    )


@router.message(LoginStates.waiting_login)
async def process_login(message: Message, state: FSMContext):
    await state.update_data(login=message.text.strip())
    await state.set_state(LoginStates.waiting_password)
    await message.answer("🔑 Введи пароль:")


@router.message(LoginStates.waiting_password)
async def process_password(message: Message, state: FSMContext):
    data = await state.get_data()
    login = data["login"]
    password = message.text or ""

    # Удаляем сообщение с паролем из чата — безопасность
    with suppress(Exception):
        await message.delete()

    await state.clear()
    status_msg = await message.answer("⏳ Вхожу в ЛК...")

    # Логинимся через временный клиент; если успешно — сохраняем
    from app.runtime import store

    client = BonchClient(base_url=config.BONCH_BASE_URL)
    try:
        bonch_user_id = await client.login(login, password)
    except BonchLoginError as e:
        await client.aclose()
        await status_msg.edit_text(f"❌ Не удалось войти:\n{e}")
        return
    except Exception as e:
        await client.aclose()
        log.exception("Непредвиденная ошибка входа")
        await status_msg.edit_text(f"⚠️ Ошибка: {e}")
        return

    store.save_account(message.from_user.id, login, password, bonch_user_id)
    sessions[message.from_user.id] = client
    await status_msg.edit_text(
        f"✅ Успешный вход! ID в ЛК: {bonch_user_id}\n\n"
        "Теперь используй /checkin, чтобы отметиться, или /auto on "
        "для автоматической отметки."
    )


@router.message(Command("logout"))
async def cmd_logout(message: Message):
    client = sessions.pop(message.from_user.id, None)
    if client:
        from asyncio import shield
        try:
            await shield(client.aclose())
        except Exception:
            pass

    from app.runtime import store, auto_enabled
    store.delete_account(message.from_user.id)
    auto_enabled.pop(message.from_user.id, None)
    await message.answer("🚪 Данные удалены из памяти бота. Сессия ЛК закрыта.")
