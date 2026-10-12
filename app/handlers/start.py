"""Команды /start и /help."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app import config

router = Router(name="start")


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я помогу отметиться на паре через lk.sut.ru\n\n"
        "Команды:\n"
        "  /login — ввести логин и пароль от ЛК\n"
        "  /checkin — отметиться прямо сейчас\n"
        "  /status — проверить, залогинен ли я\n"
        "  /schedule — расписание на сегодня\n"
        f"  /auto on — включить авто-отметку (каждые {config.AUTO_CHECK_INTERVAL_MIN} мин)\n"
        "  /auto off — выключить\n"
        "  /logout — забыть мои данные\n\n"
        "⚠️ Используй на свой страх и риск. Автоматизация отметки — "
        "серая зона по правилам университета."
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await cmd_start(message)
