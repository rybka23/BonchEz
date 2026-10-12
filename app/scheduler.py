"""
Планировщик авто-отметки.

Каждые AUTO_CHECK_INTERVAL_MIN минут обходит пользователей с включённой
авто-отметкой и пытается нажать кнопку «Отметиться».
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app import config
from app.bot import build_bot
from app.runtime import auto_enabled
from app.sessions import get_or_restore_client

log = logging.getLogger(__name__)


async def auto_checkin_job(bot) -> None:
    """Периодически проверяет, появилась ли кнопка «Отметиться»."""
    if not auto_enabled:
        return
    log.info("Auto-checkin: проверяю для %d пользователей", len(auto_enabled))

    for tg_user_id in list(auto_enabled.keys()):
        if not auto_enabled.get(tg_user_id):
            continue
        client = await get_or_restore_client(tg_user_id)
        if not client:
            log.warning("Auto-checkin: нет клиента для user_id=%s", tg_user_id)
            continue
        try:
            result = await client.mark_lesson()
            if result.success:
                snippet = result.message[:200] if result.message else "OK"
                await bot.send_message(
                    tg_user_id,
                    f"✅ Авто-отметка сработала!\n\n📄 {snippet}",
                )
                # После успешной отметки отключаем авто до следующего /auto on
                auto_enabled.pop(tg_user_id, None)
            else:
                log.info("Auto-checkin: %s — %s", tg_user_id, result.message)
        except Exception:
            log.exception("Auto-checkin ошибка для user_id=%s", tg_user_id)


def start_scheduler(bot) -> AsyncIOScheduler:
    """Создаёт и запускает AsyncIOScheduler с одной задачей авто-отметки."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        auto_checkin_job,
        "interval",
        minutes=config.AUTO_CHECK_INTERVAL_MIN,
        id="auto_checkin",
        args=[bot],
    )
    scheduler.start()
    log.info(
        "Планировщик запущен. AUTO_CHECK_INTERVAL_MIN=%s",
        config.AUTO_CHECK_INTERVAL_MIN,
    )
    return scheduler
