"""
Клиент личного кабинета lk.sut.ru (Бонч-Бруевич).

Эндпоинты восстановлены из JS-файлов сохранённой страницы ЛК:
  - Логин:       POST /cabinet/lib/autentificationok.php
                 Body: users=<login>&parole=<password>
                 Ответ: число (>0 = ID пользователя, 0 = ошибка,
                         либо "key=val|key=val|..." если аккаунт заблокирован)
  - Меню/раздел: POST /cabinet/project/cabinet/history.php
                 Body: subconto=menu&key=<menu_key>
  - Контент:     POST <modul_path>
                 Body: subconto=menu&key=<menu_key>

Ключевая секция для отметки: key=6112,
  modul=project/cabinet/modul/raspisanie/zanatie_jurnal.php
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Ключ меню «Занятие журнала» — раздел с кнопкой «Отметиться»
LESSON_JOURNAL_KEY = "6112"
LESSON_JOURNAL_MODUL = "project/cabinet/modul/raspisanie/zanatie_jurnal.php"

# Ключ меню «Расписание» (на сегодня / на неделю)
SCHEDULE_KEY = "6118"
SCHEDULE_MODUL = "project/cabinet/forms/raspisanie.php"


@dataclass
class MarkResult:
    """Результат попытки отметки."""
    success: bool
    message: str
    raw_html: str | None = None


class BonchLoginError(Exception):
    """Логин не удался."""


class BonchClient:
    """Асинхронный HTTP-клиент ЛК. Один экземпляр = одна сессия."""

    def __init__(self, base_url: str = "https://lk.sut.ru"):
        self.base_url = base_url.rstrip("/")
        self.cabinet_url = f"{self.base_url}/cabinet/"

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                "Referer": self.cabinet_url,
                "X-Requested-With": "XMLHttpRequest",
            },
            follow_redirects=True,
            timeout=httpx.Timeout(20.0, connect=10.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ─────────────────────────────────────────────────────── LOGIN ──

    async def login(self, users: str, parole: str) -> str:
        """
        Авторизация в ЛК.

        Возвращает PHPSESSID (cookie) — он хранится внутри клиента.
        Бросает BonchLoginError при неудаче.
        """
        # 1. Заходим на главную, чтобы получить PHPSESSID и куки
        await self._client.get("/cabinet/")

        # 2. POST на autentificationok.php
        resp = await self._client.post(
            "/cabinet/lib/autentificationok.php",
            data={"users": users, "parole": parole},
        )
        body = resp.text.strip()

        # Если в ответе есть "|" — это блокировка аккаунта или ошибка
        if "|" in body:
            parts = dict(p.split("=", 1) for p in body.split("|") if "=" in p)
            err = parts.get("error", "")
            fio = parts.get("fio", "")
            user = parts.get("users", "")
            raise BonchLoginError(
                f"Вход заблокирован: {err} (пользователь {user} {fio})"
            )

        try:
            user_id = int(body)
        except ValueError as e:
            raise BonchLoginError(f"Неожиданный ответ сервера: {body!r}") from e

        if user_id <= 0:
            raise BonchLoginError("Неверный логин или пароль")

        # 3. Подтверждаем вход — гружим кабинет с ?login=yes
        await self._client.get("/cabinet/", params={"login": "yes"})

        log.info("Успешный вход: user_id=%s", user_id)
        return str(user_id)

    async def is_logged_in(self) -> bool:
        """Живая ли ещё сессия?"""
        resp = await self._client.get(
            "/cabinet/", params={"login": "yes"}, follow_redirects=False
        )
        return resp.status_code == 200 and "login=yes" in str(resp.url)

    # ─────────────────────────────────────────────── LESSON JOURNAL ──

    async def _post_history(self, key: str) -> None:
        """Записывает в history.php (нужно серверу для корректного состояния)."""
        try:
            await self._client.post(
                "/cabinet/project/cabinet/history.php",
                data={"subconto": "menu", "key": key},
            )
        except httpx.HTTPError:
            log.debug("history.php запрос упал для key=%s, продолжаем", key)

    async def fetch_lesson_journal_html(self) -> str:
        """Загружает раздел «Занятие журнала» (key=6112)."""
        await self._post_history(LESSON_JOURNAL_KEY)
        resp = await self._client.post(
            f"/cabinet/{LESSON_JOURNAL_MODUL}",
            data={"subconto": "menu", "key": LESSON_JOURNAL_KEY},
        )
        return resp.text

    # ───────────────────────────────────────────────────────  MARK ──

    async def mark_lesson(self) -> MarkResult:
        """
        Ищет в «Занятии журнала» кнопку «Отметиться» и нажимает её.
        """
        html = await self.fetch_lesson_journal_html()
        soup = BeautifulSoup(html, "html.parser")

        mark_keywords = (
            "отметиться", "отметится", "отметка",
            "я на паре", "я тут", "отметить присутствие",
        )
        candidates: list[BeautifulSoup] = []

        # 1) <a> с подходящим текстом
        for a in soup.find_all("a"):
            txt = a.get_text(" ", strip=True).lower()
            if any(kw in txt for kw in mark_keywords):
                candidates.append(a)

        # 2) <button>/<input type=button> с подходящим текстом/значением
        for tag in soup.find_all(["button", "input"]):
            txt = (tag.get("value", "") + " " + tag.get_text(" ", strip=True)).lower()
            if any(kw in txt for kw in mark_keywords):
                candidates.append(tag)

        if not candidates:
            return MarkResult(
                success=False,
                message="Кнопка «Отметиться» не найдена — вероятно, сейчас нет пары.",
                raw_html=html,
            )

        el = candidates[0]

        # Сценарий A: обычная ссылка <a href="..."> — делаем GET
        href = el.get("href")
        if href and not href.startswith("javascript:"):
            url = urljoin(self.cabinet_url, href)
            log.info("Отметка через GET: %s", url)
            resp = await self._client.get(url)
            return MarkResult(
                success=resp.status_code == 200,
                message=self._parse_mark_response(resp.text),
                raw_html=resp.text,
            )

        # Сценарий B: Бонч-style кнопка с modul/parametr/key
        modul = el.get("modul") or el.get("myfunc")
        parametr = el.get("parametr", "0")
        key = el.get("key", LESSON_JOURNAL_KEY)

        if modul and not modul.endswith("0.php"):
            url = f"/cabinet/{modul.lstrip('/')}"
            payload = {"subconto": "menu", "key": key, "parametr": parametr}
            log.info("Отметка через POST: %s payload=%s", url, payload)
            resp = await self._client.post(url, data=payload)
            return MarkResult(
                success=resp.status_code == 200,
                message=self._parse_mark_response(resp.text),
                raw_html=resp.text,
            )

        # Сценарий C: input type=submit внутри формы — отправляем форму целиком
        form = el.find_parent("form")
        if form:
            action = form.get("action") or ""
            url = urljoin(self.cabinet_url, action) if action else self.cabinet_url
            form_data = {
                inp.get("name", ""): inp.get("value", "")
                for inp in form.find_all("input")
                if inp.get("name")
            }
            log.info("Отметка через form POST: %s payload=%s", url, form_data)
            resp = await self._client.post(url, data=form_data)
            return MarkResult(
                success=resp.status_code == 200,
                message=self._parse_mark_response(resp.text),
                raw_html=resp.text,
            )

        return MarkResult(
            success=False,
            message=(
                "Кнопка найдена, но не удалось определить, какой запрос "
                "отправить. Сохрани HTML раздела и пришли разработчику."
            ),
            raw_html=html,
        )

    def _parse_mark_response(self, html: str) -> str:
        """Извлекаем человекочитаемый ответ сервера после отметки."""
        if not html:
            return "Пустой ответ сервера"
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        if not text:
            return "Сервер вернул пустой HTML"
        return text[:300].strip() or "Сервер вернул пустой ответ"

    # ────────────────────────────────────────────────────── SCHEDULE ──

    async def fetch_today_schedule_html(self) -> str:
        """Возвращает HTML сегодняшнего расписания (для команды /schedule)."""
        await self._post_history(SCHEDULE_KEY)
        resp = await self._client.post(
            f"/cabinet/{SCHEDULE_MODUL}",
            data={"subconto": "menu", "key": SCHEDULE_KEY},
        )
        return resp.text


# ─────────────────────────────────────────────────────────── SYNC WRAPPER ──

def run_async_login(client: BonchClient, users: str, parole: str) -> str:
    """Синхронная обёртка для отладки вне бота."""
    return asyncio.run(client.login(users, parole))
