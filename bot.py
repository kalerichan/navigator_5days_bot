import logging
import asyncio
import sqlite3
import os
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

# ================== ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ==================
TOKEN = os.environ.get('BOT_TOKEN')
CHANNEL_ID = os.environ.get('CHANNEL_ID', '@kalerichan')
DIAGNOSTIC_LINK = os.environ.get('DIAGNOSTIC_LINK', 'https://t.me/valeriasereda')

if not TOKEN:
    raise ValueError("Переменная окружения BOT_TOKEN не задана!")

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

CHECKLIST_PDF_PATH = find_file("checklist_spasatel.pdf")
if CHECKLIST_PDF_PATH:
    logging.info(f"Чек-лист найден: {CHECKLIST_PDF_PATH}")
else:
    logging.warning("Чек-лист не найден! Проверь, что файл checklist_spasatel.pdf загружен.")

# ОБНОВЛЁННЫЕ ПУТИ с суффиксом _opus
AUDIO_FILES = {
    "track1": {
        "day1_evening": "files/track1_day1_evening_opus.ogg",
        "day2_evening": "files/track1_day2_evening_opus.ogg",
        "day3_evening": "files/track1_day3_evening_opus.ogg",
        "day4_evening": "files/track1_day4_evening_opus.ogg",
        "day5_evening": "files/track1_day5_evening_opus.ogg",
    },
    "track2": {
        "day1_evening": "files/track2_day1_evening_opus.ogg",
        "day2_evening": "files/track2_day2_evening_opus.ogg",
        "day3_evening": "files/track2_day3_evening_opus.ogg",
        "day4_evening": "files/track2_day4_evening_opus.ogg",
        "day5_evening": "files/track2_day5_evening_opus.ogg",
    },
    "track3": {
        "day1_evening": "files/track3_day1_evening_opus.ogg",
        "day2_evening": "files/track3_day2_evening_opus.ogg",
        "day3_evening": "files/track3_day3_evening_opus.ogg",
        "day4_evening": "files/track3_day4_evening_opus.ogg",
        "day5_evening": "files/track3_day5_evening_opus.ogg",
    }
}

# ================== БАЗА ДАННЫХ ==================
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            score INTEGER DEFAULT 0,
            challenge_started BOOLEAN DEFAULT 0,
            track INTEGER DEFAULT 0,
            current_day INTEGER DEFAULT 0,
            start_time DATETIME,
            checklist_sent_time DATETIME,
            reminder_5min_sent BOOLEAN DEFAULT 0,
            reminder_1hour_sent BOOLEAN DEFAULT 0,
            finished BOOLEAN DEFAULT 0
        )
    ''')
    c.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in c.fetchall()]
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
            'score': row[1],
            'challenge_started': bool(row[2]),
            'track': row[3],
            'current_day': row[4],
            'start_time': row[5],
            'checklist_sent_time': row[6],
            'reminder_5min_sent': bool(row[7]),
            'reminder_1hour_sent': bool(row[8]),
            'finished': bool(row[9])
        }
    return None

def create_user(user_id):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('INSERT INTO users (user_id) VALUES (?)', (user_id,))
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
        logging.info(f"Статус пользователя {user_id} в канале {CHANNEL_ID}: {status}")
        return status in ("member", "administrator", "creator")
    except Exception as e:
        logging.error(f"Ошибка проверки подписки для {user_id}: {e}")
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

def schedule_voice(chat_id, audio_path, run_date, track, day):
    scheduler.add_job(
        send_evening_audio,
        trigger=DateTrigger(run_date=run_date),
        args=[chat_id, audio_path, track, day],
        id=f"voice_{chat_id}_{int(run_date.timestamp())}",
        replace_existing=True
    )

async def send_scheduled_message(chat_id, text, reply_markup):
    try:
        bot = application.bot
        user = get_user(chat_id)
        if user and user['challenge_started']:
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            keyboard = [[InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await bot.send_message(
                chat_id=chat_id,
                text="❌ Ой, кажется, ты отписалась от канала... Чтобы я могла продолжать тебя поддерживать, подпишись снова, пожалуйста 💔",
                reply_markup=reply_markup
            )
    except Exception as e:
        logging.error(f"Ошибка отправки отложенного сообщения: {e}")

async def send_evening_audio(chat_id, audio_path, track, day):
    try:
        bot = application.bot
        if not await is_subscribed(bot, chat_id):
            keyboard = [[InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await bot.send_message(
                chat_id=chat_id,
                text="❌ Ой, кажется, ты отписалась от канала. Чтобы получить голосовое сообщение, подпишись снова 💔",
                reply_markup=reply_markup
            )
            return

        if not os.path.exists(audio_path):
            await bot.send_message(
                chat_id=chat_id,
                text="❌ Извини, файл с голосовым сообщением не найден. Я разбираюсь, попробуй позже 🌸"
            )
            logging.error(f"Аудиофайл не найден: {audio_path}")
            return

        file_size = os.path.getsize(audio_path)
        logging.info(f"Отправка аудио: {audio_path}, размер: {file_size} байт, трек {track}, день {day}")

        caption_text = get_voice_caption(track, day)
        await bot.send_message(chat_id=chat_id, text=caption_text)

        with open(audio_path, 'rb') as f:
            # Используем send_voice для голосовых сообщений (после перекодировки в Opus)
            await bot.send_voice(chat_id=chat_id, voice=f)

        logging.info(f"Голосовое сообщение успешно отправлено для {chat_id}, день {day}")

        if day == 5:
            await send_final_invitation(chat_id)
        else:
            await schedule_next_morning(chat_id, track, day + 1)

    except FileNotFoundError:
        logging.error(f"Аудиофайл не найден при отправке: {audio_path}")
        await bot.send_message(
            chat_id=chat_id,
            text="❌ Ой, файл с голосовым сообщением не найден. Я уже проверяю, что случилось. Попробуй позже 🌸"
        )
    except Exception as e:
        logging.error(f"Ошибка отправки аудио: {e}")
        await bot.send_message(
            chat_id=chat_id,
            text="❌ Произошла ошибка при отправке голосового сообщения. Попробуй позже 🌸"
        )

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

def get_moscow_time(hour, minute=0):
    tz = pytz.timezone('Europe/Moscow')
    now = datetime.now(tz)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target

def get_moscow_time_for_day(day_offset, hour, minute=0):
    tz = pytz.timezone('Europe/Moscow')
    now = datetime.now(tz)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=day_offset)
    return target

async def schedule_next_morning(chat_id, track, next_day):
    if next_day > 5:
        return
    day_offset = next_day - 1
    morning_time = get_moscow_time_for_day(day_offset, 9, 0)
    evening_time = get_moscow_time_for_day(day_offset, 19, 0)

    morning_text = MORNING_TEXTS.get((track, next_day), "Утреннее задание для этого дня ещё не готово, но скоро будет 🌸")
    schedule_message(chat_id, morning_text, morning_time)

    audio_path = AUDIO_FILES[f"track{track}"][f"day{next_day}_evening"]
    schedule_voice(chat_id, audio_path, evening_time, track, next_day)

    logging.info(f"Запланировано утро дня {next_day} на {morning_time}, вечер на {evening_time} для пользователя {chat_id}")

# ================== ЛОГИРОВАНИЕ ==================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================== СОЗДАЁМ APPLICATION ==================
application = Application.builder().token(TOKEN).build()

# ================== ОБРАБОТЧИКИ ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not get_user(user_id):
        create_user(user_id)

    if not await is_subscribed(context.bot, user_id):
        welcome_text = (
            "🌸 Привет, дорогая!\n\n"
            "Меня зовут Лера, я твой личный навигатор и автор канала о том, как перестать жить для других и начать выбирать себя 💖\n\n"
            "Я создала этот бот, чтобы помочь тебе заметить, где ты теряешь себя в ролях «удобной», «спасательницы» и «отличницы».\n\n"
            "Здесь ты сможешь:\n"
            "📋 Получить чек-лист «10 признаков Спасателя» — чтобы увидеть свои паттерны.\n"
            "🗓 Пройти бесплатный 5-дневный челлендж «5 дней ясности» — с заданиями и голосовыми разборами.\n"
            "💬 Написать мне лично, если захочешь разобрать свою ситуацию глубже.\n\n"
            "Чтобы получить доступ ко всем материалам, подпишись на мой канал — там я делюсь инсайтами и анонсами. Это бесплатно и займёт 5 секунд 🌹\n\n"
            "👇 Нажми «Подписаться», а затем «Проверить подписку»."
        )
        keyboard = [
            [InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")],
            [InlineKeyboardButton("✅ Проверить подписку", callback_data="check_sub")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
        return

    keyboard = [
        [InlineKeyboardButton("📋 Чек-лист «Спасатель»", callback_data="checklist")],
        [InlineKeyboardButton("🗓 Челлендж «5 дней»", callback_data="challenge")],
        [InlineKeyboardButton("💬 Написать мне", url=DIAGNOSTIC_LINK)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🌸 Привет, дорогая! Рада видеть тебя снова! 💖\n\n"
        "Ты уже подписана на мой канал, и я благодарна тебе за это. Теперь все материалы открыты для тебя.\n\n"
        "Здесь ты можешь:\n"
        "📋 Получить чек-лист «10 признаков Спасателя» — чтобы увидеть свои паттерны.\n"
        "🗓 Пройти бесплатный 5-дневный челлендж «5 дней ясности» — с заданиями и голосовыми разборами.\n"
        "💬 Написать мне лично, если захочешь разобрать свою ситуацию глубже.\n\n"
        "Выбери, что хочешь получить сегодня:",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data

    if data == "check_sub":
        subscribed = await is_subscribed(context.bot, user_id)
        logger.info(f"Проверка подписки для {user_id}: {subscribed}")
        if subscribed:
            keyboard = [
                [InlineKeyboardButton("📋 Чек-лист «Спасатель»", callback_data="checklist")],
                [InlineKeyboardButton("🗓 Челлендж «5 дней»", callback_data="challenge")],
                [InlineKeyboardButton("💬 Написать мне", url=DIAGNOSTIC_LINK)]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "🌺 Супер! Подписка подтверждена! Теперь все материалы твои 🌸\n\nВыбери, что хочешь получить:",
                reply_markup=reply_markup
            )
        else:
            keyboard = [
                [InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")],
                [InlineKeyboardButton("✅ Проверить подписку", callback_data="check_sub")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "💔 Ой, а ты ещё не подписалась на канал. Это важно, потому что именно там я делюсь всеми новыми материалами и анонсами 🌷\n\n"
                "Пожалуйста, подпишись и нажми «Проверить подписку» снова.",
                reply_markup=reply_markup
            )
        return

    if not await is_subscribed(context.bot, user_id):
        await query.edit_message_text("⚠️ Ты отписалась от канала. Подпишись, чтобы продолжить, хорошо? 🌸")
        keyboard = [[InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Подпишись и нажми «Проверить подписку», и мы продолжим 🌹", reply_markup=reply_markup)
        return

    if data == "checklist":
        await send_checklist(update, context)
    elif data == "challenge":
        await handle_challenge_start(update, context)
    elif data == "start_challenge_from_checklist":
        await handle_challenge_start(update, context)
    elif data.startswith("test_"):
        await handle_test_answer(update, context)
    else:
        await query.edit_message_text("Неизвестная команда 🤔")

# --- Чек-лист ---
async def send_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    file_path = find_file("checklist_spasatel.pdf")
    if not file_path:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Ой, файл с чек-листом не найден... Я уже проверяю, что случилось. Попробуй чуть позже, хорошо? 🌸\n\n"
                 "💡 Если ты загружала файл в папку `files`, перезагрузи бота, и всё заработает!"
        )
        logger.error(f"Файл checklist_spasatel.pdf не найден! Текущая директория: {os.getcwd()}, файлы: {os.listdir('.')}")
        return

    try:
        with open(file_path, 'rb') as f:
            await context.bot.send_document(
                chat_id=chat_id,
                document=f,
                filename="checklist_spasatel.pdf",
                caption="📋 Держи обещанный чек-лист «10 неочевидных признаков, что ты играешь роль Спасателя» 👇\n\nПосмотри внимательно – там много неожиданных открытий 🌸"
            )
        now = datetime.now()
        update_user(user_id, checklist_sent_time=now)

        await context.bot.send_message(
            chat_id=chat_id,
            text="🌺 Чек-лист уже у тебя! Скоро вернусь к тебе, а ты пока изучи чек лист и посмотри насколько откликается 💖"
        )

        text_1min = (
            "🌸 Ну что, дорогая? Сколько пунктов совпало? 😊\n\n"
            "Если больше трёх – я очень рекомендую пройти мой бесплатный челлендж «5 дней ясности».\n"
            "Это очень интересно и познавательно, честно! Мы шаг за шагом выходим из роли Спасателя и начинаем жить для себя 💖\n\n"
            "Хочешь попробовать?"
        )
        keyboard = [[InlineKeyboardButton("🗓 Начать челлендж", callback_data="start_challenge_from_checklist")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        run_date = datetime.now() + timedelta(minutes=1)
        schedule_message(chat_id, text_1min, run_date, reply_markup)

        text_1hour = (
            "🌷 Милая, я вижу, что ты пока не решилась…\n\n"
            "Знаешь, мне очень грустно смотреть на ситуации, когда собственная жизнь откладывается на потом.\n"
            "А ведь всего 10–15 минут в день в течение 5 дней – и ты почувствуешь такие перемены, что сама удивишься! ✨\n\n"
            "Ты достойна этого времени для себя. Давай попробуем? 💗"
        )
        run_date_1hour = datetime.now() + timedelta(hours=1)
        schedule_message(chat_id, text_1hour, run_date_1hour, reply_markup)

    except Exception as e:
        logger.error(f"Ошибка отправки чек-листа: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Что-то пошло не так при отправке файла. Попробуй ещё раз или напиши мне @valeriasereda, я помогу 🌸"
        )

# --- Вступительное сообщение перед тестом ---
async def send_challenge_intro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    intro_text = (
        "🌸 Я рада, что ты решила пройти челлендж «5 дней ясности»!\n\n"
        "Прежде чем мы начнём, я предлагаю тебе пройти небольшой тест «Индекс потери себя». Он поможет понять, на каком ты сейчас этапе и какой трек подойдёт тебе лучше всего.\n\n"
        "Тест состоит из 6 вопросов – отвечай честно, здесь нет правильных или неправильных ответов. Только твоя правда.\n\n"
        "После теста я подберу для тебя индивидуальный трек, и мы начнём челлендж. Готова? 💖"
    )
    await context.bot.send_message(chat_id=chat_id, text=intro_text)
    await asyncio.sleep(2)
    context.user_data['last_feedback_id'] = None
    await send_question(update, context, question_index=0)

# --- Запуск челленджа ---
async def handle_challenge_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        create_user(user_id)
        user = get_user(user_id)

    if not await is_subscribed(context.bot, user_id):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ Ты отписалась от канала. Подпишись, чтобы начать челлендж 🌸"
        )
        keyboard = [[InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Подпишись и нажми «Проверить подписку», и мы продолжим 🌹",
            reply_markup=reply_markup
        )
        return

    if user['challenge_started']:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🌷 Ты уже участвуешь или прошла челлендж. Если потеряла расписание – дождись следующего сообщения или напиши мне @valeriasereda, я помогу 💖"
        )
        return

    update_user(user_id, challenge_started=1, score=0, track=0, current_day=0, start_time=datetime.now(), finished=0)
    await send_challenge_intro(update, context)

# --- Вопросы теста ---
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

async def send_question(update: Update, context: ContextTypes.DEFAULT_TYPE, question_index: int):
    q = questions[question_index]
    keyboard = []
    for i, (label, points) in enumerate(q['options']):
        keyboard.append([InlineKeyboardButton(label, callback_data=f"test_{question_index}_{i}_{points}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    chat_id = update.effective_chat.id
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"🌷 Вопрос {question_index+1}/6\n\n{q['text']}",
        reply_markup=reply_markup
    )

async def handle_test_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split('_')
    _, q_idx, opt_idx, points = data
    q_idx = int(q_idx)
    points = int(points)
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        create_user(user_id)
        user = get_user(user_id)

    if not await is_subscribed(context.bot, user_id):
        await query.edit_message_text("⚠️ Ты отписалась от канала. Подпишись, чтобы продолжить тест 🌸")
        keyboard = [[InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Подпишись и нажми «Проверить подписку», и мы продолжим 🌹", reply_markup=reply_markup)
        return

    new_score = user['score'] + points
    update_user(user_id, score=new_score)

    last_feedback_id = context.user_data.get('last_feedback_id')
    if last_feedback_id:
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=last_feedback_id
            )
        except Exception as e:
            logger.warning(f"Не удалось удалить предыдущий фидбек: {e}")
        context.user_data['last_feedback_id'] = None

    await query.edit_message_text(f"✅ Выбрано: {questions[q_idx]['options'][int(opt_idx)][0]}")
    context.user_data['last_feedback_id'] = query.message.message_id

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

    if 6 <= score <= 9:
        track = 1
        track_desc = (
            "🌿 Ты в контакте с собой\n"
            "Ты умеешь слышать свои желания и ставить границы. Мой челлендж поможет тебе укрепить эту опору и не скатиться обратно в роль «удобной»."
        )
    elif 10 <= score <= 14:
        track = 2
        track_desc = (
            "⚖️ Ты на грани потери\n"
            "Ты ещё помнишь себя настоящую, но всё чаще выбираешь «надо» вместо «хочу». Твоё тело уже подаёт сигналы. Пора остановиться и посмотреть, куда утекает твоя энергия."
        )
    else:
        track = 3
        track_desc = (
            "🕯️ Ты забыла о себе\n"
            "Ты живёшь в режиме функции. Достижения не радуют, а внутри — пустота и усталость. Хорошая новость: ты не сломалась, ты просто слишком долго обслуживала чужие сценарии. Челлендж станет твоим первым шагом обратно к себе."
        )

    update_user(user_id, track=track, current_day=1, start_time=datetime.now())

    result_text = f"🌸 Твой результат: {score} баллов.\n\n{track_desc}\n\nТеперь начинаем челлендж! Сегодня – день 1. Готова? 💖"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=result_text)
    await asyncio.sleep(2)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="💡 Важный совет: закрепи этот чат в Telegram (зажми на пару секунд название чата и выбери «Закрепить»), чтобы не потерять его в течение 5 дней челленджа. Я буду присылать тебе задания и голосовые сообщения каждый день, и они не затеряются 🌸"
    )

    await asyncio.sleep(2)

    # День 1: утро сразу
    day = 1
    morning_text = MORNING_TEXTS.get((track, day), "Утреннее задание для этого дня ещё не готово, но скоро будет 🌸")
    await context.bot.send_message(chat_id=update.effective_chat.id, text=morning_text)

    # Определяем время вечера дня 1
    now_moscow = datetime.now(pytz.timezone('Europe/Moscow'))
    if now_moscow.hour < 19 or (now_moscow.hour == 19 and now_moscow.minute == 0):
        evening_time = get_moscow_time(19, 0)
    else:
        evening_time = get_moscow_time(23, 59)

    audio_path = AUDIO_FILES[f"track{track}"][f"day{day}_evening"]
    schedule_voice(update.effective_chat.id, audio_path, evening_time, track, day)
    logger.info(f"Запланировано вечернее аудио дня 1 для {update.effective_chat.id} на {evening_time}")

    # Планируем день 2: утро в 9:00 МСК, вечер в 19:00 МСК
    await schedule_next_morning(update.effective_chat.id, track, 2)

# ===== Тексты утренних заданий =====
MORNING_TEXTS = {
    (1,1): "☀️ День 1. Мои точки опоры\n\nСегодня мы не будем искать проблемы. Мы будем искать то, что тебя держит.\n\nЗадание:\n- Возьми лист бумаги или заметки в телефоне.\n- Напиши 5 вещей, занятий, моментов, которые возвращают тебе ощущение «я». Это может быть что угодно: утренний кофе в одиночестве, пробежка, звонок подруге, с которой можно молчать, работа над конкретной задачей, запах книги.\n- Напротив каждого пункта напиши, когда в последний раз ты это делала.\n- Выбери один пункт и встрой его в своё расписание на завтра. Прямо сейчас реши, во сколько и как.\n\nВечером я пришлю тебе голосовое сообщение. А пока дыши глубже. Ты в порядке 🌸",
    (1,2): "☀️ День 2. Границы как забота\n\nУмение говорить «нет» — это не про жесткость. Это про заботу о себе.\n\nЗадание:\n- Вспомни одну недавнюю ситуацию, где ты сказала «да», но внутри чувствовала «нет». Или где ты хотела отказаться, но не смогла.\n- Напиши, что именно ты чувствовала в тот момент: вину, страх обидеть, желание быть хорошей?\n- Теперь перепиши эту ситуацию. Напиши идеальный сценарий твоего «нет» — без оправданий, но уважительно.\n- Прочитай написанное вслух. Как ощущения?\n\nЭто упражнение — репетиция. В следующий раз мозгу будет легче 💪",
    (1,3): "☀️ День 3. Тело как союзник\n\nТело — не инструмент для достижений. Оно — твой дом.\n\nЗадание:\n- Сядь удобно, закрой глаза. Сделай три глубоких вдоха.\n- Пройди вниманием от макушки до пальцев ног. Где сейчас живёт тепло, лёгкость, а где — напряжение, тяжесть?\n- Открой глаза и запиши:\n    - Точка напряжения: где она? На что похожа?\n    - Точка ресурса: где в теле тебе сейчас хорошо, спокойно?\n- Задай вопрос точке напряжения: «Что ты хочешь мне сказать?». Запиши первую пришедшую мысль, даже если она кажется странной.\n\nТвоё тело всегда на твоей стороне. Учись его слышать 🌷",
    (1,4): "☀️ День 4. Спасатель vs Поддержка\n\nПомогать можно по-разному: из любви или из страха быть ненужной.\n\nЗадание:\n- Вспомни одну ситуацию за последние дни, где ты кому-то помогла.\n- Ответь честно:\n    - Кому принадлежала проблема изначально?\n    - Тебя просили о помощи или ты предложила сама?\n    - Что ты чувствовала в процессе: энергию и тепло или усталость и раздражение?\n    - Если бы ты не помогла, что бы случилось с тобой? (Стыд? Вина? Страх, что тебя разлюбят?)\n- Если помощь больше напоминала спасение — просто заметь это. Не ругай себя. Ты это увидела, а значит — уже начала выходить из роли 💗",
    (1,5): "☀️ День 5. Мой следующий шаг\n\nТы умеешь слышать себя. Теперь — усилить.\n\nЗадание:\n- Посмотри на записи за эти дни. Что стало самым важным открытием?\n- Напиши одно действие, которое расширит твою «зону авторства» в ближайшую неделю. Это может быть: сказать честно о своей усталости, отказаться от задачи, которую ты обычно берёшь «потому что надо», выделить час в день только для себя и никому не отчитываться.\n- Запиши это действие в календарь. Сделай его неотменяемым 🌸",
    (2,1): "☀️ День 1. Детектор утечки энергии\n\nТы устаёшь не от дел. Ты устаёшь от ролей, которые не твои.\n\nЗадание:\n- Нарисуй таблицу из 4 столбцов:\n    - Роль (сотрудница, жена, дочь, подруга, перфекционистка…)\n    - Энергия ЗАБИРАЕТ (1–10)\n    - Энергия ПРИНОСИТ (1–10)\n    - Разница (Приносит – Забирает)\n- Заполни. Будь честна. Роль «хорошая мать» может забирать 8, а приносить 3 — и это нормально заметить.\n- Посмотри на роли с отрицательной разницей. Выбери одну, которая истощает тебя сильнее всего. Завтра мы продолжим.\n\nТы не плохая. Ты просто слишком долго раздаёшь то, что не восполняется 🌷",
    (2,2): "☀️ День 2. Чей это голос?\n\nМногие цели — не наши. Мы просто взяли их напрокат у родителей, начальников, общества.\n\nЗадание:\n- Выпиши 3 главные цели на этот год (карьера, деньги, статус).\n- Для каждой ответь:\n    - Кто первым сказал, что это важно? (Мама? Партнёр? Коллеги?)\n    - Если бы НИКТО никогда не узнал о моём результате, мне всё ещё было бы это важно?\n    - Какой процент этого желания — попытка доказать что-то другим? (0–100%)\n- Посмотри на проценты. Если больше 60% — скорее всего, цель не твоя. Если ответ «нет» — цель точно навязана.\n\nЭто может быть больно. Но это правда, которая освобождает. Я тоже через это прошла 💖",
    (2,3): "☀️ День 3. Тело не врёт\n\nПока голова думает, что всё нормально, тело уже кричит.\n\nЗадание:\n- Сядь тихо. Закрой глаза. Спроси: «Где сейчас живёт моя усталость?»\n- Запиши все сигналы тела за последний месяц: напряжение в шее/плечах, ком в горле, бессонница, головные боли, проблемы с желудком.\n- Рядом с каждым сигналом напиши: «Что я делала в момент, когда это появилось? Что я чувствовала, но не выразила?»\n\nТвоё тело — твой главный свидетель. Оно не врёт. Верни ему право голоса 🌸",
    (2,4): "☀️ День 4. Маска спасателя\n\nСпасательство — это часто не доброта, а способ контролировать и чувствовать себя нужной.\n\nЗадание:\n- Вспомни одну конкретную ситуацию за последнюю неделю, где ты кого-то «спасала» (решала чужую проблему, брала на себя чужую ответственность).\n- Нарисуй треугольник и поставь себя в одну из ролей: Жертва, Спасатель, Преследователь.\n- Ответь:\n    - Что я чувствовала ДО того, как начала спасать?\n    - Что я чувствовала В ПРОЦЕССЕ?\n    - Что я получила в итоге? (Благодарность? Ощущение контроля? Пустоту?)\n- Что будет, если в следующий раз ты не войдёшь в эту роль? Страх, который возникнет — это и есть твой ключ к выходу 💗",
    (2,5): "☀️ День 5. Один шаг к себе\n\nОсознание — это половина. Теперь — действие.\n\nЗадание:\n- Вернись к Дню 1. Посмотри на роль, которая истощает тебя сильнее всего.\n- Как ты можешь «сыграть» её на 30% меньше?\n    - Не отвечать на рабочие сообщения после 20:00.\n    - Не быть жилеткой для подруги, если у самой нет сил.\n    - Сказать домашним: «Сегодня я готовлю только для себя».\n- Выбери одно маленькое действие и сделай его в ближайшие 48 часов 🌺",
    (3,1): "🕯️ День 1. Стоп-кран\n\nНикаких планов, никаких «надо». Сегодня мы просто останавливаемся.\n\nЗадание:\n- Найди 15 минут тишины. Без телефона, без людей, без задач.\n- Сядь или ляг удобно. Положи руку на грудь.\n- Задай себе вопрос: «Что я сейчас чувствую на самом деле?»\n    - Не «что я должна чувствовать».\n    - Не «что от меня ждут».\n    - А просто — что внутри. Пустота? Грусть? Облегчение? Злость?\n- Запиши первое, что пришло. Даже если это «ничего». Это тоже ответ.\n\nСегодня не надо ничего решать. Просто разреши себе быть 🌸",
    (3,2): "🕯️ День 2. Моё тело говорит\n\nКогда ты забыла о себе, тело помнит всё.\n\nЗадание:\n- В течение дня делай паузы. Каждые 2–3 часа спрашивай: «Что сейчас чувствует моё тело?»\n- Запиши 3–5 сигналов, которые повторяются: усталость, боль, напряжение, пустота в груди.\n- Вечером возьми записи и допиши рядом с каждым сигналом: «Это может говорить о том, что я…»\n\nНичего не исправляй. Просто признай: твоё тело говорило с тобой всё это время 💖",
    (3,3): "🕯️ День 3. Чужие сценарии\n\nНекоторые правила мы выучили так давно, что считаем их своими.\n\nЗадание:\n- Вспомни фразы, которые ты часто слышала в детстве. От родителей, учителей, значимых взрослых. Например: «Ты должна быть сильной», «Не плачь, это стыдно», «Что люди подумают?», «Ты же девочка, будь удобной».\n- Выпиши 5 таких фраз.\n- Рядом с каждой напиши: «Так было тогда. Но сейчас я взрослая. И я могу…» и закончи по-новому.\n\nЭто не предательство. Это взросление 🌷",
    (3,4): "🕯️ День 4. Я имею право\n\nСегодня мы будем возвращать себе то, что у тебя когда-то отобрали.\n\nЗадание:\n- Напиши список из 10–15 пунктов, который начинается словами «Я имею право…». Например:\n    - Я имею право уставать.\n    - Я имею право просить о помощи.\n    - Я имею право злиться.\n    - Я имею право не справляться.\n    - Я имею право быть неудобной.\n    - Я имею право на отдых без чувства вины.\n- Прочитай список вслух. Медленно. Пункт за пунктом.\n- Выбери один пункт, который труднее всего принять. Напиши его на листочке и повесь на видное место.\n\nЭто не бунт. Это возвращение к себе 💗",
    (3,5): "🕯️ День 5. Первый контакт с желанием\n\nТы долго обслуживала чужие сценарии. Сегодня — только ты.\n\nЗадание:\n- Подумай: что бы ты сделала сегодня, если бы никто не ждал от тебя результата? Не «что полезно», а «что приятно».\n- Выбери одно микро-действие. Очень маленькое. Без цели и смысла. Просто для удовольствия: съесть любимое пирожное, не думая о калориях; включить музыку и танцевать; купить себе цветок; лечь в кровать в 19:00 и смотреть глупый сериал.\n- Сделай это. И не объясняй никому 🌸"
}

# ================== ТЕСТОВЫЕ КОМАНДЫ ==================

async def test_force_morning(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user or not user['challenge_started']:
        await update.message.reply_text("❌ Челлендж не начат. Нажми /start и запусти челлендж.")
        return
    track = user['track']
    day = user['current_day']
    if day == 0 or day > 5:
        await update.message.reply_text("❌ Нет активного дня для отправки.")
        return
    morning_text = MORNING_TEXTS.get((track, day), "Утреннее задание не найдено.")
    await context.bot.send_message(chat_id=update.effective_chat.id, text=morning_text)
    await update.message.reply_text(f"✅ Утреннее задание для дня {day} отправлено принудительно.")

async def test_force_evening(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user or not user['challenge_started']:
        await update.message.reply_text("❌ Челлендж не начат.")
        return
    track = user['track']
    day = user['current_day']
    if day == 0 or day > 5:
        await update.message.reply_text("❌ Нет активного дня.")
        return
    audio_path = AUDIO_FILES[f"track{track}"][f"day{day}_evening"]
    if not os.path.exists(audio_path):
        await update.message.reply_text(f"❌ Файл не найден: {audio_path}")
        return
    caption = get_voice_caption(track, day)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=caption)
    with open(audio_path, 'rb') as f:
        await context.bot.send_voice(chat_id=update.effective_chat.id, voice=f)
    await update.message.reply_text(f"✅ Вечернее голосовое для дня {day} отправлено принудительно.")
    if day == 5:
        await send_final_invitation(update.effective_chat.id)

async def test_advance_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user or not user['challenge_started']:
        await update.message.reply_text("❌ Челлендж не начат.")
        return
    current_day = user['current_day']
    if current_day >= 5:
        await update.message.reply_text("❌ Челлендж уже завершён (день 5).")
        return
    next_day = current_day + 1
    update_user(user_id, current_day=next_day)
    await update.message.reply_text(f"✅ День переключён на {next_day}. Теперь можно отправить утро дня {next_day} командой /test_force_morning.")

async def test_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user(user_id, challenge_started=0, score=0, track=0, current_day=0, start_time=None, finished=0)
    await update.message.reply_text("✅ Состояние сброшено. Теперь можно начать челлендж заново через /start и выбор кнопки.")

async def test_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    audio_path = AUDIO_FILES["track1"]["day1_evening"]
    if not os.path.exists(audio_path):
        await update.message.reply_text("❌ Тестовый файл не найден. Проверьте путь: " + audio_path)
        return
    try:
        await update.message.reply_text("🧪 Тестовое голосовое сообщение (трек 1, день 1)")
        with open(audio_path, 'rb') as f:
            await context.bot.send_voice(chat_id=chat_id, voice=f)
        await update.message.reply_text("✅ Голосовое сообщение отправлено. Проверьте, воспроизводится ли оно на телефоне.")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
        logger.error(f"Ошибка тестовой отправки: {e}")

async def test_audio_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        track = int(context.args[0])
        day = int(context.args[1])
        if track not in [1,2,3] or day not in [1,2,3,4,5]:
            await update.message.reply_text("Использование: /test_audio_file <трек 1-3> <день 1-5>")
            return
        audio_path = AUDIO_FILES[f"track{track}"][f"day{day}_evening"]
        if not os.path.exists(audio_path):
            await update.message.reply_text(f"❌ Файл не найден: {audio_path}")
            return
        await update.message.reply_text(f"🧪 Тестовое голосовое (трек {track}, день {day})")
        with open(audio_path, 'rb') as f:
            await context.bot.send_voice(chat_id=update.effective_chat.id, voice=f)
        await update.message.reply_text("✅ Отправлено")
    except (IndexError, ValueError):
        await update.message.reply_text("Использование: /test_audio_file <трек 1-3> <день 1-5>")

# --- Финальное приглашение ---
async def send_final_invitation(chat_id):
    bot = application.bot
    if not await is_subscribed(bot, chat_id):
        keyboard = [[InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await bot.send_message(
            chat_id=chat_id,
            text="❌ Ой, кажется, ты отписалась от канала. Чтобы получить финальное приглашение, подпишись снова 💔",
            reply_markup=reply_markup
        )
        return

    text = (
        "🌟 Ты прошла челлендж «5 дней ясности»! Это огромный шаг – я горжусь тобой 💖\n\n"
        "Если ты чувствуешь, что хочешь разобрать именно твою ситуацию лично – приглашаю на сессию «Разворот».\n"
        "За 1,5 часа мы составим твой индивидуальный маршрут.\n\n"
        "Напиши мне слово «РАЗВОРОТ» и узнай детали. Это бесплатно и ни к чему тебя не обязывает 🌸"
    )
    keyboard = [[InlineKeyboardButton("💬 Написать Лере", url=DIAGNOSTIC_LINK)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)

# ================== ЗАПУСК ==================
def main():
    init_db()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("test_audio", test_audio))
    application.add_handler(CommandHandler("test_force_morning", test_force_morning))
    application.add_handler(CommandHandler("test_force_evening", test_force_evening))
    application.add_handler(CommandHandler("test_advance_day", test_advance_day))
    application.add_handler(CommandHandler("test_reset", test_reset))
    application.add_handler(CommandHandler("test_audio_file", test_audio_file))
    application.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Бот запущен и ожидает сообщения...")
    application.run_polling()

if __name__ == "__main__":
    main()
