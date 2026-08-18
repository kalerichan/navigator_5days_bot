import logging
import os
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import BOT_TOKEN, ADMIN_ID, CHANNEL_ID, DIAGNOSTIC_LINK

# ============================================================
# НАСТРОЙКИ
# ============================================================

TIMEZONE_NAME = os.environ.get("BOT_TIMEZONE", "Europe/Moscow")
TZ = ZoneInfo(TIMEZONE_NAME)

DB_PATH = "database.db"

CHECKLIST_FILENAME = "checklist_net.pdf"
WORKBOOK_FILENAME = "workbook.pdf"

# День 6 — бонус только для версии 2.0.
# Файлы голосовых должны лежать в files/audio/
AUDIO_FILES = {
    1: {
        1: "files/audio/track1_day1_evening.ogg",
        2: "files/audio/track1_day2_evening.ogg",
        3: "files/audio/track1_day3_evening.ogg",
        4: "files/audio/track1_day4_evening.ogg",
        5: "files/audio/track1_day5_evening.ogg",
        6: "files/audio/track1_day6_bonus.ogg",
    },
    2: {
        1: "files/audio/track2_day1_evening.ogg",
        2: "files/audio/track2_day2_evening.ogg",
        3: "files/audio/track2_day3_evening.ogg",
        4: "files/audio/track2_day4_evening.ogg",
        5: "files/audio/track2_day5_evening.ogg",
        6: "files/audio/track2_day6_bonus.ogg",
    },
    3: {
        1: "files/audio/track3_day1_evening.ogg",
        2: "files/audio/track3_day2_evening.ogg",
        3: "files/audio/track3_day3_evening.ogg",
        4: "files/audio/track3_day4_evening.ogg",
        5: "files/audio/track3_day5_evening.ogg",
        6: "files/audio/track3_day6_bonus.ogg",
    },
}

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("clarity_bot")


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def now_local() -> datetime:
    return datetime.now(TZ)


def find_file(filename: str):
    candidates = [
        filename,
        os.path.join("files", filename),
        os.path.join("app", filename),
        os.path.join("my_bot", filename),
        os.path.join("..", filename),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def channel_url() -> str:
    value = CHANNEL_ID.strip()
    if value.startswith("@"):
        return f"https://t.me/{value[1:]}"
    if value.startswith("https://t.me/"):
        return value
    # Для числового channel_id прямой URL неизвестен.
    # В этом случае лучше задать CHANNEL_URL в .env.
    return os.environ.get("CHANNEL_URL", "https://t.me/kalerichan")


def parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=TZ)
        return value.astimezone(TZ)
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ)
    except ValueError:
        return None


def dt_to_db(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=TZ)
    return value.astimezone(TZ).isoformat()


# ============================================================
# БАЗА ДАННЫХ
# ============================================================

DB_COLUMNS = {
    "user_id": "INTEGER PRIMARY KEY",
    "username": "TEXT",
    "state": "TEXT DEFAULT 'NEW'",
    "subscribed": "INTEGER DEFAULT 0",
    "checklist_sent": "INTEGER DEFAULT 0",
    "challenge_started": "INTEGER DEFAULT 0",
    "challenge_version": "TEXT",
    "version_locked": "INTEGER DEFAULT 0",
    "track": "INTEGER DEFAULT 0",
    "score": "INTEGER DEFAULT 0",
    "test_question": "INTEGER DEFAULT 0",
    "current_day": "INTEGER DEFAULT 0",
    "start_time": "TEXT",
    "finished": "INTEGER DEFAULT 0",
    "reflection_sent": "INTEGER DEFAULT 0",
    "workbook_sent": "INTEGER DEFAULT 0",
    "bonus_sent": "INTEGER DEFAULT 0",
    "last_morning_at": "TEXT",
    "last_evening_at": "TEXT",
    "next_morning_at": "TEXT",
    "next_evening_at": "TEXT",
}


def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            state TEXT DEFAULT 'NEW',
            subscribed INTEGER DEFAULT 0,
            checklist_sent INTEGER DEFAULT 0,
            challenge_started INTEGER DEFAULT 0,
            challenge_version TEXT,
            version_locked INTEGER DEFAULT 0,
            track INTEGER DEFAULT 0,
            score INTEGER DEFAULT 0,
            test_question INTEGER DEFAULT 0,
            current_day INTEGER DEFAULT 0,
            start_time TEXT,
            finished INTEGER DEFAULT 0,
            reflection_sent INTEGER DEFAULT 0,
            workbook_sent INTEGER DEFAULT 0,
            bonus_sent INTEGER DEFAULT 0,
            last_morning_at TEXT,
            last_evening_at TEXT,
            next_morning_at TEXT,
            next_evening_at TEXT
        )
    """)

    # Миграция старой базы: добавляем недостающие поля.
    cur.execute("PRAGMA table_info(users)")
    existing = {row[1] for row in cur.fetchall()}

    for name, sql_type in DB_COLUMNS.items():
        if name not in existing and name != "user_id":
            cur.execute(f"ALTER TABLE users ADD COLUMN {name} {sql_type}")

    conn.commit()
    conn.close()
    logger.info("База данных инициализирована.")


def get_user(user_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def create_or_update_user(user_id: int, username: str | None):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO users (user_id, username)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET username = excluded.username
    """, (user_id, username))
    conn.commit()
    conn.close()


def update_user(user_id: int, **kwargs):
    if not kwargs:
        return

    allowed = set(DB_COLUMNS.keys()) - {"user_id"}
    invalid = set(kwargs.keys()) - allowed
    if invalid:
        raise ValueError(f"Недопустимые поля БД: {invalid}")

    conn = db_connect()
    cur = conn.cursor()

    assignments = ", ".join(f"{key} = ?" for key in kwargs)
    values = list(kwargs.values()) + [user_id]

    cur.execute(
        f"UPDATE users SET {assignments} WHERE user_id = ?",
        values,
    )
    conn.commit()
    conn.close()


# ============================================================
# ПОДПИСКА
# ============================================================

async def is_subscribed(bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(
            chat_id=CHANNEL_ID,
            user_id=user_id,
        )
        return member.status in ("member", "administrator", "creator")
    except Exception:
        logger.exception("Ошибка проверки подписки user_id=%s", user_id)
        return False


# ============================================================
# ТЕКСТЫ
# ============================================================

questions = [
    {
        "text": "Когда в последний раз ты делала что-то только для себя, без оглядки на других?",
        "options": [
            ("На этой неделе", 1),
            ("В прошлом месяце", 2),
            ("Даже не помню, когда такое было", 3),
        ],
    },
    {
        "text": "Окружающие чаще всего говорят тебе:",
        "options": [
            ("«Ты всегда знаешь, чего хочешь»", 1),
            ("«На тебя можно положиться»", 2),
            ("«Как ты всё успеваешь?»", 3),
        ],
    },
    {
        "text": "Если тебе нужна помощь, ты:",
        "options": [
            ("Просишь и не чувствуешь вины", 1),
            ("Просишь, но долго переживаешь", 2),
            ("Никогда не просишь, справляешься сама", 3),
        ],
    },
    {
        "text": "Твоё тело чаще всего:",
        "options": [
            ("Полно энергии, высыпаешься", 1),
            ("Бывает напряжение в шее/плечах, но терпимо", 2),
            ("Постоянная усталость, головные боли, ком в горле", 3),
        ],
    },
    {
        "text": "Когда тебя хвалят за достижения, ты внутри:",
        "options": [
            ("Чувствуешь гордость", 1),
            ("Думаешь: «Ой, да это просто повезло»", 2),
            ("Ощущаешь пустоту или страх, что разоблачат", 3),
        ],
    },
    {
        "text": "Представь, что завтра ты исчезнешь из всех своих ролей (работа, семья). Что ты почувствуешь в первую секунду?",
        "options": [
            ("Любопытство", 1),
            ("Тревогу", 2),
            ("Облегчение", 3),
        ],
    },
]

MORNING_TEXTS = {
    (1, 1): """☀️ День 1. Мои точки опоры

Сегодня мы не будем искать проблемы. Мы будем искать то, что тебя держит.

Задание:
• Возьми лист бумаги или заметки в телефоне.
• Напиши 5 вещей, занятий, моментов, которые возвращают тебе ощущение «я».
• Напротив каждого пункта напиши, когда в последний раз ты это делала.
• Выбери один пункт и встрой его в своё расписание на завтра.

Вечером я пришлю тебе голосовое сообщение. А пока дыши глубже. Ты в порядке 🌸""",

    (1, 2): """☀️ День 2. Границы как забота

Умение говорить «нет» — это не про жесткость. Это про заботу о себе.

Задание:
• Вспомни одну недавнюю ситуацию, где ты сказала «да», но внутри чувствовала «нет».
• Напиши, что именно ты чувствовала в тот момент.
• Теперь перепиши эту ситуацию. Напиши идеальный сценарий твоего «нет».
• Прочитай написанное вслух.

Это упражнение — репетиция. В следующий раз мозгу будет легче 💪""",

    (1, 3): """☀️ День 3. Тело как союзник

Тело — не инструмент для достижений. Оно — твой дом.

Задание:
• Сядь удобно, закрой глаза. Сделай три глубоких вдоха.
• Пройди вниманием от макушки до пальцев ног.
• Открой глаза и запиши: Точка напряжения и Точка ресурса.
• Задай вопрос точке напряжения: «Что ты хочешь мне сказать?».

Твоё тело всегда на твоей стороне. Учись его слышать 🌷""",

    (1, 4): """☀️ День 4. Спасатель vs Поддержка

Помогать можно по-разному: из любви или из страха быть ненужной.

Задание:
• Вспомни одну ситуацию за последние дни, где ты кому-то помогла.
• Ответь честно: Кому принадлежала проблема? Тебя просили о помощи или ты предложила сама?
• Если помощь больше напоминала спасение — просто заметь это.

Ты это увидела, а значит — уже начала выходить из роли 💗""",

    (1, 5): """☀️ День 5. Мой следующий шаг

Ты умеешь слышать себя. Теперь — усилить.

Задание:
• Посмотри на записи за эти дни. Что стало самым важным открытием?
• Напиши одно действие, которое расширит твою «зону авторства» в ближайшую неделю.
• Запиши это действие в календарь. Сделай его неотменяемым 🌸""",

    (2, 1): """☀️ День 1. Детектор утечки энергии

Ты устаёшь не от дел. Ты устаёшь от ролей, которые не твои.

Задание:
• Нарисуй таблицу из 4 столбцов: Роль, Энергия ЗАБИРАЕТ (1–10), Энергия ПРИНОСИТ (1–10), Разница.
• Заполни. Будь честна.
• Выбери одну роль, которая истощает тебя сильнее всего.

Ты не плохая. Ты просто слишком долго раздаёшь то, что не восполняется 🌷""",

    (2, 2): """☀️ День 2. Чей это голос?

Многие цели — не наши. Мы просто взяли их напрокат.

Задание:
• Выпиши 3 главные цели на этот год.
• Для каждой ответь: Кто первым сказал, что это важно?
• Если бы НИКТО никогда не узнал о моём результате, мне всё ещё было бы это важно?

Это может быть больно. Но это правда, которая освобождает 💖""",

    (2, 3): """☀️ День 3. Тело не врёт

Пока голова думает, что всё нормально, тело уже кричит.

Задание:
• Сядь тихо. Закрой глаза. Спроси: «Где сейчас живёт моя усталость?»
• Запиши все сигналы тела за последний месяц.
• Рядом с каждым сигналом напиши: «Что я делала в момент, когда это появилось?»

Твоё тело — твой главный свидетель. Верни ему право голоса 🌸""",

    (2, 4): """☀️ День 4. Маска спасателя

Спасательство — это часто не доброта, а способ контролировать и чувствовать себя нужной.

Задание:
• Вспомни одну конкретную ситуацию за последнюю неделю, где ты кого-то «спасала».
• Ответь: Что ты чувствовала ДО, В ПРОЦЕССЕ и ПОСЛЕ?
• Что будет, если в следующий раз ты не войдёшь в эту роль?

Страх, который возникнет — это и есть твой ключ к выходу 💗""",

    (2, 5): """☀️ День 5. Один шаг к себе

Осознание — это половина. Теперь — действие.

Задание:
• Вернись к Дню 1. Посмотри на роль, которая истощает тебя сильнее всего.
• Как ты можешь «сыграть» её на 30% меньше?
• Выбери одно маленькое действие и сделай его в ближайшие 48 часов 🌺""",

    (3, 1): """🕯️ День 1. Стоп-кран

Никаких планов, никаких «надо». Сегодня мы просто останавливаемся.

Задание:
• Найди 15 минут тишины. Без телефона, без людей, без задач.
• Сядь или ляг удобно. Положи руку на грудь.
• Задай себе вопрос: «Что я сейчас чувствую на самом деле?»

Сегодня не надо ничего решать. Просто разреши себе быть 🌸""",

    (3, 2): """🕯️ День 2. Моё тело говорит

Когда ты забыла о себе, тело помнит всё.

Задание:
• В течение дня делай паузы. Каждые 2–3 часа спрашивай: «Что сейчас чувствует моё тело?»
• Запиши 3–5 сигналов, которые повторяются.
• Вечером допиши: «Это может говорить о том, что я…»

Ничего не исправляй. Просто признай: твоё тело говорило с тобой всё это время 💖""",

    (3, 3): """🕯️ День 3. Чужие сценарии

Некоторые правила мы выучили так давно, что считаем их своими.

Задание:
• Вспомни фразы, которые ты часто слышала в детстве.
• Выпиши 5 таких фраз.
• Рядом с каждой напиши: «Так было тогда. Но сейчас я взрослая. И я могу…»

Это не предательство. Это взросление 🌷""",

    (3, 4): """🕯️ День 4. Я имею право

Сегодня мы будем возвращать себе то, что у тебя когда-то отобрали.

Задание:
• Напиши список из 10–15 пунктов, который начинается словами «Я имею право…».
• Прочитай список вслух. Медленно. Пункт за пунктом.
• Выбери один пункт, который труднее всего принять. Напиши его на листочке и повесь на видное место.

Это не бунт. Это возвращение к себе 💗""",

    (3, 5): """🕯️ День 5. Первый контакт с желанием

Ты долго обслуживала чужие сценарии. Сегодня — только ты.

Задание:
• Подумай: что бы ты сделала сегодня, если бы никто не ждал от тебя результата? Не «что полезно», а «что приятно».
• Выбери одно микро-действие. Очень маленькое. Без цели и смысла. Просто для удовольствия.
• Сделай это. И не объясняй никому 🌸""",
}

VOICE_CAPTIONS = {
    (1, 1): "✨ Ты отлично справилась с днём 1! Ты искала свои точки опоры — это важный шаг к себе. Горжусь тобой 💖",
    (1, 2): "💪 День 2 пройден! Ты училась говорить «нет» и защищать свои границы – это смело.",
    (1, 3): "🌿 Ты уже на полпути! Сегодня ты слушала своё тело — это очень ценно.",
    (1, 4): "💗 Четвёртый день позади. Ты разбиралась с ролью Спасателя — это трудная работа, но ты справляешься!",
    (1, 5): "🌟 Ты сделала это! Пять дней ты была в контакте с собой. Ты — невероятная!",

    (2, 1): "✨ День 1 завершён! Ты нашла свои источники утечки энергии — это первый шаг к восстановлению.",
    (2, 2): "💪 День 2 пройден! Ты осознала, какие цели не твои — это освобождает.",
    (2, 3): "🌿 Ты уже на полпути! Сегодня ты слушала своё тело — это очень ценно.",
    (2, 4): "💗 Четвёртый день позади. Ты увидела свою роль Спасателя — это открытие меняет всё.",
    (2, 5): "🌟 Ты сделала это! Пять дней ты искала себя. Ты — невероятная!",

    (3, 1): "✨ День 1 завершён! Ты остановилась и разрешила себе быть — это самое важное.",
    (3, 2): "💪 День 2 пройден! Ты начала слышать своё тело — это мощный шаг.",
    (3, 3): "🌿 Ты уже на полпути! Ты переписываешь чужие сценарии — это твой выбор.",
    (3, 4): "💗 Четвёртый день позади. Ты возвращаешь себе право быть — это революция.",
    (3, 5): "🌟 Ты сделала это! Пять дней ты шла к себе. Ты — моя героиня!",
}


# ============================================================
# ПЛАНИРОВАНИЕ
# ============================================================

def job_name(kind: str, user_id: int, day: int):
    return f"{kind}:{user_id}:{day}"


def remove_job(context: ContextTypes.DEFAULT_TYPE, name: str):
    jobs = context.job_queue.get_jobs_by_name(name)
    for job in jobs:
        job.schedule_removal()


def schedule_once(context, when: datetime, name: str, callback, data: dict):
    if when <= now_local():
        return

    remove_job(context, name)

    context.job_queue.run_once(
        callback,
        when=when,
        data=data,
        name=name,
    )


async def send_morning_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    await send_morning(
        context,
        data["user_id"],
        data["day"],
        scheduled=True,
    )


async def send_evening_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    await send_evening(
        context,
        data["user_id"],
        data["day"],
        scheduled=True,
    )


async def send_bonus_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    await send_bonus(
        context,
        data["user_id"],
    )


def day_times(day: int, start_date: datetime):
    """
    День 1 = дата start_date.
    День 2 = следующий календарный день и т.д.
    """
    date = (start_date + timedelta(days=day - 1)).date()

    morning = datetime(
        date.year, date.month, date.day,
        9, 0, 0,
        tzinfo=TZ,
    )

    evening = datetime(
        date.year, date.month, date.day,
        19, 0, 0,
        tzinfo=TZ,
    )

    return morning, evening


def schedule_day(context, user_id: int, day: int, start_date: datetime):
    if day > 5:
        return

    morning, evening = day_times(day, start_date)

    schedule_once(
        context,
        morning,
        job_name("morning", user_id, day),
        send_morning_job,
        {"user_id": user_id, "day": day},
    )

    schedule_once(
        context,
        evening,
        job_name("evening", user_id, day),
        send_evening_job,
        {"user_id": user_id, "day": day},
    )


def schedule_remaining_days(context, user_id: int, current_day: int, start_date: datetime):
    for day in range(current_day, 6):
        schedule_day(context, user_id, day, start_date)


def schedule_bonus(context, user_id: int, start_date: datetime):
    # Бонус — на следующий календарный день после дня 5, в 09:00.
    bonus_date = (start_date + timedelta(days=5)).date()
    bonus_time = datetime(
        bonus_date.year, bonus_date.month, bonus_date.day,
        9, 0, 0,
        tzinfo=TZ,
    )

    schedule_once(
        context,
        bonus_time,
        job_name("bonus", user_id, 6),
        send_bonus_job,
        {"user_id": user_id},
    )


def cancel_challenge_jobs(context, user_id: int):
    for kind in ("morning", "evening", "bonus"):
        for day in range(1, 7):
            remove_job(context, job_name(kind, user_id, day))


# ============================================================
# СТАРТ / ПОДПИСКА
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username

    create_or_update_user(user_id, username)
    user = get_user(user_id)

    if user["challenge_started"]:
        version = user["challenge_version"] or "неизвестная"
        await update.message.reply_text(
            f"🌿 Ты уже проходишь челлендж версии {version}.\n\n"
            "Выбрать другую версию во время прохождения нельзя — "
            "это сделано, чтобы твой путь оставался цельным 💛"
        )
        return

    if user["checklist_sent"]:
        await show_version_choice(update, context)
        return

    await show_subscription_required(update, context)


async def show_subscription_required(update, context):
    text = (
        "🌸 Привет, дорогая!\n\n"
        "Меня зовут Лера, я твой личный навигатор и автор канала "
        "о том, как перестать жить для других и начать выбирать себя 💖\n\n"
        "Для использования бота нужна подписка на мой канал.\n\n"
        "🎁 После проверки подписки я пришлю тебе чек-лист "
        "«Как отказать без чувства вины»."
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "📢 Подписаться на канал",
                url=channel_url(),
            )
        ],
        [
            InlineKeyboardButton(
                "✅ Проверить подписку",
                callback_data="check_sub",
            )
        ],
    ]

    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.message.reply_text(
            text,
            reply_markup=markup,
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=markup,
        )


async def check_subscription(update: Update, context):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    user = get_user(user_id)

    if user and user["checklist_sent"]:
        await query.message.reply_text(
            "🌿 Ты уже получила чек-лист. Выбирай версию челленджа ниже."
        )
        await show_version_choice(update, context)
        return

    subscribed = await is_subscribed(context.bot, user_id)

    if not subscribed:
        keyboard = [
            [
                InlineKeyboardButton(
                    "📢 Подписаться на канал",
                    url=channel_url(),
                )
            ],
            [
                InlineKeyboardButton(
                    "✅ Проверить подписку",
                    callback_data="check_sub",
                )
            ],
        ]

        await query.edit_message_text(
            "💔 Пока я не вижу подписку на канал.\n\n"
            "Подпишись и нажми «Проверить подписку» ещё раз.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    update_user(
        user_id,
        subscribed=1,
        state="SUBSCRIBED",
    )

    await query.edit_message_text(
        "🌺 Подписка подтверждена!\n\n"
        "🎁 В качестве подарка через 10 секунд я пришлю тебе "
        "чек-лист «Как отказать без чувства вины»."
    )

    # Требование пользователя: ровно 10 секунд.
    # Удаляем возможную предыдущую задачу, чтобы двойное нажатие
    # «Проверить подписку» не отправило два файла.
    remove_job(context, f"checklist:{user_id}")
    context.application.job_queue.run_once(
        send_checklist_job,
        when=10,
        data={"user_id": user_id},
        name=f"checklist:{user_id}",
    )


async def send_checklist_job(context):
    user_id = context.job.data["user_id"]
    user = get_user(user_id)

    if not user or user["checklist_sent"]:
        return

    # Повторно проверяем подписку непосредственно перед отправкой.
    if not await is_subscribed(context.bot, user_id):
        await context.bot.send_message(
            chat_id=user_id,
            text="💔 Перед отправкой подарка я снова проверила подписку "
                 "и больше не вижу её.\n\n"
                 "Подпишись на канал и нажми /start.",
        )
        return

    file_path = find_file(CHECKLIST_FILENAME)

    if not file_path:
        logger.error("Не найден %s", CHECKLIST_FILENAME)
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Чек-лист сейчас недоступен. Проверь файл "
                 f"{CHECKLIST_FILENAME} на сервере.",
        )
        return

    try:
        with open(file_path, "rb") as file:
            await context.bot.send_document(
                chat_id=user_id,
                document=file,
                filename=CHECKLIST_FILENAME,
                caption=(
                    "📋 Держи обещанный чек-лист "
                    "«Как отказать без чувства вины».\n\n"
                    "А через 10 секунд я предложу тебе выбрать "
                    "версию челленджа 🌿"
                ),
            )

        update_user(
            user_id,
            checklist_sent=1,
            state="CHECKLIST_SENT",
        )

        remove_job(context, f"version-choice:{user_id}")
        context.application.job_queue.run_once(
            send_version_choice_job,
            when=10,
            data={"user_id": user_id},
            name=f"version-choice:{user_id}",
        )

    except Exception:
        logger.exception("Ошибка отправки чек-листа user_id=%s", user_id)
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Не получилось отправить чек-лист. "
                 "Попробуй снова через /start.",
        )


async def send_version_choice_job(context):
    user_id = context.job.data["user_id"]
    user = get_user(user_id)

    if not user or user["challenge_started"]:
        return

    await show_version_choice_to_chat(context, user_id)


async def show_version_choice_to_chat(context, user_id):
    text = (
        "🌸 Теперь можно выбрать челлендж.\n\n"
        "У тебя есть две версии. В обеих одинаковые вопросы теста "
        "и одинаковая система из 3 треков.\n\n"
        "📖 **Версия 1.0 — бесплатно**\n"
        "Основной путь: тест → твой трек → 5 дней заданий "
        "и вечерних голосовых.\n\n"
        "🌟 **Версия 2.0 — пока бесплатно на тестовом запуске**\n"
        "Всё содержание основного челленджа +:\n"
        "💎 рабочая тетрадь PDF;\n"
        "💎 бонусное голосовое на 6-й день;\n"
        "💎 закрытый чат участниц;\n"
        "💎 персональная аудио-рефлексия от Леры.\n\n"
        "⚠️ Пока тестовый запуск бесплатный. Позже версия 2.0 станет платной.\n\n"
        "Выбери одну версию. После выбора переключиться на другую "
        "во время прохождения будет нельзя."
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "📖 Челлендж 1.0 — бесплатно",
                callback_data="challenge_1_0",
            )
        ],
        [
            InlineKeyboardButton(
                "🌟 Челлендж 2.0 — бесплатно, тест",
                callback_data="challenge_2_0",
            )
        ],
    ]

    await context.bot.send_message(
        chat_id=user_id,
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_version_choice(update, context):
    if update.callback_query:
        await show_version_choice_to_chat(
            context,
            update.effective_user.id,
        )
    else:
        await show_version_choice_to_chat(
            context,
            update.effective_user.id,
        )


# ============================================================
# ВЫБОР ВЕРСИИ
# ============================================================

async def start_challenge(update: Update, context, version: str):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    user = get_user(user_id)

    if not user:
        create_or_update_user(user_id, update.effective_user.username)
        user = get_user(user_id)

    if user["challenge_started"] or user["version_locked"]:
        old_version = user["challenge_version"] or "другой"
        await query.edit_message_text(
            f"🌿 Ты уже выбрала версию {old_version}.\n\n"
            "Начать вторую версию нельзя, потому что один человек "
            "проходит только один путь челленджа."
        )
        return

    if not user["checklist_sent"]:
        await query.edit_message_text(
            "Сначала нужно подтвердить подписку и получить чек-лист. "
            "Нажми /start."
        )
        return

    update_user(
        user_id,
        challenge_started=1,
        challenge_version=version,
        version_locked=1,
        state="TEST",
        score=0,
        test_question=0,
        current_day=0,
        finished=0,
        start_time=dt_to_db(now_local()),
    )

    if version == "2.0":
        text = (
            "🌟 Ты выбрала Челлендж 2.0!\n\n"
            "Это полная версия с рабочей тетрадью, бонусным 6-м днём "
            "и дополнительными материалами.\n\n"
            "Сначала пройдём тот же тест из 6 вопросов.\n\n"
            "Важно: после выбора версии переключиться на 1.0 уже нельзя."
        )
    else:
        text = (
            "📖 Ты выбрала Челлендж 1.0!\n\n"
            "Это основной бесплатный путь: тест, твой трек, "
            "5 дней заданий и вечерние голосовые.\n\n"
            "После выбора версии переключиться на 2.0 уже нельзя."
        )

    await query.edit_message_text(text)
    remove_job(context, f"question:{user_id}:0")
    context.application.job_queue.run_once(
        send_first_question_job,
        when=1.5,
        data={"user_id": user_id, "question": 0},
        name=f"question:{user_id}:0",
    )


async def send_first_question_job(context):
    user_id = context.job.data["user_id"]
    await send_question_to_user(context, user_id, 0)


async def send_question_to_user(context, user_id: int, q_idx: int):
    user = get_user(user_id)

    if not user or not user["challenge_started"] or user["finished"]:
        return

    if user["state"] != "TEST":
        return

    if q_idx < 0 or q_idx >= len(questions):
        return

    update_user(user_id, test_question=q_idx)

    q = questions[q_idx]

    keyboard = [
        [
            InlineKeyboardButton(
                label,
                callback_data=f"test:{q_idx}:{opt_idx}:{points}",
            )
        ]
        for opt_idx, (label, points) in enumerate(q["options"])
    ]

    await context.bot.send_message(
        chat_id=user_id,
        text=f"🌷 Вопрос {q_idx + 1}/6\n\n{q['text']}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ============================================================
# ТЕСТ
# ============================================================

async def handle_test_answer(update: Update, context):
    query = update.callback_query
    await query.answer()

    try:
        _, q_idx_s, opt_idx_s, points_s = query.data.split(":")
        q_idx = int(q_idx_s)
        opt_idx = int(opt_idx_s)
        points = int(points_s)
    except (ValueError, AttributeError):
        await query.answer("Ошибка ответа. Попробуй ещё раз.", show_alert=True)
        return

    user_id = update.effective_user.id
    user = get_user(user_id)

    if not user or not user["challenge_started"] or user["finished"]:
        await query.answer(
            "Этот тест уже недоступен.",
            show_alert=True,
        )
        return

    if user["state"] != "TEST":
        await query.answer(
            "Тест уже завершён.",
            show_alert=True,
        )
        return

    # Защита от повторного нажатия старой кнопки.
    if int(user["test_question"] or 0) != q_idx:
        await query.answer(
            "Этот вопрос уже закрыт.",
            show_alert=True,
        )
        return

    new_score = int(user["score"] or 0) + points
    update_user(
        user_id,
        score=new_score,
        test_question=q_idx + 1,
    )

    await query.edit_message_text(
        f"✅ Выбрано: {questions[q_idx]['options'][opt_idx][0]}"
    )

    if q_idx + 1 < len(questions):
        remove_job(context, f"question:{user_id}:{q_idx + 1}")
        context.application.job_queue.run_once(
            send_question_job,
            when=1.5,
            data={
                "user_id": user_id,
                "question": q_idx + 1,
            },
            name=f"question:{user_id}:{q_idx + 1}",
        )
    else:
        remove_job(context, f"finish-test:{user_id}")
        context.application.job_queue.run_once(
            finish_test_job,
            when=1.5,
            data={"user_id": user_id},
            name=f"finish-test:{user_id}",
        )


async def send_question_job(context):
    data = context.job.data
    await send_question_to_user(
        context,
        data["user_id"],
        data["question"],
    )


async def finish_test_job(context):
    user_id = context.job.data["user_id"]
    await process_test_result(context, user_id)


async def process_test_result(context, user_id: int):
    user = get_user(user_id)

    if not user or not user["challenge_started"]:
        return

    score = int(user["score"] or 0)

    if 6 <= score <= 9:
        track = 1
        track_desc = (
            "🌿 Ты в контакте с собой\n"
            "Ты умеешь слышать свои желания и ставить границы."
        )
    elif 10 <= score <= 14:
        track = 2
        track_desc = (
            "⚖️ Ты на грани потери\n"
            "Ты ещё помнишь себя настоящую, но всё чаще выбираешь "
            "«надо» вместо «хочу»."
        )
    else:
        track = 3
        track_desc = (
            "🕯️ Ты забыла о себе\n"
            "Ты живёшь в режиме функции. Достижения не радуют, "
            "а внутри — пустота и усталость."
        )

    update_user(
        user_id,
        track=track,
        state="CHALLENGE_RUNNING",
        current_day=1,
    )

    await context.bot.send_message(
        chat_id=user_id,
        text=(
            f"🌸 Твой результат: {score} баллов.\n\n"
            f"{track_desc}\n\n"
            "Теперь начинается твой путь из 5 дней."
        ),
    )

    if user["challenge_version"] == "2.0":
        await send_workbook_to_user(context, user_id)

    # Главное правило расписания:
    # если тест закончен до 19:00 — первое задание сразу,
    # голосовое сегодня в 19:00.
    # Если после 19:00 — первое задание завтра в 09:00.
    current = now_local()

    if current < current.replace(hour=19, minute=0, second=0, microsecond=0):
        await send_morning(context, user_id, 1, scheduled=False)

        start_date = current
        update_user(
            user_id,
            start_time=dt_to_db(start_date),
        )

        schedule_evening_for_day(
            context,
            user_id,
            day=1,
            date_value=current.date(),
        )

        # Дни 2–5 идут по календарю.
        for day in range(2, 6):
            schedule_day(
                context,
                user_id,
                day,
                start_date,
            )

    else:
        tomorrow = current + timedelta(days=1)
        start_date = datetime(
            tomorrow.year,
            tomorrow.month,
            tomorrow.day,
            tzinfo=TZ,
        )

        update_user(
            user_id,
            start_time=dt_to_db(start_date),
        )

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "🌙 Ты присоединилась уже после 19:00.\n\n"
                "Первое задание придёт завтра в **09:00**, "
                "а в **19:00** тебя будет ждать первое голосовое.\n\n"
                "До завтра ничего делать не нужно 💛"
            ),
        )

        for day in range(1, 6):
            schedule_day(
                context,
                user_id,
                day,
                start_date,
            )

    if user["challenge_version"] == "2.0":
        schedule_bonus(
            context,
            user_id,
            start_date,
        )


def schedule_evening_for_day(context, user_id, day, date_value):
    evening = datetime(
        date_value.year,
        date_value.month,
        date_value.day,
        19,
        0,
        0,
        tzinfo=TZ,
    )

    audio_path = AUDIO_FILES.get(1, {}).get(day)
    user = get_user(user_id)

    if user:
        track = int(user["track"] or 0)
        audio_path = AUDIO_FILES.get(track, {}).get(day)

    if not audio_path:
        logger.error(
            "Не найден путь к audio: user=%s track=%s day=%s",
            user_id,
            user["track"] if user else None,
            day,
        )
        return

    schedule_once(
        context,
        evening,
        job_name("evening", user_id, day),
        send_evening_job,
        {"user_id": user_id, "day": day},
    )


# ============================================================
# УТРЕННЕЕ ЗАДАНИЕ
# ============================================================

async def send_morning(context, user_id: int, day: int, scheduled=True):
    user = get_user(user_id)

    if not user:
        return

    if not user["challenge_started"] or user["finished"]:
        return

    if int(user["current_day"] or 0) != day:
        # Разрешаем только следующий день.
        if day != int(user["current_day"] or 0):
            return

    if not await is_subscribed(context.bot, user_id):
        await send_subscription_block(context, user_id)
        return

    track = int(user["track"] or 0)
    text = MORNING_TEXTS.get(
        (track, day),
        "☀️ Утреннее задание ещё не подготовлено.",
    )

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
        )

        update_user(
            user_id,
            current_day=day,
            last_morning_at=dt_to_db(now_local()),
        )

        logger.info(
            "Утреннее задание отправлено: user=%s day=%s track=%s",
            user_id,
            day,
            track,
        )

    except Exception:
        logger.exception(
            "Ошибка утреннего задания user=%s day=%s",
            user_id,
            day,
        )


async def send_subscription_block(context, user_id):
    keyboard = [
        [
            InlineKeyboardButton(
                "📢 Подписаться",
                url=channel_url(),
            )
        ],
        [
            InlineKeyboardButton(
                "✅ Проверить подписку",
                callback_data="check_sub",
            )
        ],
    ]

    await context.bot.send_message(
        chat_id=user_id,
        text=(
            "❌ Я больше не вижу твою подписку на канал.\n\n"
            "Подпишись снова, чтобы получать задания."
        ),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ============================================================
# ВЕЧЕРНЕЕ ГОЛОСОВОЕ
# ============================================================

async def send_evening(context, user_id: int, day: int, scheduled=True):
    user = get_user(user_id)

    if not user:
        return

    if not user["challenge_started"] or user["finished"]:
        return

    if int(user["current_day"] or 0) != day:
        return

    if not await is_subscribed(context.bot, user_id):
        await send_subscription_block(context, user_id)
        return

    track = int(user["track"] or 0)
    caption = VOICE_CAPTIONS.get(
        (track, day),
        "🌙 День завершён. Ты справляешься 💖",
    )

    audio_path = AUDIO_FILES.get(track, {}).get(day)

    if not audio_path or not os.path.exists(audio_path):
        logger.error(
            "Аудиофайл не найден: user=%s track=%s day=%s path=%s",
            user_id,
            track,
            day,
            audio_path,
        )

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "⚠️ Текст вечернего разбора готов, "
                "но аудиофайл сейчас недоступен.\n\n"
                "Я зафиксировала ошибку."
            ),
        )

        # Не ломаем цепочку из-за отсутствия одного файла.
        await advance_to_next_day(context, user_id, day)
        return

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=caption,
        )

        with open(audio_path, "rb") as audio:
            await context.bot.send_voice(
                chat_id=user_id,
                voice=audio,
            )

        update_user(
            user_id,
            last_evening_at=dt_to_db(now_local()),
        )

        logger.info(
            "Вечернее голосовое отправлено: user=%s day=%s track=%s",
            user_id,
            day,
            track,
        )

        await advance_to_next_day(context, user_id, day)

    except Exception:
        logger.exception(
            "Ошибка вечернего сообщения user=%s day=%s",
            user_id,
            day,
        )

        # Следующий день всё равно планируем.
        await advance_to_next_day(context, user_id, day)


async def advance_to_next_day(context, user_id: int, day: int):
    if day >= 5:
        user = get_user(user_id)
        if user and user["challenge_version"] == "1.0":
            update_user(
                user_id,
                finished=1,
                state="FINISHED",
            )
            await send_final_message(context, user_id)

        # Для 2.0 завершение происходит после бонуса дня 6.
        return

    next_day = day + 1
    update_user(
        user_id,
        current_day=next_day,
    )


async def send_final_message(context, user_id):
    await context.bot.send_message(
        chat_id=user_id,
        text=(
            "🌺 Ты прошла Челлендж 1.0!\n\n"
            "Пять дней ты возвращала себе контакт с собой. "
            "Теперь самое важное — не потерять эти открытия в обычной жизни.\n\n"
            "Если хочешь поделиться главным инсайтом, "
            "пришли мне голосовое сообщение 💖"
        ),
    )

    await send_reflection_invitation(context, user_id)


# ============================================================
# БОНУС 2.0 — ДЕНЬ 6
# ============================================================

async def send_bonus(context, user_id):
    user = get_user(user_id)

    if not user:
        return

    if user["challenge_version"] != "2.0":
        return

    if user["bonus_sent"] or user["finished"]:
        return

    if not await is_subscribed(context.bot, user_id):
        await send_subscription_block(context, user_id)
        return

    track = int(user["track"] or 0)
    audio_path = AUDIO_FILES.get(track, {}).get(6)

    await context.bot.send_message(
        chat_id=user_id,
        text=(
            "🌸 Бонусный день 2.0\n\n"
            "«Как закрепить результат и не откатиться назад»\n\n"
            "Сегодня не будет нового большого задания. "
            "Это день, чтобы собрать свои открытия и понять, "
            "что ты хочешь забрать с собой дальше."
        ),
    )

    if audio_path and os.path.exists(audio_path):
        try:
            with open(audio_path, "rb") as audio:
                await context.bot.send_voice(
                    chat_id=user_id,
                    voice=audio,
                )
        except Exception:
            logger.exception("Ошибка бонусного аудио user=%s", user_id)
    else:
        await context.bot.send_message(
            chat_id=user_id,
            text="⚠️ Бонусное аудио пока недоступно.",
        )

    update_user(
        user_id,
        bonus_sent=1,
        finished=1,
        state="FINISHED",
    )

    await context.bot.send_message(
        chat_id=user_id,
        text=(
            "🌺 Ты прошла Челлендж 2.0.\n\n"
            "Спасибо, что прошла этот путь до конца. "
            "Теперь у тебя есть не просто мысли, а конкретные наблюдения "
            "и действия, которые можно забрать в жизнь."
        ),
    )

    await send_reflection_invitation(context, user_id)


# ============================================================
# РАБОЧАЯ ТЕТРАДЬ
# ============================================================

async def send_workbook_to_user(context, user_id):
    file_path = find_file(WORKBOOK_FILENAME)

    if not file_path:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "⚠️ Рабочая тетрадь 2.0 пока не найдена на сервере. "
                "Челлендж продолжится, а файл можно добавить позже."
            ),
        )
        return

    try:
        with open(file_path, "rb") as file:
            await context.bot.send_document(
                chat_id=user_id,
                document=file,
                filename="rabochaya_tetrad_challenge_2_0.pdf",
                caption=(
                    "📋 Рабочая тетрадь к Челленджу 2.0.\n\n"
                    "Сохрани её — здесь ты будешь записывать "
                    "свои инсайты и наблюдения каждый день 💖"
                ),
            )

        update_user(user_id, workbook_sent=1)

    except Exception:
        logger.exception("Ошибка отправки workbook user=%s", user_id)


# ============================================================
# РЕФЛЕКСИЯ
# ============================================================

async def send_reflection_invitation(context, user_id):
    await context.bot.send_message(
        chat_id=user_id,
        text=(
            "💎 Персональная аудио-рефлексия\n\n"
            "Пришли мне голосовое сообщение с твоим главным инсайтом "
            "за этот челлендж.\n\n"
            "Я прослушаю его и отвечу тебе персональным голосовым "
            "сообщением 1–2 минуты.\n\n"
            "Жду твой инсайт 💖"
        ),
    )


async def handle_reflection(update: Update, context):
    user_id = update.effective_user.id
    user = get_user(user_id)

    if not user or not user["finished"]:
        return

    if user["reflection_sent"]:
        await update.message.reply_text(
            "🌸 Твой инсайт уже получен. Спасибо!"
        )
        return

    voice = update.message.voice

    if not voice:
        return

    username = user["username"] or "без_username"

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "🎤 Новый голосовой инсайт!\n"
                f"User ID: {user_id}\n"
                f"Username: @{username}\n"
                f"Версия: {user['challenge_version']}\n"
                f"Трек: {user['track']}"
            ),
        )

        await context.bot.forward_message(
            chat_id=ADMIN_ID,
            from_chat_id=user_id,
            message_id=update.message.message_id,
        )

        update_user(user_id, reflection_sent=1)

        await update.message.reply_text(
            "🌸 Спасибо! Твой голосовой инсайт получен.\n\n"
            "Я прослушаю и отвечу тебе 💖"
        )

    except Exception:
        logger.exception("Ошибка обработки рефлексии user=%s", user_id)
        await update.message.reply_text(
            "Не получилось передать голосовое. Попробуй отправить его ещё раз."
        )


# ============================================================
# КНОПКИ
# ============================================================

async def button_handler(update: Update, context):
    query = update.callback_query
    data = query.data or ""

    if data == "check_sub":
        await check_subscription(update, context)
        return

    if data == "challenge_1_0":
        await start_challenge(update, context, "1.0")
        return

    if data == "challenge_2_0":
        await start_challenge(update, context, "2.0")
        return

    if data.startswith("test:"):
        await handle_test_answer(update, context)
        return

    await query.answer(
        "Эта кнопка больше недоступна.",
        show_alert=True,
    )


# ============================================================
# АДМИНСКИЕ ТЕСТОВЫЕ КОМАНДЫ
# ============================================================

def is_admin(user_id: int) -> bool:
    return int(user_id) == int(ADMIN_ID)


async def admin_status(update: Update, context):
    if not is_admin(update.effective_user.id):
        return

    user_id = update.effective_user.id
    user = get_user(user_id)

    if not user:
        await update.message.reply_text("Пользователь ещё не создан.")
        return

    await update.message.reply_text(
        "📊 STATUS\n\n"
        f"state: {user['state']}\n"
        f"version: {user['challenge_version']}\n"
        f"locked: {user['version_locked']}\n"
        f"track: {user['track']}\n"
        f"score: {user['score']}\n"
        f"day: {user['current_day']}\n"
        f"finished: {user['finished']}\n"
        f"checklist: {user['checklist_sent']}\n"
        f"workbook: {user['workbook_sent']}\n"
        f"bonus: {user['bonus_sent']}"
    )


async def admin_test_morning(update: Update, context):
    if not is_admin(update.effective_user.id):
        return

    user_id = update.effective_user.id
    user = get_user(user_id)

    if not user or not user["challenge_started"]:
        await update.message.reply_text(
            "Сначала создай тестового пользователя через /start "
            "и выбери версию."
        )
        return

    day = int(user["current_day"] or 1)
    await send_morning(context, user_id, day, scheduled=False)
    await update.message.reply_text("✅ Тестовое утреннее задание отправлено.")


async def admin_test_evening(update: Update, context):
    if not is_admin(update.effective_user.id):
        return

    user_id = update.effective_user.id
    user = get_user(user_id)

    if not user or not user["challenge_started"]:
        await update.message.reply_text(
            "Сначала создай тестового пользователя через /start "
            "и выбери версию."
        )
        return

    day = int(user["current_day"] or 1)
    await send_evening(context, user_id, day, scheduled=False)
    await update.message.reply_text("✅ Тестовое вечернее сообщение отправлено.")


async def admin_reset(update: Update, context):
    if not is_admin(update.effective_user.id):
        return

    # /reset 123456789 — сброс конкретного пользователя.
    if not context.args:
        await update.message.reply_text(
            "Использование: /reset USER_ID"
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("USER_ID должен быть числом.")
        return

    update_user(
        target_id,
        state="NEW",
        subscribed=0,
        checklist_sent=0,
        challenge_started=0,
        challenge_version=None,
        version_locked=0,
        track=0,
        score=0,
        test_question=0,
        current_day=0,
        start_time=None,
        finished=0,
        reflection_sent=0,
        workbook_sent=0,
        bonus_sent=0,
        last_morning_at=None,
        last_evening_at=None,
        next_morning_at=None,
        next_evening_at=None,
    )

    cancel_challenge_jobs(context, target_id)

    await update.message.reply_text(
        f"♻️ Пользователь {target_id} сброшен."
    )


async def admin_jobs(update: Update, context):
    if not is_admin(update.effective_user.id):
        return

    jobs = context.job_queue.jobs()

    if not jobs:
        await update.message.reply_text("Активных запланированных задач нет.")
        return

    lines = ["⏰ Активные задачи:\n"]

    for job in jobs:
        lines.append(
            f"• {job.name} → {job.next_t}"
        )

    await update.message.reply_text("\n".join(lines))


# ============================================================
# ВОССТАНОВЛЕНИЕ РАСПИСАНИЯ ПОСЛЕ ПЕРЕЗАПУСКА
# ============================================================

async def restore_schedules(application: Application):
    """
    JobQueue не является постоянным хранилищем.
    Поэтому после перезапуска приложения мы заново создаём
    задачи из состояния SQLite.
    """
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT *
        FROM users
        WHERE challenge_started = 1
          AND finished = 0
          AND state = 'CHALLENGE_RUNNING'
    """)
    rows = cur.fetchall()
    conn.close()

    restored = 0

    for row in rows:
        user = dict(row)

        if not user["start_time"]:
            continue

        start_date = parse_dt(user["start_time"])
        if not start_date:
            continue

        current_day = int(user["current_day"] or 1)

        # Восстанавливаем расписание активного участника.
        # Если сервер был выключен и конкретное время уже прошло,
        # schedule_once не создаст задачу задним числом. Это безопаснее,
        # чем отправлять просроченное задание сразу после рестарта.
        for day in range(current_day, 6):
            schedule_day(
                application,
                user["user_id"],
                day,
                start_date,
            )

        if user["challenge_version"] == "2.0":
            schedule_bonus(
                application,
                user["user_id"],
                start_date,
            )

        restored += 1

    logger.info("Восстановлено расписаний пользователей: %s", restored)


# ============================================================
# POST INIT / ЗАПУСК
# ============================================================

async def post_init(application: Application):
    init_db()
    await restore_schedules(application)
    logger.info(
        "Бот готов. Часовой пояс: %s",
        TIMEZONE_NAME,
    )


def main():
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("status", admin_status)
    )

    application.add_handler(
        CommandHandler("test_morning", admin_test_morning)
    )

    application.add_handler(
        CommandHandler("test_evening", admin_test_evening)
    )

    application.add_handler(
        CommandHandler("reset", admin_reset)
    )

    application.add_handler(
        CommandHandler("jobs", admin_jobs)
    )

    application.add_handler(
        CallbackQueryHandler(button_handler)
    )

    application.add_handler(
        MessageHandler(
            filters.VOICE,
            handle_reflection,
        )
    )

    logger.info("Запуск Telegram-бота...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
