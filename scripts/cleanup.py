"""
Скрипт очистки проекта от временных и мусорных файлов.

Запуск на Windows:
    cd C:\\Users\\mrspe\\Desktop\\bonch-tg
    python scripts/cleanup.py

Запуск на Linux/macOS:
    cd ~/BonchEz
    python scripts/cleanup.py

Удаляет:
  - __pycache__ во всех подпапках
  - *.pyc, *.pyo
  - .pytest_cache, .mypy_cache, .ruff_cache
  - .venv (НЕ удаляет! только предупреждение)
  - data/*.db, data/*.db-journal
  - .env (только предупреждение — не удаляет)
  - лишние файлы в корне: diag_login.py, test_with_cookies.py,
    test.py, debug.py, scratch.py
  - .DS_Store, Thumbs.db, desktop.ini
  - *.log, *.tmp, *.bak

НЕ удаляет:
  - .env (твой с секретами)
  - .venv/ (твоё виртуальное окружение)
  - data/ (папку, только *.db внутри)
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


# Что удаляем без вопросов
JUNK_PATTERNS = [
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".coverage",
    "htmlcov",
    "*.egg-info",
    "build",
    "dist",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    "*.log",
    "*.tmp",
    "*.bak",
    "*.orig",
    "*.swp",
    "*.swo",
    "*~",
    ".ipynb_checkpoints",
]

# Файлы в корне, которые должны лежать в scripts/, а не в корне
MISPLACED_IN_ROOT = [
    "diag_login.py",
    "test_with_cookies.py",
    "test.py",
    "debug.py",
    "scratch.py",
    "scratch_pad.py",
]

# В data/ удаляем только базы и логи, не саму папку
DATA_JUNK = ["*.db", "*.db-journal", "*.db-wal", "*.db-shm", "*.sqlite", "*.sqlite3", "*.log", "*.tmp"]


def find_junk(root: Path) -> list[Path]:
    """Находит все мусорные файлы и папки."""
    junk: list[Path] = []

    # 1. Папки и файлы по точному имени / глоб-паттерну
    for pattern in JUNK_PATTERNS:
        # Папки
        for p in root.rglob(pattern):
            if p.is_dir():
                junk.append(p)
        # Файлы (rglob уже покрывает оба случая, но для надёжности)
        for p in root.rglob(pattern):
            if p.is_file() and p not in junk:
                junk.append(p)

    # 2. Misplaced files в корне
    for name in MISPLACED_IN_ROOT:
        p = root / name
        if p.exists() and p.is_file():
            junk.append(p)

    # 3. data/ — только мусорные файлы внутри
    data_dir = root / "data"
    if data_dir.is_dir():
        for pattern in DATA_JUNK:
            for p in data_dir.glob(pattern):
                if p.is_file():
                    junk.append(p)

    return junk


def main():
    # Корень проекта — родитель родителя этого скрипта
    root = Path(__file__).resolve().parent.parent
    print(f"Корень проекта: {root}\n")

    if not (root / "app").is_dir() or not (root / "requirements.txt").is_file():
        print("❌ Это не похоже на корень проекта bonch_tg_bot.")
        print("   Ожидаю увидеть app/ и requirements.txt рядом со скриптом.")
        sys.exit(1)

    junk = find_junk(root)
    if not junk:
        print("✅ Проект чист — мусорных файлов не найдено.")
        return

    print(f"Найдено мусорных файлов/папок: {len(junk)}\n")
    total_size = 0
    for p in junk:
        try:
            if p.is_dir():
                size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
                total_size += size
                print(f"  [DIR]  {p.relative_to(root)}  ({size // 1024} KB)")
            else:
                size = p.stat().st_size
                total_size += size
                print(f"  [FILE] {p.relative_to(root)}  ({size} B)")
        except (PermissionError, OSError) as e:
            print(f"  [ERR]  {p.relative_to(root)}  ({e})")

    print(f"\nВсего мусора: {total_size // 1024} KB\n")

    # Подтверждение
    if "--yes" not in sys.argv:
        answer = input("Удалить всё это? [y/N] ").strip().lower()
        if answer not in ("y", "yes", "д", "да"):
            print("Отмена. Ничего не удалено.")
            return

    # Удаляем
    deleted = 0
    for p in junk:
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            deleted += 1
        except (PermissionError, OSError) as e:
            print(f"  ❌ Не удалось удалить {p}: {e}")

    print(f"\n✅ Удалено: {deleted} из {len(junk)}")

    # Проверки, что НЕ нужно удалять
    print("\nПроверки (что НЕ удалено и должно остаться):")
    env = root / ".env"
    if env.exists():
        print(f"  ✓ .env на месте (секреты сохранены)")
    venv = root / ".venv"
    if venv.exists():
        print(f"  ✓ .venv на месте (окружение сохранено)")
    data = root / "data"
    if data.exists():
        print(f"  ✓ data/ на месте (папка сохранена, базы удалены)")


if __name__ == "__main__":
    main()
