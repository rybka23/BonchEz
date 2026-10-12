"""FSM-состояния бота."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class LoginStates(StatesGroup):
    """Процесс ввода логина и пароля от ЛК."""
    waiting_login = State()
    waiting_password = State()
