"""Команды /status, /schedule, /lessons."""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from bs4 import BeautifulSoup

from app.sessions import get_or_restore_client
from app.runtime import store, auto_enabled, sessions

log = logging.getLogger(__name__)
router = Router(name="info")


@router.message(Command("status"))
async def cmd_status(message: Message):
    acc = store.get_account(message.from_user.id)
    if not acc:
        await message.answer("❌ Ты не залогинен. Используй /login")
        return

    client = sessions.get(message.from_user.id)
    if client and await client.is_logged_in():
        auto = "включена" if auto_enabled.get(message.from_user.id) else "выключена"
        await message.answer(
            f"✅ Сессия ЛК жива\n"
            f"Логин: {acc.login}\n"
            f"ID в ЛК: {acc.bonch_user_id or '—'}\n"
            f"Авто-отметка: {auto}"
        )
    else:
        reactivated = await get_or_restore_client(message.from_user.id)
        if reactivated:
            await message.answer("✅ Сессия восстановлена — я тебя перезалогинил")
        else:
            await message.answer(
                "⚠️ Сессия истекла и не удалось войти заново. "
                "Пароль изменился? Сделай /login заново."
            )


@router.message(Command("schedule"))
async def cmd_schedule(message: Message):
    """Показывает расписание на сегодня в виде простого текста."""
    client = await get_or_restore_client(message.from_user.id)
    if not client:
        await message.answer("Сначала /login")
        return

    status_msg = await message.answer("⏳ Гружу расписание...")
    try:
        html = await client.fetch_today_schedule_html()
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n", strip=True)
        snippet = text[:1500]
        await status_msg.edit_text(
            f"📅 Расписание на сегодня:\n\n{snippet or 'пусто'}"
        )
    except Exception as e:
        log.exception("Ошибка загрузки расписания")
        await status_msg.edit_text(f"⚠️ Ошибка: {e}")


@router.message(Command("lessons"))
async def cmd_lessons(message: Message):
    """
    Показывает список занятий на сегодня с ID, по которым можно отметиться.
    Полезно для отладки и для /checkin <ID>.
    """
    client = await get_or_restore_client(message.from_user.id)
    if not client:
        await message.answer("Сначала /login")
        return

    status_msg = await message.answer("⏳ Гружу и парсю расписание...")
    try:
        html = await client.fetch_today_schedule_html()
        lessons = client.parse_lessons(html)
        if not lessons:
            await status_msg.edit_text(
                "В расписании на сегодня нет занятий с кнопкой отметки. "
                "Возможно, сегодня выходной или все пары уже прошли."
            )
            return

        lines = [f"📚 Найдено занятий: {len(lessons)}\n"]
        for i, l in enumerate(lessons, 1):
            lines.append(
                f"{i}. {l.time} — {l.subject} ({l.lesson_type})\n"
                f"   👨‍🏫 {l.teacher}  📍 {l.room}\n"
                f"   🆔 ID: {l.lesson_id}"
            )
        await status_msg.edit_text("\n".join(lines))
    except Exception as e:
        log.exception("Ошибка разбора расписания")
        await status_msg.edit_text(f"⚠️ Ошибка: {e}")
