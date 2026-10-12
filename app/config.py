"""
Конфигурация бота.
Значения можно переопределить через переменные окружения (.env).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Подгружаем .env из корня проекта (на два уровня выше этого файла)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# ───────────────────────────────────────── Telegram ──
# Токен от @BotFather
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "PASTE_YOUR_TOKEN_HERE")

# Список telegram ID, кому разрешено пользоваться ботом.
# Узнать свой ID: @userinfobot. Если пусто — доступ открыт всем,
# кто смог войти в ЛК (НЕ рекомендуется для прод-бота).
ALLOWED_USER_IDS: set[int] = {
    int(x)
    for x in os.getenv("ALLOWED_USER_IDS", "").replace(",", " ").split()
    if x.strip().isdigit()
}

# ───────────────────────────────────────── ЛК ────
BONCH_BASE_URL: str = os.getenv("BONCH_BASE_URL", "https://lk.sut.ru")
BONCH_CABINET_URL: str = f"{BONCH_BASE_URL}/cabinet/"

# ─────────────────────────────────── Авто-отметка ──
# Интервал в минутах. Кнопка «Отметиться» появляется только во время
# пары — слишком частая проверка бессмысленна и может привести к
# блокировке. Минимум — 1 минута.
AUTO_CHECK_INTERVAL_MIN: int = int(os.getenv("AUTO_CHECK_INTERVAL_MIN", "3"))

# ─────────────────────────────────── Хранилище ────
# Куда складываем SQLite-базу с аккаунтами (зашифрованные пароли)
DATA_DIR: Path = _PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH: Path = Path(os.getenv("DB_PATH", str(DATA_DIR / "bonch_bot.db")))

# Ключ для шифрования паролей в БД. 32 байта (Fernet). Сгенерируйте свой:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FERNET_KEY: str = os.getenv(
    "FERNET_KEY",
    "REPLACE_ME_WITH_FERNET_GENERATED_KEY",
)
