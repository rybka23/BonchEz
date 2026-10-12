"""
Хранилище аккаунтов: SQLite + Fernet-шифрование паролей.

Один пользователь Telegram → один аккаунт lk.sut.ru.
Пароль не хранится в открытом виде — шифруется симметричным ключом
Fernet, который вы держите в .env.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet


SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    tg_user_id   INTEGER PRIMARY KEY,
    bonch_login  TEXT NOT NULL,
    bonch_pass_enc BLOB NOT NULL,
    bonch_user_id TEXT,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass
class Account:
    tg_user_id: int
    login: str
    password: str
    bonch_user_id: str | None


class AccountStore:
    def __init__(self, db_path: Path, fernet_key: str):
        self.db_path = db_path
        if "REPLACE_ME" in fernet_key:
            # Ключ не задан — генерируем случайный и работаем (пароли не переживут
            # перезапуск! Это явно небезопасно для прод-бота, но годится для теста).
            self._fernet = Fernet(Fernet.generate_key())
            self._warned = True
        else:
            self._fernet = Fernet(fernet_key.encode())
            self._warned = False
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def save_account(
        self, tg_user_id: int, login: str, password: str, bonch_user_id: str | None
    ) -> None:
        enc = self._fernet.encrypt(password.encode())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO accounts (tg_user_id, bonch_login, bonch_pass_enc, bonch_user_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tg_user_id) DO UPDATE SET
                    bonch_login = excluded.bonch_login,
                    bonch_pass_enc = excluded.bonch_pass_enc,
                    bonch_user_id = excluded.bonch_user_id
                """,
                (tg_user_id, login, enc, bonch_user_id),
            )

    def get_account(self, tg_user_id: int) -> Account | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM accounts WHERE tg_user_id = ?",
                (tg_user_id,),
            ).fetchone()
        if not row:
            return None
        password = self._fernet.decrypt(row["bonch_pass_enc"]).decode()
        return Account(
            tg_user_id=row["tg_user_id"],
            login=row["bonch_login"],
            password=password,
            bonch_user_id=row["bonch_user_id"],
        )

    def delete_account(self, tg_user_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM accounts WHERE tg_user_id = ?", (tg_user_id,)
            )
            return cur.rowcount > 0

    @property
    def is_using_ephemeral_key(self) -> bool:
        return getattr(self, "_warned", False)
