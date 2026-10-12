"""Команды /start и /help."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app import config

router = Router(name="start")

HELP_TEXT = (
    "👋 Привет! Я помогу отметиться на паре через lk.sut.ru\n\n"
    "Команды:\n"
    "  /login — ввести логин и пароль от ЛК\n"
    "  /checkin — отметиться прямо сейчас (на первой доступной паре)\n"
    "  /lessons — показать все занятия на сегодня с их ID\n"
    "  /schedule — расписание на сегодня (HTML → текст)\n"
    "  /status — проверить, залогинен ли я\n"
    f"  /auto on — включить авто-отметку (каждые {config.AUTO_CHECK_INTERVAL_MIN} мин)\n"
    "  /auto off — выключить\n"
    "  /logout — забыть мои данные\n\n"
    "ℹ️ Кнопка «Начать занятие» в ЛК появляется за 10 минут до начала пары "
    "и исчезает после её окончания. Если сейчас нет пары — /checkin скажет, "
    "когда появится кнопка.\n\n"
    "⚠️ Используй на свой страх и риск. Автоматизация отметки — "
    "серая зона по правилам университета."
)


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(HELP_TEXT)


@router.message(Command("help"))
async def cmd_help(message: Message):
    await cmd_start(message)
