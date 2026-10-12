"""
Клиент личного кабинета lk.sut.ru (Бонч-Бруевич).

Эндпоинты полностью восстановлены из JS-функций в HTML расписания:

  - Логин:       POST /cabinet/lib/autentificationok.php
                 Body: users=<login>&parole=<password>
                 Ответ: число (>0 = ID пользователя, 0 = ошибка,
                         либо "key=val|key=val|..." если аккаунт заблокирован)

  - Расписание:  POST /cabinet/project/cabinet/forms/raspisanie.php
                 Body: subconto=menu&key=6118
                 Возвращает HTML с таблицей занятий. В каждой строке с
                 предстоящей парой — заглушка:
                   <span id="knop<XXX>">
                     <a onclick="update_zan(<XXX>);">Кнопка появится в HH:MM. Обновить.</a>
                   </span>
                 где XXX — числовой ID занятия (например, 1118024).

  - Шаг 1 «Проверка»:  POST open=3&rasp=<XXX>     (функция update_zan)
                 Возвращает JSON {"data": "<HTML>"}:
                   - Если пара ещё не началась: текст «Кнопка появится в HH:MM. Обновить.»
                   - Если можно отметиться:   <a onclick="open_zan(<XXX>,<WEEK>);">Начать занятие</a>
                   - Если уже отметили:       <a onclick="close_zan('<JID>', '<XXX>');">Закончить занятие</a>
                 WEEK — номер недели из пагинации расписания (showweek(N)).

  - Шаг 2 «Отметка»:   POST open=1&rasp=<XXX>&week=<WEEK>   (функция open_zan)
                 Возвращает JSON {"data": "<HTML>", "id": "<журнал_id>"}:
                   - При успехе: текст «Закончить занятие» или close_zan(...)
                 После этого пара считается начатой (отметка прошла).

  - Завершение: POST open=2&rasp=<журнал_id>   (функция close_zan)
                 Не обязательно — используется только если нужно явно
                 завершить занятие (например, если забыл завершить прошлую пару).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
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

# Ключи меню ЛК (из HTML-меню кабинета)
SCHEDULE_KEY = "6118"           # «Расписание»
SCHEDULE_MODUL = "project/cabinet/forms/raspisanie.php"

# «Занятие журнала» — это раздел ПРОСМОТРА журнала, не отметки!
LESSON_JOURNAL_KEY = "6112"
LESSON_JOURNAL_MODUL = "project/cabinet/modul/raspisanie/zanatie_jurnal.php"

# URL для всех POST-запросов отметки (update_zan, open_zan, close_zan)
MARK_URL = "/cabinet/project/cabinet/forms/raspisanie.php"

# Regex для поиска ID занятий в HTML расписания
# Пример: <a onclick="update_zan(1118024);">...</a>
_ZAN_ID_RE = re.compile(r"update_zan\((\d+)\)")

# Regex для извлечения (lesson_id, week) из ответа update_zan
# Пример: <a onclick="open_zan(1118024,7);">Начать занятие</a>
_OPEN_ZAN_RE = re.compile(r"open_zan\((\d+)\s*,\s*(\d+)\)")

# Regex для извлечения journal_id из close_zan (если вдруг понадобится)
# Пример: <a onclick="close_zan('56649', '1118024');">Закончить занятие</a>
_CLOSE_ZAN_RE = re.compile(r"close_zan\(\s*['\"]?(\d+)['\"]?\s*,\s*['\"]?(\d+)['\"]?\s*\)")

# Признаки в HTML-ответе после отметки (open_zan вернул «отметка прошла»)
_MARK_DONE_PATTERNS = (
    "закончить занятие",   # кнопка «Закончить занятие»
    "close_zan",           # onclick="close_zan(...)"
    "занятие начато",
    "отмечено",
)
# Признаки «пара ещё не началась» — кнопка «Начать занятие» ещё не появилась
_MARK_NOT_YET_PATTERNS = (
    "кнопка появится",     # «Кнопка появится в HH:MM. Обновить.»
    "появится в",
)


@dataclass
class MarkResult:
    """Результат попытки отметки."""
    success: bool
    message: str
    raw_html: str | None = None
    lesson_ids: list[int] | None = None
    raw_json: str | None = None
    journal_id: str | None = None  # ID журнала, если отметка прошла


@dataclass
class LessonInfo:
    """Информация об одном занятии из расписания."""
    lesson_id: int          # ID для update_zan / open_zan
    week: int = 0           # номер недели (из пагинации showweek), нужен для open_zan
    time: str = ""          # "09.00-10.30"
    subject: str = ""      # "Электротехника"
    lesson_type: str = ""   # "Лекция" / "Практические занятия"
    teacher: str = ""      # "Цветков А.Ю."
    room: str = ""         # "702; Б22/1"


class BonchLoginError(Exception):
    """Логин не удался."""


class BonchClient:
    """Асинхронный HTTP-клиент ЛК. Один экземпляр = одна сессия."""

    def __init__(self, base_url: str = "https://lk.sut.ru"):
        self.base_url = base_url.rstrip("/")
        self.cabinet_url = f"{self.base_url}/cabinet/"

        # Общие заголовки — максимальное сходство с браузером.
        # Без Origin / Sec-Fetch-* nginx Бонча отдаёт 403 на POST к autentificationok.php.
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,application/xhtml+xml;q=0.8,*/*;q=0.7"
                ),
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept-Encoding": "gzip, deflate, br, zstd",
                "Referer": self.cabinet_url,
                "Origin": self.base_url,
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
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def set_cookies(self, cookies: dict[str, str]) -> None:
        """
        Вручную установить cookies (например, скопированные из браузера).
        Полезно для отладки без логина.

        Основная сессионная кука Бонча — `miden`.
        Также есть `uid` (id пользователя), `_ym_d`/`_ym_uid` (Яндекс.Метрика — не нужны).
        """
        for name, value in cookies.items():
            self._client.cookies.set(name, value, domain="lk.sut.ru")
        log.info("Установлены cookies: %s", list(cookies.keys()))

    # ─────────────────────────────────────────────────────── LOGIN ──

    async def login(self, users: str, parole: str) -> str:
        """
        Авторизация в ЛК.

        Возвращает PHPSESSID (cookie) — он хранится внутри клиента.
        Бросает BonchLoginError при неудаче.
        """
        # 1. Заходим на главную, чтобы получить PHPSESSID и куки.
        #    ВАЖНО: загружаем именно login=yes страницу, как делает браузер
        #    при форме входа — иначе сервер может не выдать нужные куки.
        await self._client.get("/cabinet/", params={"login": "no"})
        await asyncio.sleep(0.3)  # имитируем человека

        # 2. POST на autentificationok.php
        #    Headers подменяем на «ajax-ные» — как делает jQuery:
        #    Content-Type с charset=UTF-8 + Sec-Fetch-* для same-origin AJAX
        resp = await self._client.post(
            "/cabinet/lib/autentificationok.php",
            data={"users": users, "parole": parole},
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Accept": "*/*",
                "Origin": self.base_url,
                "Referer": self.cabinet_url,
                "X-Requested-With": "XMLHttpRequest",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        # Диагностика: если вернулся HTML (а не число) — это ошибка nginx/WAF
        if resp.status_code != 200 or "<html" in resp.text.lower()[:200]:
            raise BonchLoginError(
                f"Сервер вернул нечисловой ответ. Status={resp.status_code}, "
                f"body[:300]={resp.text[:300]!r}, "
                f"cookies={dict(self._client.cookies)}"
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
        """
        Живая ли ещё сессия?

        У Бонча сессионная кука называется `miden` (не PHPSESSID, как в стандартном PHP).
        Если её нет или GET /cabinet/?login=yes редиректит на ?login=no — сессия протухла.
        """
        # Быстрая проверка: есть ли вообще кука miden?
        has_miden = bool(self._client.cookies.get("miden"))
        if not has_miden:
            log.debug("is_logged_in: кука miden отсутствует")
            return False
        # Полная проверка: GET кабинета без follow_redirects.
        # Если сессия жива — 200. Если истекла — 302 на /cabinet/?login=no.
        try:
            resp = await self._client.get(
                "/cabinet/", params={"login": "yes"}, follow_redirects=False
            )
        except httpx.HTTPError as e:
            log.debug("is_logged_in: HTTP error %s", e)
            return False
        if resp.status_code == 200:
            return True
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location", "")
            # Если редирект на login=no — сессия протухла.
            # Любой другой редирект — будем считать, что сессия жива.
            return "login=no" not in location
        return False

    # ───────────────────────────────────────────────────── SCHEDULE ──

    async def _post_history(self, key: str) -> None:
        """Записывает в history.php (нужно серверу для корректного состояния)."""
        try:
            await self._client.post(
                "/cabinet/project/cabinet/history.php",
                data={"subconto": "menu", "key": key},
            )
        except httpx.HTTPError:
            log.debug("history.php запрос упал для key=%s, продолжаем", key)

    async def fetch_today_schedule_html(self) -> str:
        """Возвращает HTML расписания на текущую неделю."""
        await self._post_history(SCHEDULE_KEY)
        resp = await self._client.post(
            f"/cabinet/{SCHEDULE_MODUL}",
            data={"subconto": "menu", "key": SCHEDULE_KEY},
        )
        return resp.text

    def _detect_week(self, html: str) -> int:
        """
        Пытается определить номер текущей недели из HTML расписания.
        Активная неделя в пагинации помечена так:
          <a class="page-link  bg-info text-white" onclick="showweek(7)">7</a>
        (двойной пробел между классами — это нормально для ЛК Бонч)

        Возвращает 0, если не удалось определить.
        """
        # Прямой regex — надёжнее, чем BeautifulSoup по классам
        # Ищем <a class="page-link...bg-info text-white..." onclick="showweek(N)">
        m = re.search(
            r'class="page-link[^"]*bg-info[^"]*"[^>]*onclick="showweek\((\d+)\)"',
            html,
        )
        if m:
            return int(m.group(1))
        # Запасной вариант: находим все showweek и берём любой, у которого рядом есть bg-info
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a"):
            classes = a.get("class", [])
            if isinstance(classes, str):
                classes = classes.split()
            if "bg-info" in classes:
                onclick = a.get("onclick", "")
                mm = re.search(r"showweek\((\d+)\)", onclick)
                if mm:
                    return int(mm.group(1))
                txt = a.get_text(strip=True)
                if txt.isdigit():
                    return int(txt)
        return 0

    def parse_lessons(self, html: str) -> list[LessonInfo]:
        """
        Разбирает HTML расписания и достаёт список занятий с их ID.

        Возвращаются только те строки, где есть update_zan(XXX) —
        то есть пары, по которым ещё можно отметиться.
        """
        week = self._detect_week(html)
        log.info("Определена неделя: %s", week or "?")

        soup = BeautifulSoup(html, "html.parser")
        lessons: list[LessonInfo] = []

        for row in soup.select("tr"):
            # Ищем <span id="knopXXX"><a onclick="update_zan(XXX);">...</a></span>
            span = row.find("span", id=re.compile(r"^knop\d+$"))
            if not span:
                continue
            onclick_match = _ZAN_ID_RE.search(str(span))
            if not onclick_match:
                continue
            lesson_id = int(onclick_match.group(1))

            # Текст кнопки-заглушки — даёт подсказку о времени пары
            btn_text = span.get_text(" ", strip=True).lower()
            log.debug("Занятие ID=%s, кнопка: %s", lesson_id, btn_text)

            # Достаём остальные поля строки
            tds = row.find_all("td")
            time_str = tds[0].get_text(strip=True) if len(tds) > 0 else ""
            # 3-я колонка иногда пустая, 4-я — аудитория, 5-я — преподаватель
            room = tds[3].get_text(" ", strip=True) if len(tds) > 3 else ""
            teacher = tds[4].get_text(" ", strip=True) if len(tds) > 4 else ""

            # subject обычно содержит название + тип, разделённые <br>
            # например: <b>Разработка защищенных сетевых приложений</b><br><small>Лекция</small>
            lesson_type = ""
            subj_html = str(tds[1]) if len(tds) > 1 else ""
            subj_soup = BeautifulSoup(subj_html, "html.parser")
            name_tag = subj_soup.find("b")
            if name_tag:
                subj = name_tag.get_text(" ", strip=True)
            else:
                subj = subj_soup.get_text(" ", strip=True)
            type_tag = subj_soup.find("small")
            if type_tag:
                lesson_type = type_tag.get_text(" ", strip=True)

            lessons.append(LessonInfo(
                lesson_id=lesson_id,
                week=week,
                time=time_str,
                subject=subj,
                lesson_type=lesson_type,
                teacher=teacher,
                room=room,
            ))

        return lessons

    # ───────────────────────────────────────────────────────  MARK ──

    async def _call_update_zan(self, lesson_id: int) -> dict:
        """
        Шаг 1: POST open=3&rasp=<lesson_id> — вызывает update_zan().
        Возвращает распарсенный JSON {"data": "<HTML>"}.
        """
        resp = await self._client.post(
            MARK_URL,
            data={"open": "3", "rasp": str(lesson_id)},
            headers={"Referer": self.cabinet_url},
        )
        try:
            return resp.json()
        except json.JSONDecodeError as e:
            log.error(
                "update_zan(%s): невалидный JSON. Status=%s, body[:200]=%r",
                lesson_id, resp.status_code, resp.text[:200],
            )
            return {"data": resp.text, "_raw": resp.text, "_error": str(e)}

    async def _call_open_zan(self, lesson_id: int, week: int) -> dict:
        """
        Шаг 2: POST open=1&rasp=<lesson_id>&week=<week> — вызывает open_zan().
        Это и есть реальная отметка.
        Возвращает JSON {"data": "<HTML>", "id": "<журнал_id>"}.
        """
        resp = await self._client.post(
            MARK_URL,
            data={
                "open": "1",
                "rasp": str(lesson_id),
                "week": str(week),
            },
            headers={"Referer": self.cabinet_url},
        )
        try:
            return resp.json()
        except json.JSONDecodeError as e:
            log.error(
                "open_zan(%s, week=%s): невалидный JSON. Status=%s, body[:200]=%r",
                lesson_id, week, resp.status_code, resp.text[:200],
            )
            return {"data": resp.text, "_raw": resp.text, "_error": str(e)}

    async def mark_lesson(self, lesson_id: int | None = None) -> MarkResult:
        """
        Отмечается на паре (двухшаговый флоу).

        Шаг 1: для каждого занятия вызываем update_zan (open=3) — проверяем,
               появилась ли кнопка «Начать занятие».
        Шаг 2: если в ответе есть open_zan(ID, WEEK) — вызываем open_zan
               (open=1&rasp=ID&week=WEEK) — это и есть отметка.
        Успех: в ответе open_zan есть «Закончить занятие» / close_zan.

        Если lesson_id не задан — пробует все занятия из расписания.
        """
        # 1. Загружаем расписание и парсим занятия
        schedule_html = await self.fetch_today_schedule_html()
        lessons = self.parse_lessons(schedule_html)

        if not lessons:
            return MarkResult(
                success=False,
                message="В расписании на сегодня нет занятий с кнопкой отметки.",
                raw_html=schedule_html,
                lesson_ids=[],
            )

        log.info("Найдено занятий с кнопкой: %d", len(lessons))

        # Если указан конкретный ID — отметим только его
        target_lessons = [l for l in lessons if lesson_id is None or l.lesson_id == lesson_id]
        if not target_lessons:
            return MarkResult(
                success=False,
                message=f"Занятие с ID={lesson_id} не найдено в расписании.",
                raw_html=schedule_html,
                lesson_ids=[l.lesson_id for l in lessons],
            )

        # 2. Шаг 1 для каждого занятия: проверяем, можно ли отметиться
        for lesson in target_lessons:
            log.info(
                "update_zan(%s) для '%s' (%s, %s)",
                lesson.lesson_id, lesson.subject, lesson.time, lesson.teacher,
            )
            resp_json = await self._call_update_zan(lesson.lesson_id)
            inner_html = resp_json.get("data", "") or ""

            # Анализируем ответ шага 1
            check = self._analyze_update_zan_response(lesson, inner_html)

            # Если пара ещё не началась — пробуем следующее занятие
            if check.status == "not_yet":
                log.info("Пара ещё не началась: %s", check.message)
                continue

            # Если уже отметились ранее (был close_zan) — успех
            if check.status == "already_done":
                return MarkResult(
                    success=True,
                    message=check.message,
                    raw_html=inner_html,
                    raw_json=json.dumps(resp_json, ensure_ascii=False),
                    journal_id=check.journal_id,
                )

            # Если есть кнопка «Начать занятие» — делаем шаг 2
            if check.status == "can_mark":
                # week из ответа update_zan имеет приоритет над тем, что мы определили
                week = check.week or lesson.week
                if week == 0:
                    log.warning(
                        "Не удалось определить week для open_zan(%s). "
                        "Пробую week=0.", lesson.lesson_id,
                    )

                log.info(
                    "open_zan(%s, week=%s) — реальная отметка",
                    check.open_lesson_id or lesson.lesson_id, week,
                )
                resp2 = await self._call_open_zan(
                    check.open_lesson_id or lesson.lesson_id, week,
                )
                inner_html2 = resp2.get("data", "") or ""
                journal_id = str(resp2.get("id", "")) or None

                # Анализируем ответ шага 2
                result = self._analyze_open_zan_response(
                    lesson, inner_html2, journal_id,
                    raw_json=json.dumps(resp2, ensure_ascii=False),
                )
                if result.success:
                    return result
                log.info("open_zan не удался: %s", result.message)
                continue

            # Непонятный ответ update_zan — пробуем следующее занятие
            log.warning("Непонятный ответ update_zan: %s", check.message)

        # 3. Ни одно не отметилось — собираем сводку
        return MarkResult(
            success=False,
            message=(
                "Не удалось отметиться ни на одной паре. "
                "Возможно, сейчас нет пары или все уже отмечены. "
                "Попробуй /lessons, чтобы посмотреть ID и время."
            ),
            raw_html=schedule_html,
            lesson_ids=[l.lesson_id for l in lessons],
        )

    # ─────────────────────────────────────────── RESPONSE ANALYZERS ──

    @dataclass
    class _UpdateZanCheck:
        """Внутренний результат анализа ответа update_zan (шаг 1)."""
        status: str  # "not_yet" | "can_mark" | "already_done" | "unknown"
        message: str = ""
        open_lesson_id: int | None = None  # ID из open_zan(ID, WEEK)
        week: int | None = None             # week из open_zan(ID, WEEK)
        journal_id: str | None = None       # journal_id из close_zan

    def _analyze_update_zan_response(
        self, lesson: LessonInfo, inner_html: str,
    ) -> "_UpdateZanCheck":
        """
        Анализирует HTML из JSON.data после open=3 (update_zan).
        """
        inner_lower = inner_html.lower()

        # Сценарий «уже отметили» (close_zan)
        if any(p in inner_lower for p in _MARK_DONE_PATTERNS):
            jid_match = _CLOSE_ZAN_RE.search(inner_html)
            jid = jid_match.group(1) if jid_match else None
            return self._UpdateZanCheck(
                status="already_done",
                message=(
                    f"Уже отмечен на паре «{lesson.subject}» ({lesson.time}). "
                    f"Сервер: «{self._strip_html(inner_html)[:200]}»"
                ),
                journal_id=jid,
            )

        # Сценарий «пара ещё не началась»
        if any(p in inner_lower for p in _MARK_NOT_YET_PATTERNS):
            btn_text = self._strip_html(inner_html)[:200]
            return self._UpdateZanCheck(
                status="not_yet",
                message=(
                    f"Пара «{lesson.subject}» ({lesson.time}) ещё не началась. "
                    f"Сервер: «{btn_text}»"
                ),
            )

        # Сценарий «можно отметиться» — есть open_zan(ID, WEEK)
        m = _OPEN_ZAN_RE.search(inner_html)
        if m:
            open_lesson_id = int(m.group(1))
            week = int(m.group(2))
            log.info(
                "Найдена кнопка «Начать занятие»: open_zan(%s, %s)",
                open_lesson_id, week,
            )
            return self._UpdateZanCheck(
                status="can_mark",
                message=f"Кнопка «Начать занятие» доступна.",
                open_lesson_id=open_lesson_id,
                week=week,
            )

        # Непонятный ответ
        return self._UpdateZanCheck(
            status="unknown",
            message=(
                f"Непонятный ответ сервера для пары «{lesson.subject}». "
                f"HTML: {inner_html[:300]!r}"
            ),
        )

    def _analyze_open_zan_response(
        self,
        lesson: LessonInfo,
        inner_html: str,
        journal_id: str | None,
        raw_json: str,
    ) -> MarkResult:
        """
        Анализирует HTML из JSON.data после open=1 (open_zan).
        Это ответ на реальную отметку.
        """
        inner_lower = inner_html.lower()

        # Успех — есть «Закончить занятие» / close_zan
        if any(p in inner_lower for p in _MARK_DONE_PATTERNS):
            # Достаём journal_id из close_zan, если есть
            if not journal_id:
                jid_match = _CLOSE_ZAN_RE.search(inner_html)
                if jid_match:
                    journal_id = jid_match.group(1)
            return MarkResult(
                success=True,
                message=(
                    f"✅ Отметился на паре «{lesson.subject}» "
                    f"({lesson.time}, {lesson.teacher}). "
                    f"Сервер: «{self._strip_html(inner_html)[:200]}»"
                ),
                raw_html=inner_html,
                raw_json=raw_json,
                journal_id=journal_id,
            )

        # В ответе снова «Кнопка появится в HH:MM» — странно, но возможно
        if any(p in inner_lower for p in _MARK_NOT_YET_PATTERNS):
            return MarkResult(
                success=False,
                message=(
                    f"Странно: после open_zan сервер снова пишет «пара не началась». "
                    f"Возможно, отметка не прошла. Сервер: "
                    f"«{self._strip_html(inner_html)[:200]}»"
                ),
                raw_html=inner_html,
                raw_json=raw_json,
            )

        # Пустой ответ — скорее всего отметка прошла, но сервер ничего не вернул
        if not inner_html.strip():
            return MarkResult(
                success=False,
                message=(
                    f"После отметки на «{lesson.subject}» сервер вернул пустой ответ. "
                    f"Проверь в ЛК, появилась ли отметка. journal_id={journal_id}"
                ),
                raw_html=inner_html,
                raw_json=raw_json,
                journal_id=journal_id,
            )

        # Непонятный ответ
        return MarkResult(
            success=False,
            message=(
                f"После отметки на «{lesson.subject}» сервер вернул непонятный ответ. "
                f"HTML: {inner_html[:300]!r}"
            ),
            raw_html=inner_html,
            raw_json=raw_json,
        )

    @staticmethod
    def _strip_html(html: str) -> str:
        return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)

    # ──────────────────────────────────────────── LESSON JOURNAL ──

    async def fetch_lesson_journal_html(self) -> str:
        """
        Загружает раздел «Занятие журнала» (key=6112) — это ПРОСМОТР
        журнала посещаемости, не отметка.
        """
        await self._post_history(LESSON_JOURNAL_KEY)
        resp = await self._client.post(
            f"/cabinet/{LESSON_JOURNAL_MODUL}",
            data={"subconto": "menu", "key": LESSON_JOURNAL_KEY},
        )
        return resp.text

    async def close_lesson(self, journal_id: int | str) -> dict:
        """
        Завершить занятие (POST open=2&rasp=<журнал_id>).
        Соответствует close_zan() в JS.
        Использовать только если нужно явно завершить (обычно не требуется).
        """
        resp = await self._client.post(
            MARK_URL,
            data={"open": "2", "rasp": str(journal_id)},
            headers={"Referer": self.cabinet_url},
        )
        try:
            return resp.json()
        except json.JSONDecodeError:
            return {"_raw": resp.text}


# ─────────────────────────────────────────────────────────── SYNC WRAPPER ──

def run_async_login(client: BonchClient, users: str, parole: str) -> str:
    """Синхронная обёртка для отладки вне бота."""
    return asyncio.run(client.login(users, parole))
