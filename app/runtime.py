"""
Разделяемое runtime-состояние бота.

Здесь хранятся:
  - store: AccountStore (SQLite + Fernet)
  - sessions: кэш активных BonchClient-ов
  - auto_enabled: кому включена авто-отметка

Вынесено в отдельный модуль, чтобы handlers и scheduler могли
импортировать его без циклической зависимости на app.bot.
"""
from __future__ import annotations

from app import config
from app.services.bonch_client import BonchClient
from app.services.storage import AccountStore

# Хранилище аккаунтов (SQLite + Fernet-шифрование паролей)
store: AccountStore = AccountStore(config.DB_PATH, config.FERNET_KEY)

# Кэш открытых сессий ЛК {tg_user_id: BonchClient}
sessions: dict[int, BonchClient] = {}

# {tg_user_id: bool} — включена ли авто-отметка
auto_enabled: dict[int, bool] = {}
