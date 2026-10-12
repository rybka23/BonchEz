"""
Хелпер переавторизации: возвращает живой BonchClient.
Кэш sessions и AccountStore берутся из app.runtime, чтобы не было
циклических импортов.
"""
from __future__ import annotations

import logging
from typing import Optional

from app import config
from app.runtime import sessions, store
from app.services.bonch_client import BonchClient, BonchLoginError

log = logging.getLogger(__name__)


async def get_or_restore_client(tg_user_id: int) -> Optional[BonchClient]:
    """
    Возвращает живой BonchClient для пользователя.
    Если сессии нет — читает аккаунт из БД, логинится заново.
    """
    if tg_user_id in sessions:
        client = sessions[tg_user_id]
        if await client.is_logged_in():
            return client
        log.info("Сессия истекла для user_id=%s — переавторизация", tg_user_id)
        await client.aclose()
        del sessions[tg_user_id]

    acc = store.get_account(tg_user_id)
    if not acc:
        return None

    client = BonchClient(base_url=config.BONCH_BASE_URL)
    try:
        bonch_user_id = await client.login(acc.login, acc.password)
        if acc.bonch_user_id != bonch_user_id:
            store.save_account(tg_user_id, acc.login, acc.password, bonch_user_id)
        sessions[tg_user_id] = client
        return client
    except BonchLoginError as e:
        log.warning("Переавторизация не удалась для user_id=%s: %s", tg_user_id, e)
        await client.aclose()
        return None
