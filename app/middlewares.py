"""Middleware-классы бота."""
from __future__ import annotations

import logging
from contextlib import suppress
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from app import config

log = logging.getLogger(__name__)


class AccessMiddleware(BaseMiddleware):
    """Пропускает только пользователей из ALLOWED_USER_IDS (если список задан)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user and config.ALLOWED_USER_IDS and user.id not in config.ALLOWED_USER_IDS:
            log.warning("Доступ запрещён для user_id=%s", user.id)
            if isinstance(event, Message):
                with suppress(Exception):
                    await event.answer("⛔ Доступ запрещён. Этот бот не для тебя.")
            return
        return await handler(event, data)
