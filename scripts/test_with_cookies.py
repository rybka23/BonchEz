"""
Тест отметки с куками, скопированными из браузера.

Запуск на сервере (в venv):
    cd ~/BonchEz
    source .venv/bin/activate
    python scripts/test_with_cookies.py

Покажет:
  - Жива ли сессия (проверка через GET /cabinet/?login=yes)
  - Какие занятия найдены в расписании
  - Что ответил сервер при update_zan и open_zan
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import json
from app.services.bonch_client import BonchClient


# ─────────────────── ВСТАВЬ СЮДА КУКИ ИЗ БРАУЗЕРА ───────────────────
# Открой lk.sut.ru в браузере → F12 → Application → Cookies → lk.sut.ru
# Скопируй значения miden и uid (остальное — Яндекс.Метрика, не нужно).

COOKIES = {
    "miden": "8dc0e8989aa954cc9aa3961f1692c4da",  # ← основная сессия
    "uid": "d057ba131406c6e8585086d8546181a8",    # ← id пользователя
    # Опционально:
    # "_ym_d": "1790247006",
    # "_ym_uid": "175613296325869168",
}
# ──────────────────────────────────────────────────────────────────


async def main():
    print("=== Тест отметки с куками из браузера ===\n")
    print(f"Куки: {list(COOKIES.keys())}\n")

    client = BonchClient()
    client.set_cookies(COOKIES)

    # Шаг 1: проверяем, жива ли сессия
    print("Шаг 1: проверяем сессию (GET /cabinet/?login=yes)")
    alive = await client.is_logged_in()
    print(f"  Сессия жива: {alive}")
    if not alive:
        print("\n❌ Сессия протухла. Зайди в ЛК в браузере, скопируй свежие куки")
        print("   и обнови их в scripts/test_with_cookies.py (переменная COOKIES).")
        await client.aclose()
        return
    print()

    # Шаг 2: грузим расписание и парсим занятия
    print("Шаг 2: загружаем расписание")
    html = await client.fetch_today_schedule_html()
    print(f"  HTML расписания: {len(html)} символов")
    if "update_zan" not in html and "knop" not in html:
        print(f"  ⚠️ Расписание не распознано. Body snippet:")
        print("    " + html[:500].replace("\n", "\n    "))
        await client.aclose()
        return

    lessons = client.parse_lessons(html)
    print(f"  Найдено занятий: {len(lessons)}\n")
    for i, l in enumerate(lessons, 1):
        print(f"  {i}. ID={l.lesson_id} week={l.week} time={l.time!r}")
        print(f"     subject={l.subject!r}")
        print(f"     teacher={l.teacher!r} room={l.room!r}")
        print()

    if not lessons:
        print("❌ Нет занятий с кнопкой отметки. Возможно, сегодня выходной.")
        await client.aclose()
        return

    # Шаг 3: для каждого занятия вызываем update_zan (open=3)
    print("Шаг 3: проверяем каждое занятие через update_zan (open=3)")
    for lesson in lessons:
        print(f"\n  → update_zan({lesson.lesson_id}) для «{lesson.subject}»")
        resp_json = await client._call_update_zan(lesson.lesson_id)
        inner_html = resp_json.get("data", "") or ""
        print(f"    JSON.data: {inner_html!r}")

        check = client._analyze_update_zan_response(lesson, inner_html)
        print(f"    Status: {check.status}")
        print(f"    Message: {check.message}")

        if check.status == "can_mark":
            # Реальная отметка
            week = check.week or lesson.week
            print(f"\n  → open_zan({check.open_lesson_id}, week={week}) — РЕАЛЬНАЯ ОТМЕТКА!")
            resp2 = await client._call_open_zan(check.open_lesson_id, week)
            print(f"    JSON ответ: {json.dumps(resp2, ensure_ascii=False)[:500]}")
            inner2 = resp2.get("data", "") or ""
            jid = str(resp2.get("id", "")) or None
            result = client._analyze_open_zan_response(
                lesson, inner2, jid,
                raw_json=json.dumps(resp2, ensure_ascii=False),
            )
            print(f"    ✅ Success: {result.success}")
            print(f"    Message: {result.message}")
            if result.success:
                # Отметились! Дальше не идём
                break
        elif check.status == "already_done":
            print("    (уже отмечен — пропускаем)")
            continue

    print("\n=== Готово ===")
    await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
