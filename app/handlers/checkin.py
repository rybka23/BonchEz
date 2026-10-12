"""Команды /checkin и /auto (on/off)."""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.services.bonch_client import MarkResult
from app.sessions import get_or_restore_client
from app.runtime import store, auto_enabled

log = logging.getLogger(__name__)
router = Router(name="checkin")


@router.message(Command("checkin"))
async def cmd_checkin(message: Message):
    client = await get_or_restore_client(message.from_user.id)
    if not client:
        await message.answer("Сначала /login")
        return

    status_msg = await message.answer("⏳ Ищу кнопку «Отметиться»...")
    try:
        result: MarkResult = await client.mark_lesson()
    except Exception as e:
        log.exception("Ошибка при отметке")
        await status_msg.edit_text(f"⚠️ Ошибка: {e}")
        return

    if result.success:
        snippet = result.message[:200] if result.message else "Готово"
        await status_msg.edit_text(
            f"✅ Отметка отправлена!\n\n📄 Ответ сервера:\n{snippet}"
        )
    else:
        await status_msg.edit_text(f"ℹ️ {result.message}")


@router.message(Command("auto"))
async def cmd_auto(message: Message):
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or args[1].lower() not in ("on", "off", "вкл", "выкл"):
        await message.answer(
            "Использование: /auto on  или  /auto off\n"
            f"Сейчас авто-отметка: "
            f"{'включена' if auto_enabled.get(message.from_user.id) else 'выключена'}"
        )
        return

    turn_on = args[1].lower() in ("on", "вкл")
    if turn_on:
        if not store.get_account(message.from_user.id):
            await message.answer("Сначала /login")
            return
        auto_enabled[message.from_user.id] = True
        from app import config
        await message.answer(
            "✅ Авто-отметка включена. Каждые "
            f"{config.AUTO_CHECK_INTERVAL_MIN} мин я буду проверять, "
            "появилась ли кнопка «Отметиться», и жать её."
        )
    else:
        auto_enabled.pop(message.from_user.id, None)
        await message.answer("🛑 Авто-отметка выключена.")
