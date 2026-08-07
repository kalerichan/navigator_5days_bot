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

CHECKLIST_PDF_PATH = find_file("checklist_net.pdf")
if CHECKLIST_PDF_PATH:
    logging.info(f"Чек-лист найден: {CHECKLIST_PDF_PATH}")
else:
    logging.warning("Чек-лист не найден! Проверь, что файл checklist_net.pdf загружен.")

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

    user = get_user(chat_id)
    if not user or not user.get('start_time'):
        logging.error(f"Не найден start_time для пользователя {chat_id}, планирование невозможно")
        start_time = datetime.now(pytz.timezone('Europe/Moscow'))
    else:
        start_time = user['start_time']
        if isinstance(start_time, str):
            start_time = datetime.fromisoformat(start_time)
        if start_time.tzinfo is None:
            start_time = pytz.timezone('Europe/Moscow').localize(start_time)

    base_day = start_time + timedelta(days=(next_day - 1))
    morning_time = base_day.replace(hour=9, minute=0, second=0, microsecond=0)
    evening_time = base_day.replace(hour=19, minute=0, second=0, microsecond=0)

    now_moscow = datetime.now(pytz.timezone('Europe/Moscow'))
    if morning_time < now_moscow:
        morning_time += timedelta(days=1)
        evening_time += timedelta(days=1)

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
            "📋 Получить чек-лист «Как отказать без чувства вины» — чтобы научиться говорить «нет» без угрызений совести.\n"
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

    # Если уже подписана — сразу чек-лист
    await send_checklist(update, context)

# ================== ЧЕК-ЛИСТ ==================
async def send_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    file_path = find_file("checklist_net.pdf")
    if not file_path:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Ой, файл с чек-листом не найден... Я уже проверяю, что случилось. Попробуй чуть позже, хорошо? 🌸\n\n"
                 "💡 Если ты загружала файл в папку `files`, перезагрузи бота, и всё заработает!"
        )
        logger.error(f"Файл checklist_net.pdf не найден! Текущая директория: {os.getcwd()}, файлы: {os.listdir('.')}")
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

        await context.bot.send_message(
            chat_id=chat_id,
            text="🌺 Чек-лист уже у тебя! А теперь расскажу тебе про обновлённый челлендж 💖"
        )

        await asyncio.sleep(1)
        await show_version_choice(update, context)

    except Exception as e:
        logger.error(f"Ошибка отправки чек-листа: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Что-то пошло не так при отправке файла. Попробуй ещё раз или напиши мне @valeriasereda, я помогу 🌸"
        )

# ================== ВЫБОР ВЕРСИИ ЧЕЛЛЕНДЖА ==================
async def show_version_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает выбор версии челленджа."""
    chat_id = update.effective_chat.id

    text = (
        "🌸 У меня вышло обновление — **Челлендж 2.0**! Теперь он **платный** (700₽).\n\n"
        "✨ **Что поменялось?**\n\n"
        "| Бесплатная версия (было) | Платная версия 2.0 (за 700₽) |\n"
        "|---|---|\n"
        "| 5 утренних заданий | 5 утренних заданий (те же) |\n"
        "| 5 вечерних голосовых | 5 вечерних голосовых (те же) |\n"
        "| Тест и подбор трека | Тест и подбор трека |\n"
        "| ❌ Не было | ✅ Рабочая тетрадь в PDF (1 файл на все 5 дней) |\n"
        "| ❌ Не было | ✅ 1 бонусное голосовое на 6-й день |\n"
        "| ❌ Не было | ✅ Закрытый чат с участницами твоего потока |\n"
        "| ❌ Не было | ✅ Персональная аудио-рефлексия от меня на 7-й день |\n\n"
        "Я создала это специально для того, чтобы дать больше пользы, но это потребовало и большего ресурса. "
        "Я не хочу забирать бесплатную возможность, но также готова дать больше.\n\n"
        "**Какую версию челленджа ты хочешь пройти?**"
    )

    keyboard = [
        [InlineKeyboardButton("🎁 Продолжить бесплатно", callback_data="start_free_challenge")],
        [InlineKeyboardButton("💎 Приобрести доступ к новой версии", callback_data="buy_paid_version")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

# ================== ОБРАБОТЧИКИ КНОПОК ==================
async def start_free_challenge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запускает бесплатную версию челленджа."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🌸 Отлично! Запускаем бесплатную версию челленджа. Давай начнём с теста! 💖")
    await asyncio.sleep(1)
    await handle_challenge_start(update, context)

async def buy_paid_version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет информацию о покупке платной версии."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "💎 Ссылка на оплату пока не добавлена. Свяжитесь с @valeriasereda для получения доступа к платной версии."
    )

# ================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data

    if data == "check_sub":
        subscribed = await is_subscribed(context.bot, user_id)
        logger.info(f"Проверка подписки для {user_id}: {subscribed}")
        if subscribed:
            await query.edit_message_text(
                "🌺 Супер! Подписка подтверждена! Теперь все материалы твои 🌸"
            )
            await send_checklist(update, context)
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
        await show_version_choice(update, context)
    elif data == "start_free_challenge":
        await start_free_challenge(update, context)
    elif data == "buy_paid_version":
        await buy_paid_version(update, context)
    elif data == "start_challenge_from_checklist":
        await show_version_choice(update, context)
    elif data.startswith("test_"):
        await handle_test_answer(update, context)
    else:
        await query.edit_message_text("Неизвестная команда 🤔")

# ================== ЗАПУСК ЧЕЛЛЕНДЖА ==================
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

# ================== ТЕСТ (вопросы) ==================
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

# ================== ВОПРОСЫ ТЕСТА ==================
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
            "Ты умеешь слышать свои желания и ставить границы. Мой челлендж поможет тебе укрепить эту опору и не скатиться обратно в роль
