"""
Создание Bot и Dispatcher, регистрация middleware и роутеров.
"""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher

from app import config
from app.middlewares import AccessMiddleware
from app.handlers import register_handlers

log = logging.getLogger(__name__)


def build_bot() -> Bot:
    return Bot(token=config.BOT_TOKEN)


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()

    # Middleware на доступ
    dp.message.middleware(AccessMiddleware())
    dp.callback_query.middleware(AccessMiddleware())

    # Роутеры из app/handlers/*
    register_handlers(dp)

    return dp
