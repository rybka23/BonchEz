"""
Точка входа: запускает бот + планировщик.

Запуск:
    python -m app.main
или (из корня проекта):
    python app/main.py
"""
from __future__ import annotations

import asyncio
import logging
import sys

from app import config
from app.bot import build_bot, build_dispatcher
from app.runtime import sessions, store


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )


async def main() -> None:
    _setup_logging()
    log = logging.getLogger("bonch_bot.main")

    if "PASTE_YOUR_TOKEN_HERE" in config.BOT_TOKEN or not config.BOT_TOKEN.strip():
        log.error(
            "❌ BOT_TOKEN не задан в .env. Скопируй .env.example → .env "
            "и подставь токен от @BotFather."
        )
        sys.exit(1)

    if store.is_using_ephemeral_key:
        log.warning(
            "⚠️ FERNET_KEY не задан в .env — пароли шифруются временным ключом, "
            "который потеряется при перезапуске. Сгенерируйте постоянный ключ "
            "и укажите его в .env."
        )

    bot = build_bot()
    dp = build_dispatcher()

    # Планировщик с авто-отметкой
    from app.scheduler import start_scheduler
    scheduler = start_scheduler(bot)

    log.info("Бот запущен.")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        for c in sessions.values():
            await c.aclose()
        await bot.session.close()


if __name__ == "__main__":
    # Поддержка запуска как `python app/main.py` из корня проекта.
    # Тогда нужно добавить корень в sys.path, чтобы импорт `app.*` работал.
    import os
    from pathlib import Path

    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

    asyncio.run(main())
