"""Хендлеры бота, разбитые по роутерам."""
from __future__ import annotations

from aiogram import Dispatcher

from . import start, auth, checkin, info


def register_handlers(dp: Dispatcher) -> None:
    """Подключает все роутеры к диспетчеру."""
    dp.include_router(start.router)
    dp.include_router(auth.router)
    dp.include_router(info.router)
    # /checkin и /auto — последним, чтобы не перехватывал чужие команды
    dp.include_router(checkin.router)


__all__ = ["register_handlers"]
