import logging
import asyncio
import sqlite3
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from config import BOT_TOKEN, ADMIN_ID, CHANNEL_ID, DIAGNOSTIC_LINK

# ================== ЛОГИРОВАНИЕ ==================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================== ПУТИ К ФАЙЛАМ ==================
def find_file(filename):
    possible_paths = [
        filename,
        os.path.join('files', filename),
        os.path.join('app', filename),
        os.path.join('my_bot', filename),
        os.path.join('..', filename),
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return path
    return None

CHECKLIST_PDF_PATH = find_file("checklist_net.pdf")
if CHECKLIST_PDF_PATH:
    logger.info(f"Чек-лист найден: {CHECKLIST_PDF_PATH}")
else:
    logger.warning("Чек-лист не найден! Проверь, что файл checklist_net.pdf загружен.")

WORKBOOK_PDF = "files/workbook.pdf"

AUDIO_FILES = {
    "track1": {
        "day1_evening": "files/audio/track1_day1_evening.ogg",
        "day2_evening": "files/audio/track1_day2_evening.ogg",
        "day3_evening": "files/audio/track1_day3_evening.ogg",
        "day4_evening": "files/audio/track1_day4_evening.ogg",
        "day5_evening": "files/audio/track1_day5_evening.ogg",
        "day6_bonus": "files/audio/track1_day6_bonus.ogg",
    },
    "track2": {
        "day1_evening": "files/audio/track2_day1_evening.ogg",
        "day2_evening": "files/audio/track2_day2_evening.ogg",
        "day3_evening": "files/audio/track2_day3_evening.ogg",
        "day4_evening": "files/audio/track2_day4_evening.ogg",
        "day5_evening": "files/audio/track2_day5_evening.ogg",
        "day6_bonus": "files/audio/track2_day6_bonus.ogg",
    },
    "track3": {
        "day1_evening": "files/audio/track3_day1_evening.ogg",
        "day2_evening": "files/audio/track3_day2_evening.ogg",
        "day3_evening": "files/audio/track3_day3_evening.ogg",
        "day4_evening": "files/audio/track3_day4_evening.ogg",
        "day5_evening": "files/audio/track3_day5_evening.ogg",
        "day6_bonus": "files/audio/track3_day6_bonus.ogg",
    }
}

# ================== БАЗА ДАННЫХ ==================
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            paid BOOLEAN DEFAULT 0,
            payment_id TEXT,
            payment_date DATETIME,
            challenge_started BOOLEAN DEFAULT 0,
            challenge_version TEXT DEFAULT '1.0',
            track INTEGER DEFAULT 0,
            current_day INTEGER DEFAULT 0,
            start_time DATETIME,
            finished BOOLEAN DEFAULT 0,
            reflection_sent BOOLEAN DEFAULT 0,
            bonus_sent BOOLEAN DEFAULT 0,
            workbook_sent BOOLEAN DEFAULT 0,
            score INTEGER DEFAULT 0,
            checklist_sent_time DATETIME,
            reminder_5min_sent BOOLEAN DEFAULT 0,
            reminder_1hour_sent BOOLEAN DEFAULT 0
        )
    ''')
    c.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in c.fetchall()]
    if 'reflection_sent' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN reflection_sent BOOLEAN DEFAULT 0")
    if 'bonus_sent' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN bonus_sent BOOLEAN DEFAULT 0")
    if 'workbook_sent' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN workbook_sent BOOLEAN DEFAULT 0")
    if 'score' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN score INTEGER DEFAULT 0")
    if 'username' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN username TEXT")
    if 'paid' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN paid BOOLEAN DEFAULT 0")
    if 'payment_id' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN payment_id TEXT")
    if 'payment_date' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN payment_date DATETIME")
    if 'challenge_version' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN challenge_version TEXT DEFAULT '1.0'")
    if 'checklist_sent_time' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN checklist_sent_time DATETIME")
    if 'reminder_5min_sent' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN reminder_5min_sent BOOLEAN DEFAULT 0")
    if 'reminder_1hour_sent' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN reminder_1hour_sent BOOLEAN DEFAULT 0")
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            'user_id': row[0],
            'username': row[1],
            'paid': bool(row[2]),
            'payment_id': row[3],
            'payment_date': row[4],
            'challenge_started': bool(row[5]),
            'challenge_version': row[6],
            'track': row[7],
            'current_day': row[8],
            'start_time': row[9],
            'finished': bool(row[10]),
            'reflection_sent': bool(row[11]),
            'bonus_sent': bool(row[12]),
            'workbook_sent': bool(row[13]),
            'score': row[14],
            'checklist_sent_time': row[15],
            'reminder_5min_sent': bool(row[16]),
            'reminder_1hour_sent': bool(row[17])
        }
    return None

def create_user(user_id, username=None):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('INSERT INTO users (user_id, username) VALUES (?, ?)', (user_id, username))
    conn.commit()
    conn.close()

def update_user(user_id, **kwargs):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    for key, value in kwargs.items():
        c.execute(f'UPDATE users SET {key} = ? WHERE user_id = ?', (value, user_id))
    conn.commit()
    conn.close()

# ================== ПРОВЕРКА ПОДПИСКИ ==================
async def is_subscribed(bot, user_id):
    try:
        chat_member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        status = chat_member.status
        return status in ("member", "administrator", "creator")
    except Exception:
        return False

# ================== ПЛАНИРОВЩИК ==================
scheduler = AsyncIOScheduler()
scheduler.start()

def schedule_message(chat_id, text, run_date, reply_markup=None):
    scheduler.add_job(
        send_scheduled_message,
        trigger=DateTrigger(run_date=run_date),
        args=[chat_id, text, reply_markup],
        id=f"{chat_id}_{int(run_date.timestamp())}",
        replace_existing=True
    )

async def send_scheduled_message(chat_id, text, reply_markup):
    try:
        bot = application.bot
        user = get_user(chat_id)
        if user and user['challenge_started']:
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Ошибка отправки отложенного сообщения: {e}")

# ================== ОСНОВНЫЕ ОБРАБОТЧИКИ ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    user = get_user(user_id)
    if not user:
        create_user(user_id, username)
        user = get_user(user_id)

    if not await is_subscribed(context.bot, user_id):
        await show_subscription_required(update, context)
        return

    # Если уже подписан — показываем меню с выбором версии
    await show_version_choice(update, context)

async def show_subscription_required(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🌸 Привет, дорогая!\n\n"
        "Меня зовут Лера, я твой личный навигатор и автор канала о том, как перестать жить для других и начать выбирать себя 💖\n\n"
        "Чтобы получить доступ к челленджу, подпишись на мой канал.\n\n"
        "👇 Нажми «Подписаться», а затем «Проверить подписку»."
    )
    keyboard = [
        [InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")],
        [InlineKeyboardButton("✅ Проверить подписку", callback_data="check_sub")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup)

async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if await is_subscribed(context.bot, user_id):
        await query.edit_message_text(
            "🌺 Супер! Подписка подтверждена! 🎉\n\n"
            "Сейчас я отправлю тебе чек-лист, а затем расскажу про обновлённый челлендж 💖"
        )
        # Ждём 5 секунд и отправляем чек-лист
        await asyncio.sleep(5)
        await send_checklist(update, context)
    else:
        keyboard = [
            [InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")],
            [InlineKeyboardButton("✅ Проверить подписку", callback_data="check_sub")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "💔 Ты ещё не подписалась на канал. Подпишись и нажми «Проверить подписку» снова.",
            reply_markup=reply_markup
        )

# ================== ЧЕК-ЛИСТ ==================
async def send_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    file_path = find_file("checklist_net.pdf")
    if not file_path:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Ой, файл с чек-листом не найден... Я уже проверяю, что случилось. Попробуй чуть позже, хорошо? 🌸"
        )
        logger.error(f"Файл checklist_net.pdf не найден!")
        return

    try:
        with open(file_path, 'rb') as f:
            await context.bot.send_document(
                chat_id=chat_id,
                document=f,
                filename="checklist_net.pdf",
                caption="📋 Держи обещанный чек-лист «Как отказать без чувства вины» 👇\n\nПосмотри внимательно – там много неожиданных открытий 🌸"
            )
        now = datetime.now()
        update_user(user_id, checklist_sent_time=now)

        # Ждём 5 секунд и отправляем информацию о версиях челленджа
        await asyncio.sleep(5)
        await show_version_choice(update, context)

    except Exception as e:
        logger.error(f"Ошибка отправки чек-листа: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Что-то пошло не так при отправке файла. Попробуй ещё раз или напиши мне @valeriasereda, я помогу 🌸"
        )

# ================== ВЫБОР ВЕРСИИ ЧЕЛЛЕНДЖА ==================
async def show_version_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    text = (
        "🌸 У меня вышло обновление — **Челлендж 2.0**!\n\n"
        "🔥 **Скоро версия 2.0 станет платной**, но пока — тестовый запуск, и ты можешь пройти её **бесплатно**! 💖\n\n"
        "✨ **Что нового в Челлендже 2.0?**\n\n"
        "✅ 5 утренних заданий\n"
        "✅ 5 вечерних голосовых разборов\n"
        "✅ Тест и подбор трека\n\n"
        "💎 Рабочая тетрадь в PDF\n"
        "Один файл на все 5 дней с полями для записей.\n\n"
        "💎 Бонусное голосовое на 6-й день\n"
        "«Как закрепить результат и не откатиться назад»\n\n"
        "💎 Закрытый чат с участницами твоего потока\n"
        "Общее пространство для поддержки.\n\n"
        "💎 Персональная аудио-рефлексия от меня на 7-й день\n"
        "Ты присылаешь голосом свой главный инсайт — я отвечаю персонально.\n\n"
        "🎁 **Какую версию челленджа ты хочешь пройти?**"
    )

    keyboard = [
        [InlineKeyboardButton("📖 Челлендж 1.0 (бесплатно)", callback_data="challenge_1.0")],
        [InlineKeyboardButton("🌟 Челлендж 2.0 (бесплатно, тест)", callback_data="challenge_2.0")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

# ================== ЗАПУСК ЧЕЛЛЕНДЖА ==================

async def start_challenge(update: Update, context: ContextTypes.DEFAULT_TYPE, version="1.0"):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user = get_user(user_id)

    if user['challenge_started']:
        await query.edit_message_text("🌷 Ты уже участвуешь в челлендже.")
        return

    update_user(user_id, challenge_started=True, challenge_version=version, start_time=datetime.now())

    # В зависимости от версии выбираем текст
    if version == "2.0":
        await query.edit_message_text(
            "🌟 Отлично! Ты выбрала **Челлендж 2.0** — самую полную версию с бонусами и рабочей тетрадью! 💖\n\n"
            "Давай начнём с теста «Индекс потери себя».\n"
            "Тест состоит из 6 вопросов – отвечай честно.\n\n"
            "Готова? 💖"
        )
    else:
        await query.edit_message_text(
            "📖 Отлично! Ты выбрала **Челлендж 1.0** — классическую версию.\n\n"
            "Давай начнём с теста «Индекс потери себя».\n"
            "Тест состоит из 6 вопросов – отвечай честно.\n\n"
            "Готова? 💖"
        )

    await asyncio.sleep(2)
    await send_question(update, context, 0)

# ================== ТЕСТ (6 вопросов) ==================

questions = [
    {
        "text": "Когда в последний раз ты делала что-то только для себя, без оглядки на других?",
        "options": [
            ("На этой неделе", 1),
            ("В прошлом месяце", 2),
            ("Даже не помню, когда такое было", 3)
        ]
    },
    {
        "text": "Окружающие чаще всего говорят тебе:",
        "options": [
            ("«Ты всегда знаешь, чего хочешь»", 1),
            ("«На тебя можно положиться»", 2),
            ("«Как ты всё успеваешь?»", 3)
        ]
    },
    {
        "text": "Если тебе нужна помощь, ты:",
        "options": [
            ("Просишь и не чувствуешь вины", 1),
            ("Просишь, но долго переживаешь", 2),
            ("Никогда не просишь, справляешься сама", 3)
        ]
    },
    {
        "text": "Твоё тело чаще всего:",
        "options": [
            ("Полно энергии, высыпаешься", 1),
            ("Бывает напряжение в шее/плечах, но терпимо", 2),
            ("Постоянная усталость, головные боли, ком в горле", 3)
        ]
    },
    {
        "text": "Когда тебя хвалят за достижения, ты внутри:",
        "options": [
            ("Чувствуешь гордость", 1),
            ("Думаешь: «Ой, да это просто повезло»", 2),
            ("Ощущаешь пустоту или страх, что разоблачат", 3)
        ]
    },
    {
        "text": "Представь, что завтра ты исчезнешь из всех своих ролей (работа, семья). Что ты почувствуешь в первую секунду?",
        "options": [
            ("Любопытство", 1),
            ("Тревогу", 2),
            ("Облегчение", 3)
        ]
    }
]

async def send_question(update: Update, context: ContextTypes.DEFAULT_TYPE, q_idx: int):
    q = questions[q_idx]
    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"test_{q_idx}_{i}_{points}")]
        for i, (label, points) in enumerate(q['options'])
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    chat_id = update.effective_chat.id
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"🌷 Вопрос {q_idx+1}/6\n\n{q['text']}",
        reply_markup=reply_markup
    )

async def handle_test_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if not data.startswith("test_"):
        return

    _, q_idx, opt_idx, points = data.split('_')
    q_idx = int(q_idx)
    points = int(points)
    user_id = update.effective_user.id
    user = get_user(user_id)

    new_score = user['score'] + points
    update_user(user_id, score=new_score)

    await query.edit_message_text(f"✅ Выбрано: {questions[q_idx]['options'][int(opt_idx)][0]}")

    if q_idx + 1 < len(questions):
        await asyncio.sleep(1.5)
        await send_question(update, context, q_idx + 1)
    else:
        await asyncio.sleep(1.5)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🌸 Тест завершён! Сейчас я скажу, какой трек тебе подходит 💖"
        )
        await asyncio.sleep(2)
        await process_test_result(update, context)

async def process_test_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    score = user['score']
    version = user['challenge_version']

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
            "Ты ещё помнишь себя настоящую, но всё чаще выбираешь «надо» вместо «хочу»."
        )
    else:
        track = 3
        track_desc = (
            "🕯️ Ты забыла о себе\n"
            "Ты живёшь в режиме функции. Достижения не радуют, а внутри — пустота и усталость."
        )

    update_user(user_id, track=track, current_day=1)

    result_text = f"🌸 Твой результат: {score} баллов.\n\n{track_desc}\n\nТеперь начинаем челлендж! Сегодня – день 1. Готова? 💖"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=result_text)
    await asyncio.sleep(2)

    # Если версия 2.0, отправляем рабочую тетрадь
    if version == "2.0":
        await send_workbook(update, context)

    # Отправляем утро дня 1
    day = 1
    morning_text = MORNING_TEXTS.get((track, day), "Утреннее задание для этого дня ещё не готово 🌸")
    await context.bot.send_message(chat_id=update.effective_chat.id, text=morning_text)

    # Планируем вечер дня 1 (через 8 часов)
    audio_path = AUDIO_FILES[f"track{track}"][f"day{day}_evening"]
    if os.path.exists(audio_path):
        run_date = datetime.now() + timedelta(hours=8)
        scheduler.add_job(
            send_evening_audio,
            trigger=DateTrigger(run_date=run_date),
            args=[update.effective_chat.id, audio_path, track, day, version]
        )
        logger.info(f"Запланировано вечернее аудио дня 1 на {run_date}")

    # Планируем день 2
    await schedule_next_morning(update.effective_chat.id, track, 2, version)

async def send_evening_audio(chat_id, audio_path, track, day, version):
    try:
        bot = application.bot
        caption = get_voice_caption(track, day)
        await bot.send_message(chat_id=chat_id, text=caption)
        with open(audio_path, 'rb') as f:
            await bot.send_voice(chat_id=chat_id, voice=f)
        logger.info(f"Вечернее аудио дня {day} отправлено для {chat_id}")

        if day == 5 and version == "2.0":
            await send_bonus_audio(chat_id, track)
        elif day < 5:
            await schedule_next_morning(chat_id, track, day + 1, version)
    except Exception as e:
        logger.error(f"Ошибка отправки аудио: {e}")

async def send_bonus_audio(chat_id, track):
    audio_path = AUDIO_FILES[f"track{track}"]["day6_bonus"]
    if os.path.exists(audio_path):
        await asyncio.sleep(5)
        bot = application.bot
        await bot.send_message(
            chat_id=chat_id,
            text="🌸 Бонусный день!\n\n"
                 "«Как закрепить результат и не откатиться назад»\n\n"
                 "Это голосовое сообщение для тебя — чтобы завершить челлендж мягко и с чувством опоры."
        )
        with open(audio_path, 'rb') as f:
            await bot.send_voice(chat_id=chat_id, voice=f)

        await bot.send_message(
            chat_id=chat_id,
            text="🌺 Ты молодец! Челлендж пройден.\n\n"
                 "Теперь у тебя есть все инструменты, чтобы продолжать выбирать себя."
        )
        update_user(chat_id, bonus_sent=True, finished=True)

        # Отправляем приглашение на рефлексию
        await asyncio.sleep(5)
        await send_reflection_invitation(chat_id)

async def send_reflection_invitation(chat_id):
    bot = application.bot
    await bot.send_message(
        chat_id=chat_id,
        text="💎 Персональная аудио-рефлексия\n\n"
             "Пришли мне голосовое сообщение с твоим главным инсайтом за этот челлендж.\n"
             "Я прослушаю и отвечу тебе персональным голосовым сообщением 1–2 минуты.\n\n"
             "Просто нажми на кнопку «🎤 Записать голосовое» в Telegram и отправь мне.\n\n"
             "Жду твой инсайт! 💖"
    )

async def handle_reflection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user or not user['finished']:
        return
    if user['reflection_sent']:
        await update.message.reply_text("Ты уже получила рефлексию! 🌸")
        return

    voice = update.message.voice
    if voice:
        file = await context.bot.get_file(voice.file_id)
        os.makedirs("data/reflections", exist_ok=True)
        file_path = f"data/reflections/{user_id}_{datetime.now().timestamp()}.ogg"
        await file.download_to_drive(file_path)

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🎤 Новое голосовое сообщение для рефлексии!\nПользователь: {user_id} (@{user['username']})"
        )
        await context.bot.forward_message(
            chat_id=ADMIN_ID,
            from_chat_id=user_id,
            message_id=update.message.message_id
        )

        update_user(user_id, reflection_sent=True)
        await update.message.reply_text(
            "🌸 Спасибо! Твой голосовой инсайт получен.\n\n"
            "Я прослушаю и отвечу тебе в ближайшее время 💖"
        )

async def schedule_next_morning(chat_id, track, next_day, version):
    if next_day > 5:
        return
    user = get_user(chat_id)
    if not user or not user.get('start_time'):
        start_time = datetime.now()
    else:
        start_time = user['start_time']

    base_day = start_time + timedelta(days=(next_day - 1))
    morning_time = base_day.replace(hour=9, minute=0, second=0, microsecond=0)
    evening_time = base_day.replace(hour=19, minute=0, second=0, microsecond=0)

    now = datetime.now()
    if morning_time < now:
        morning_time += timedelta(days=1)
        evening_time += timedelta(days=1)

    morning_text = MORNING_TEXTS.get((track, next_day), "Утреннее задание для этого дня ещё не готово 🌸")
    schedule_message(chat_id, morning_text, morning_time)

    audio_path = AUDIO_FILES[f"track{track}"][f"day{next_day}_evening"]
    if os.path.exists(audio_path):
        scheduler.add_job(
            send_evening_audio,
            trigger=DateTrigger(run_date=evening_time),
            args=[chat_id, audio_path, track, next_day, version]
        )
        logger.info(f"Запланировано вечернее аудио дня {next_day} на {evening_time}")

# ================== РАБОЧАЯ ТЕТРАДЬ ==================

async def send_workbook(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if os.path.exists(WORKBOOK_PDF):
        with open(WORKBOOK_PDF, 'rb') as f:
            await context.bot.send_document(
                chat_id=chat_id,
                document=f,
                filename="rabochaya_tetrad_challenge_2_0.pdf",
                caption="📋 **Рабочая тетрадь к челленджу 2.0**\n\n"
                        "Сохрани её — здесь ты будешь записывать свои инсайты и наблюдения каждый день.\n\n"
                        "Это поможет структурировать опыт и не потерять важные открытия. 💖"
            )
        update_user(user_id, workbook_sent=True)
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Рабочая тетрадь временно недоступна. Я разбираюсь, попробуй позже 🌸"
        )

# ================== ТЕКСТЫ УТРЕННИХ ЗАДАНИЙ ==================

def get_voice_caption(track, day):
    captions = {
        (1,1): "✨ Ты отлично справилась с днём 1! Ты искала свои точки опоры — это важный шаг к себе. Горжусь тобой 💖",
        (1,2): "💪 День 2 пройден! Ты училась говорить «нет» и защищать свои границы – это смело. Продолжай в том же духе!",
        (1,3): "🌿 Ты уже на полпути! Сегодня ты слушала своё тело — это очень ценно. Ты молодец!",
        (1,4): "💗 Четвёртый день позади. Ты разбиралась с ролью Спасателя — это трудная работа, но ты справляешься!",
        (1,5): "🌟 Ты сделала это! Пять дней ты была в контакте с собой. Ты — невероятная!",
        (2,1): "✨ День 1 завершён! Ты нашла свои источники утечки энергии — это первый шаг к восстановлению. Ты сильная!",
        (2,2): "💪 День 2 пройден! Ты осознала, какие цели не твои — это освобождает. Ты на верном пути!",
        (2,3): "🌿 Ты уже на полпути! Сегодня ты слушала своё тело — это очень ценно. Ты молодец!",
        (2,4): "💗 Четвёртый день позади. Ты увидела свою роль Спасателя — это открытие меняет всё. Ты справляешься!",
        (2,5): "🌟 Ты сделала это! Пять дней ты искала себя. Ты — невероятная!",
        (3,1): "✨ День 1 завершён! Ты остановилась и разрешила себе быть — это самое важное. Ты уже начала путь!",
        (3,2): "💪 День 2 пройден! Ты начала слышать своё тело — это мощный шаг. Продолжай!",
        (3,3): "🌿 Ты уже на полпути! Ты переписываешь чужие сценарии — это твой выбор. Горжусь тобой!",
        (3,4): "💗 Четвёртый день позади. Ты возвращаешь себе право быть — это революция. Ты невероятна!",
        (3,5): "🌟 Ты сделала это! Пять дней ты шла к себе. Ты — моя героиня!"
    }
    return captions.get((track, day), "🌙 Отличная работа! Ты справляешься с челленджем прекрасно 💖")

MORNING_TEXTS = {
    (1,1): "☀️ День 1. Мои точки опоры\n\nСегодня мы не будем искать проблемы. Мы будем искать то, что тебя держит.\n\nЗадание:\n- Возьми лист бумаги или заметки в телефоне.\n- Напиши 5 вещей, занятий, моментов, которые возвращают тебе ощущение «я».\n- Напротив каждого пункта напиши, когда в последний раз ты это делала.\n- Выбери один пункт и встрой его в своё расписание на завтра.\n\nВечером я пришлю тебе голосовое сообщение. А пока дыши глубже. Ты в порядке 🌸",
    (1,2): "☀️ День 2. Границы как забота\n\nУмение говорить «нет» — это не про жесткость. Это про заботу о себе.\n\nЗадание:\n- Вспомни одну недавнюю ситуацию, где ты сказала «да», но внутри чувствовала «нет».\n- Напиши, что именно ты чувствовала в тот момент.\n- Теперь перепиши эту ситуацию. Напиши идеальный сценарий твоего «нет».\n- Прочитай написанное вслух.\n\nЭто упражнение — репетиция. В следующий раз мозгу будет легче 💪",
    (1,3): "☀️ День 3. Тело как союзник\n\nТело — не инструмент для достижений. Оно — твой дом.\n\nЗадание:\n- Сядь удобно, закрой глаза. Сделай три глубоких вдоха.\n- Пройди вниманием от макушки до пальцев ног.\n- Открой глаза и запиши: Точка напряжения и Точка ресурса.\n- Задай вопрос точке напряжения: «Что ты хочешь мне сказать?».\n\nТвоё тело всегда на твоей стороне. Учись его слышать 🌷",
    (1,4): "☀️ День 4. Спасатель vs Поддержка\n\nПомогать можно по-разному: из любви или из страха быть ненужной.\n\nЗадание:\n- Вспомни одну ситуацию за последние дни, где ты кому-то помогла.\n- Ответь честно: Кому принадлежала проблема? Тебя просили о помощи или ты предложила сама?\n- Если помощь больше напоминала спасение — просто заметь это.\n\nТы это увидела, а значит — уже начала выходить из роли 💗",
    (1,5): "☀️ День 5. Мой следующий шаг\n\nТы умеешь слышать себя. Теперь — усилить.\n\nЗадание:\n- Посмотри на записи за эти дни. Что стало самым важным открытием?\n- Напиши одно действие, которое расширит твою «зону авторства» в ближайшую неделю.\n- Запиши это действие в календарь. Сделай его неотменяемым 🌸",
    (2,1): "☀️ День 1. Детектор утечки энергии\n\nТы устаёшь не от дел. Ты устаёшь от ролей, которые не твои.\n\nЗадание:\n- Нарисуй таблицу из 4 столбцов: Роль, Энергия ЗАБИРАЕТ (1–10), Энергия ПРИНОСИТ (1–10), Разница.\n- Заполни. Будь честна.\n- Выбери одну роль, которая истощает тебя сильнее всего.\n\nТы не плохая. Ты просто слишком долго раздаёшь то, что не восполняется 🌷",
    (2,2): "☀️ День 2. Чей это голос?\n\nМногие цели — не наши. Мы просто взяли их напрокат.\n\nЗадание:\n- Выпиши 3 главные цели на этот год.\n- Для каждой ответь: Кто первым сказал, что это важно?\n- Если бы НИКТО никогда не узнал о моём результате, мне всё ещё было бы это важно?\n\nЭто может быть больно. Но это правда, которая освобождает 💖",
    (2,3): "☀️ День 3. Тело не врёт\n\nПока голова думает, что всё нормально, тело уже кричит.\n\nЗадание:\n- Сядь тихо. Закрой глаза. Спроси: «Где сейчас живёт моя усталость?»\n- Запиши все сигналы тела за последний месяц.\n- Рядом с каждым сигналом напиши: «Что я делала в момент, когда это появилось?»\n\nТвоё тело — твой главный свидетель. Верни ему право голоса 🌸",
    (2,4): "☀️ День 4. Маска спасателя\n\nСпасательство — это часто не доброта, а способ контролировать и чувствовать себя нужной.\n\nЗадание:\n- Вспомни одну конкретную ситуацию за последнюю неделю, где ты кого-то «спасала».\n- Ответь: Что ты чувствовала ДО, В ПРОЦЕССЕ и ПОСЛЕ?\n- Что будет, если в следующий раз ты не войдёшь в эту роль?\n\nСтрах, который возникнет — это и есть твой ключ к выходу 💗",
    (2,5): "☀️ День 5. Один шаг к себе\n\nОсознание — это половина. Теперь — действие.\n\nЗадание:\n- Вернись к Дню 1. Посмотри на роль, которая истощает тебя сильнее всего.\n- Как ты можешь «сыграть» её на 30% меньше?\n- Выбери одно маленькое действие и сделай его в ближайшие 48 часов 🌺",
    (3,1): "🕯️ День 1. Стоп-кран\n\nНикаких планов, никаких «надо». Сегодня мы просто останавливаемся.\n\nЗадание:\n- Найди 15 минут тишины. Без телефона, без людей, без задач.\n- Сядь или ляг удобно. Положи руку на грудь.\n- Задай себе вопрос: «Что я сейчас чувствую на самом деле?»\n\nСегодня не надо ничего решать. Просто разреши себе быть 🌸",
    (3,2): "🕯️ День 2. Моё тело говорит\n\nКогда ты забыла о себе, тело помнит всё.\n\nЗадание:\n- В течение дня делай паузы. Каждые 2–3 часа спрашивай: «Что сейчас чувствует моё тело?»\n- Запиши 3–5 сигналов, которые повторяются.\n- Вечером допиши: «Это может говорить о том, что я…»\n\nНичего не исправляй. Просто признай: твоё тело говорило с тобой всё это время 💖",
    (3,3): "🕯️ День 3. Чужие сценарии\n\nНекоторые правила мы выучили так давно, что считаем их своими.\n\nЗадание:\n- Вспомни фразы, которые ты часто слышала в детстве.\n- Выпиши 5 таких фраз.\n- Рядом с каждой напиши: «Так было тогда. Но сейчас я взрослая. И я могу…»\n\nЭто не предательство. Это взросление 🌷",
    (3,4): "🕯️ День 4. Я имею право\n\nСегодня мы будем возвращать себе то, что у тебя когда-то отобрали.\n\nЗадание:\n- Напиши список из 10–15 пунктов, который начинается словами «Я имею право…».\n- Прочитай список вслух. Медленно. Пункт за пунктом.\n- Выбери один пункт, который труднее всего принять. Напиши его на листочке и повесь на видное место.\n\nЭто не бунт. Это возвращение к себе 💗",
    (3,5): "🕯️ День 5. Первый контакт с желанием\n\nТы долго обслуживала чужие сценарии. Сегодня — только ты.\n\nЗадание:\n- Подумай: что бы ты сделала сегодня, если бы никто не ждал от тебя результата? Не «что полезно», а «что приятно».\n- Выбери одно микро-действие. Очень маленькое. Без цели и смысла. Просто для удовольствия.\n- Сделай это. И не объясняй никому 🌸"
}

# ================== ОБРАБОТЧИКИ КНОПОК ==================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data

    if data == "check_sub":
        await check_subscription(update, context)
        return

    if data == "challenge_1.0":
        await start_challenge(update, context, "1.0")
        return

    if data == "challenge_2.0":
        await start_challenge(update, context, "2.0")
        return

    if data.startswith("test_"):
        await handle_test_answer(update, context)
        return

    await query.edit_message_text("Неизвестная команда 🤔")

# ================== ЗАПУСК ==================
def main():
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.VOICE, handle_reflection))
    logger.info("Бот запущен и ожидает сообщения...")
    application.run_polling()

if __name__ == "__main__":
    main()
