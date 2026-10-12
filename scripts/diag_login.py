"""
Диагностический скрипт для входа в lk.sut.ru — без Telegram-бота.

Запуск на сервере (в venv):
    cd ~/BonchEz
    source .venv/bin/activate
    python scripts/diag_login.py

Покажет:
  - Какие cookies получили от главной
  - Какие headers отправили на POST
  - Что ответил сервер (status, body, headers)
  - Если прошла — пробует загрузить расписание
"""
import asyncio
import os
import sys
from pathlib import Path

# Подготовим sys.path, чтобы импорт app.* работал
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Подгрузим .env, если есть (чтобы не вводить пароль в открытую)
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import httpx
from app.services.bonch_client import USER_AGENT


BASE_URL = "https://lk.sut.ru"
CABINET_URL = f"{BASE_URL}/cabinet/"


async def main():
    login = os.getenv("TEST_LOGIN") or input("Логин (email): ").strip()
    password = os.getenv("TEST_PASSWORD") or input("Пароль: ").strip()

    print(f"\n=== Тестируем логин: {login} ===\n")

    async with httpx.AsyncClient(
        base_url=BASE_URL,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,application/xhtml+xml;q=0.8,*/*;q=0.7"
            ),
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Referer": CABINET_URL,
            "Origin": BASE_URL,
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "X-Requested-With": "XMLHttpRequest",
        },
        follow_redirects=True,
        timeout=httpx.Timeout(20.0, connect=10.0),
    ) as client:

        # ── Шаг 1: GET /cabinet/ — должны получить PHPSESSID
        print("Шаг 1: GET /cabinet/?login=no")
        r1 = await client.get("/cabinet/", params={"login": "no"})
        print(f"  Status: {r1.status_code}")
        print(f"  Final URL: {r1.url}")
        print(f"  Cookies: {dict(client.cookies)}")
        print(f"  Server headers:")
        for k, v in r1.headers.items():
            if k.lower() in ("server", "content-type", "set-cookie", "x-powered-by"):
                print(f"    {k}: {v[:200]}")
        print(f"  Body length: {len(r1.text)} chars")
        print(f"  Body snippet: {r1.text[:200]!r}")
        print()

        # ── Шаг 2: POST autentificationok.php
        print("Шаг 2: POST /cabinet/lib/autentificationok.php")
        await asyncio.sleep(0.5)  # имитируем человека

        r2 = await client.post(
            "/cabinet/lib/autentificationok.php",
            data={"users": login, "parole": password},
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Accept": "*/*",
                "Origin": BASE_URL,
                "Referer": CABINET_URL,
                "X-Requested-With": "XMLHttpRequest",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            },
        )

        print(f"  Status: {r2.status_code}")
        print(f"  Final URL: {r2.url}")
        print(f"  Cookies (after): {dict(client.cookies)}")
        print(f"  Response headers:")
        for k, v in r2.headers.items():
            print(f"    {k}: {v[:200]}")
        print(f"  Body length: {len(r2.text)} chars")
        print(f"  Body snippet (first 500):")
        print("    " + r2.text[:500].replace("\r\n", "\n    ").replace("\n", "\n    "))
        print()

        # ── Анализ
        body = r2.text.strip()
        if "<html" in body.lower()[:200]:
            print("❌ Сервер вернул HTML (а не число) — это блокировка nginx/WAF.")
            print("   Сравни свои request headers с теми, что отправляет браузер.")
            print("   Открой в браузере lk.sut.ru, F12 → Network → войди → найди POST")
            print("   к autentificationok.php → правый клик → Copy → Copy as cURL.")
            print("   Пришли мне этот cURL, и я сравню заголовки.")
            return

        if "|" in body:
            print("⚠️ Сервер вернул ошибку блокировки:")
            parts = dict(p.split("=", 1) for p in body.split("|") if "=" in p)
            for k, v in parts.items():
                print(f"   {k}: {v}")
            return

        try:
            user_id = int(body)
        except ValueError:
            print(f"❌ Неожиданный ответ сервера (не число и не pipe): {body!r}")
            return

        if user_id <= 0:
            print(f"❌ Логин не прошёл (user_id={user_id}). Неверный логин или пароль?")
            return

        print(f"✅ Логин прошёл! user_id={user_id}")
        print()

        # ── Шаг 3: Подтверждение — GET /cabinet/?login=yes
        print("Шаг 3: GET /cabinet/?login=yes — подтверждение входа")
        r3 = await client.get("/cabinet/", params={"login": "yes"})
        print(f"  Status: {r3.status_code}")
        print(f"  Final URL: {r3.url}")
        print(f"  Body snippet: {r3.text[:300]!r}")
        # Если виден профиль/имя пользователя — залогинен
        if "профиль" in r3.text.lower() or "logout" in r3.text.lower() or "выход" in r3.text.lower():
            print("  ✅ Подтверждено: страница профиля/выхода найдена")
        else:
            print("  ⚠️ Страница входа всё ещё показывается — сессия не установилась")
        print()

        # ── Шаг 4: Загрузка расписания
        print("Шаг 4: POST raspisanie.php — загружаем расписание")
        # Сначала history.php (нужно серверу)
        try:
            await client.post(
                "/cabinet/project/cabinet/history.php",
                data={"subconto": "menu", "key": "6118"},
            )
        except Exception as e:
            print(f"  history.php: {e}")
        r4 = await client.post(
            "/cabinet/project/cabinet/forms/raspisanie.php",
            data={"subconto": "menu", "key": "6118"},
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Accept": "*/*",
                "Origin": BASE_URL,
                "Referer": CABINET_URL,
                "X-Requested-With": "XMLHttpRequest",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        print(f"  Status: {r4.status_code}")
        print(f"  Body length: {len(r4.text)} chars")
        # Ищем признаки расписания
        if "update_zan" in r4.text or "knop" in r4.text:
            print("  ✅ Расписание найдено! Есть кнопки отметки (update_zan).")
            # Посчитаем сколько занятий
            import re
            ids = re.findall(r"update_zan\((\d+)\)", r4.text)
            print(f"  Найдено занятий с кнопкой: {len(set(ids))}")
            print(f"  ID занятий: {sorted(set(ids))}")
        else:
            print("  ⚠️ Расписание не распознано. Body snippet:")
            print("    " + r4.text[:500].replace("\n", "\n    "))


if __name__ == "__main__":
    asyncio.run(main())
