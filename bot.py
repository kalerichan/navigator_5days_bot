import logging
import asyncio
import sqlite3
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger

# ================== ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ==================
TOKEN = os.environ.get('BOT_TOKEN')
CHANNEL_ID = os.environ.get('CHANNEL_ID', '@kalerichan')
DIAGNOSTIC_LINK = os.environ.get('DIAGNOSTIC_LINK', 'https://t.me/valeriasereda')

if not TOKEN:
    raise ValueError("Переменная окружения BOT_TOKEN не задана!")

# ================== ПУТИ К ФАЙЛАМ ==================
CHECKLIST_PDF = "files/checklist_spasatel.pdf"
AUDIO_FILES = {
    "track1": {
        "day1_evening": "files/track1_day1_evening.ogg",
        "day2_evening": "files/track1_day2_evening.ogg",
        "day3_evening": "files/track1_day3_evening.ogg",
        "day4_evening": "files/track1_day4_evening.ogg",
        "day5_evening": "files/track1_day5_evening.ogg",
    },
    "track2": {
        "day1_evening": "files/track2_day1_evening.ogg",
        "day2_evening": "files/track2_day2_evening.ogg",
        "day3_evening": "files/track2_day3_evening.ogg",
        "day4_evening": "files/track2_day4_evening.ogg",
        "day5_evening": "files/track2_day5_evening.ogg",
    },
    "track3": {
        "day1_evening": "files/track3_day1_evening.ogg",
        "day2_evening": "files/track3_day2_evening.ogg",
        "day3_evening": "files/track3_day3_evening.ogg",
        "day4_evening": "files/track3_day4_evening.ogg",
        "day5_evening": "files/track3_day5_evening.ogg",
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
            morning_sent BOOLEAN DEFAULT 0,
            finished BOOLEAN DEFAULT 0
        )
    ''')
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
            'morning_sent': bool(row[7]),
            'finished': bool(row[8])
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
scheduler = BackgroundScheduler()
scheduler.start()

def schedule_message(chat_id, text, delay_seconds, reply_markup=None):
    run_date = datetime.now() + timedelta(seconds=delay_seconds)
    trigger = DateTrigger(run_date=run_date)
    scheduler.add_job(
        send_scheduled_message,
        trigger,
        args=[chat_id, text, reply_markup],
        id=f"{chat_id}_{int(run_date.timestamp())}",
        replace_existing=True
    )

async def send_scheduled_message(chat_id, text, reply_markup):
    try:
        bot = application.bot
        if await is_subscribed(bot, chat_id):
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            keyboard = [[InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await bot.send_message(
                chat_id=chat_id,
                text="❌ Вы отписались от канала. Чтобы продолжить получать материалы челленджа, подпишитесь снова.",
                reply_markup=reply_markup
            )
    except Exception as e:
        logging.error(f"Ошибка отправки отложенного сообщения: {e}")

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
            "Меня зовут Лера, я твой личный навигатор и автор канала о том, как перестать жить для других и начать выбирать себя.\n\n"
            "Я создала этот бот, чтобы помочь тебе заметить, где ты теряешь себя в ролях «удобной», «спасательницы» и «отличницы».\n\n"
            "Здесь ты сможешь:\n"
            "📋 Получить чек-лист «10 признаков Спасателя» — чтобы увидеть свои паттерны.\n"
            "🗓 Пройти бесплатный 5-дневный челлендж «5 дней ясности» — с заданиями и голосовыми разборами.\n"
            "💬 Написать мне лично, если захочешь разобрать свою ситуацию глубже.\n\n"
            "Чтобы получить доступ ко всем материалам, подпишись на мой канал — там я делюсь инсайтами и анонсами. Это бесплатно и займёт 5 секунд.\n\n"
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
        [InlineKeyboardButton("💬 Написать Лере", url=DIAGNOSTIC_LINK)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🌸 Привет! Я навигатор-бот.\nВыбери, что хочешь получить:",
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
                [InlineKeyboardButton("💬 Написать Лере", url=DIAGNOSTIC_LINK)]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "🌸 Супер! Подписка подтверждена. Теперь ты можешь пользоваться всеми материалами.\n\nВыбери, что хочешь получить:",
                reply_markup=reply_markup
            )
        else:
            keyboard = [
                [InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")],
                [InlineKeyboardButton("✅ Проверить подписку", callback_data="check_sub")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "💔 Ты ещё не подписалась на канал. Это важно, потому что именно там я делюсь всеми новыми материалами и анонсами.\n\n"
                "Пожалуйста, подпишись и нажми «Проверить подписку» снова.",
                reply_markup=reply_markup
            )
        return

    if not await is_subscribed(context.bot, user_id):
        await query.edit_message_text("⚠️ Вы отписались от канала. Подпишитесь, чтобы продолжить.")
        keyboard = [[InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Подпишитесь и нажмите «Проверить подписку».", reply_markup=reply_markup)
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
        await query.edit_message_text("Неизвестная команда.")

# --- Чек-лист ---
async def send_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    try:
        with open(CHECKLIST_PDF, 'rb') as f:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=f,
                filename="checklist_spasatel.pdf",
                caption="Вот обещанный чек-лист «10 неочевидных признаков, что вы играете роль Спасателя» 👇"
            )
        update_user(user_id, checklist_sent_time=datetime.now())
        text = (
            "Сколько пунктов совпало? Если больше трёх — приглашаю вас разобраться с этим глубже в моём бесплатном челлендже \"5 дней ясности\".\n"
            "Там мы шаг за шагом выходим из роли Спасателя и начинаем жить для себя."
        )
        keyboard = [[InlineKeyboardButton("🗓 Начать челлендж", callback_data="start_challenge_from_checklist")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        schedule_message(update.effective_chat.id, text, 3600, reply_markup)
        if query:
            await query.edit_message_text("Чек-лист отправлен! Через час я напомню вам о челлендже.")
    except FileNotFoundError:
        await query.edit_message_text("❌ Файл временно недоступен. Попробуйте позже.")

# --- Запуск челленджа ---
async def handle_challenge_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        create_user(user_id)
        user = get_user(user_id)

    if not await is_subscribed(context.bot, user_id):
        await query.edit_message_text("⚠️ Вы не подписаны на канал. Подпишитесь, чтобы начать челлендж.")
        keyboard = [[InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Подпишитесь и нажмите «Проверить подписку».", reply_markup=reply_markup)
        return

    if user['challenge_started']:
        await query.edit_message_text(
            "Вы уже участвуете или прошли челлендж. Если вы потеряли расписание, дождитесь следующего сообщения или напишите Лере @valeriasereda."
        )
        return

    update_user(user_id, challenge_started=1, score=0, track=0, current_day=0, start_time=datetime.now(), finished=0)
    await query.edit_message_text("Отлично! Давайте начнём с теста «Индекс потери себя». Ответьте честно – это поможет подобрать подходящий трек.")
    await send_question(update, context, question_index=0)

# --- Вопросы теста ---
questions = [
    {
        "text": "Когда в последний раз вы делали что-то только для себя, без оглядки на других?",
        "options": [
            ("На этой неделе", 1),
            ("В прошлом месяце", 2),
            ("Даже не помню, когда такое было", 3)
        ]
    },
    {
        "text": "Окружающие чаще всего говорят вам:",
        "options": [
            ("«Ты всегда знаешь, чего хочешь»", 1),
            ("«На тебя можно положиться»", 2),
            ("«Как ты всё успеваешь?»", 3)
        ]
    },
    {
        "text": "Если вам нужна помощь, вы:",
        "options": [
            ("Просите и не чувствуете вины", 1),
            ("Просите, но долго переживаете", 2),
            ("Никогда не просите, справляетесь сами", 3)
        ]
    },
    {
        "text": "Ваше тело чаще всего:",
        "options": [
            ("Полно энергии, высыпаетесь", 1),
            ("Бывает напряжение в шее/плечах, но терпимо", 2),
            ("Постоянная усталость, головные боли, ком в горле", 3)
        ]
    },
    {
        "text": "Когда вас хвалят за достижения, вы внутри:",
        "options": [
            ("Чувствуете гордость", 1),
            ("Думаете: «Ой, да это просто повезло»", 2),
            ("Ощущаете пустоту или страх, что разоблачат", 3)
        ]
    },
    {
        "text": "Представьте, что завтра вы исчезнете из всех своих ролей (работа, семья). Что вы почувствуете в первую секунду?",
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
    if update.callback_query:
        await update.callback_query.message.reply_text(
            f"Вопрос {question_index+1}/6:\n\n{q['text']}",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            f"Вопрос {question_index+1}/6:\n\n{q['text']}",
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
        await query.edit_message_text("⚠️ Вы отписались от канала. Подпишитесь, чтобы продолжить тест.")
        keyboard = [[InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Подпишитесь и нажмите «Проверить подписку».", reply_markup=reply_markup)
        return

    new_score = user['score'] + points
    update_user(user_id, score=new_score)

    if q_idx + 1 < len(questions):
        await query.edit_message_text(f"✅ Выбрано: {questions[q_idx]['options'][int(opt_idx)][0]}")
        await send_question(update, context, q_idx + 1)
    else:
        await query.edit_message_text(f"✅ Выбрано: {questions[q_idx]['options'][int(opt_idx)][0]}\n\nТест завершён!")
        await process_test_result(update, context)

async def process_test_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    score = user['score']

    if 6 <= score <= 9:
        track = 1
        track_desc = (
            "🌿 Вы в контакте с собой\n"
            "Вы умеете слышать свои желания и ставить границы. Мой челлендж поможет вам укрепить эту опору и не скатиться обратно в роль «удобной»."
        )
    elif 10 <= score <= 14:
        track = 2
        track_desc = (
            "⚖️ На грани потери\n"
            "Вы ещё помните себя настоящую, но всё чаще выбираете «надо» вместо «хочу». Ваше тело уже подаёт сигналы. Пора остановиться и посмотреть, куда утекает ваша энергия."
        )
    else:  # 15-18
        track = 3
        track_desc = (
            "🕯️ Вы забыли о себе\n"
            "Вы живёте в режиме функции. Достижения не радуют, а внутри — пустота и усталость. Хорошая новость: вы не сломались, вы просто слишком долго обслуживали чужие сценарии. Челлендж станет вашим первым шагом обратно к себе."
        )

    update_user(user_id, track=track, current_day=1, start_time=datetime.now())
    await update.effective_chat.send_message(
        f"Ваш результат: {score} баллов.\n\n{track_desc}\n\nТеперь начинаем челлендж! Сегодня – день 1."
    )
    await send_morning_task(update, context, track, 1)

# ===== Тексты утренних заданий (полные) =====
MORNING_TEXTS = {
    (1,1): "☀️ День 1. Мои точки опоры\n\nСегодня мы не будем искать проблемы. Мы будем искать то, что вас держит.\n\nЗадание:\n- Возьмите лист бумаги или заметки в телефоне.\n- Напишите 5 вещей, занятий, моментов, которые возвращают вам ощущение «я». Это может быть что угодно: утренний кофе в одиночестве, пробежка, звонок подруге, с которой можно молчать, работа над конкретной задачей, запах книги.\n- Напротив каждого пункта напишите, когда в последний раз вы это делали.\n- Выберите один пункт и встройте его в своё расписание на завтра. Прямо сейчас решите, во сколько и как.\n\nВечером вы получите голосовое сообщение. А пока дышите глубже. Вы в порядке.",
    (1,2): "☀️ День 2. Границы как забота\n\nУмение говорить «нет» — это не про жесткость. Это про заботу о себе.\n\nЗадание:\n- Вспомните одну недавнюю ситуацию, где вы сказали «да», но внутри чувствовали «нет». Или где вы хотели отказаться, но не смогли.\n- Напишите, что именно вы чувствовали в тот момент: вину, страх обидеть, желание быть хорошей?\n- Теперь перепишите эту ситуацию. Напишите идеальный сценарий вашего «нет» — без оправданий, но уважительно.\n- Прочитайте написанное вслух. Как ощущения?\n\nЭто упражнение — репетиция. В следующий раз мозгу будет легче.",
    (1,3): "☀️ День 3. Тело как союзник\n\nТело — не инструмент для достижений. Оно — ваш дом.\n\nЗадание:\n- Сядьте удобно, закройте глаза. Сделайте три глубоких вдоха.\n- Пройдите вниманием от макушки до пальцев ног. Где сейчас живёт тепло, лёгкость, а где — напряжение, тяжесть?\n- Откройте глаза и запишите:\n    - Точка напряжения: где она? На что похожа?\n    - Точка ресурса: где в теле вам сейчас хорошо, спокойно?\n- Задайте вопрос точке напряжения: «Что ты хочешь мне сказать?». Запишите первую пришедшую мысль, даже если она кажется странной.\n\nВаше тело всегда на вашей стороне. Учитесь его слышать.",
    (1,4): "☀️ День 4. Спасатель vs Поддержка\n\nПомогать можно по-разному: из любви или из страха быть ненужной.\n\nЗадание:\n- Вспомните одну ситуацию за последние дни, где вы кому-то помогли.\n- Ответьте честно:\n    - Кому принадлежала проблема изначально?\n    - Вас просили о помощи или вы предложили сами?\n    - Что вы чувствовали в процессе: энергию и тепло или усталость и раздражение?\n    - Если бы вы не помогли, что бы случилось с вами? (Стыд? Вина? Страх, что вас разлюбят?)\n- Если помощь больше напоминала спасение — просто заметьте это. Не ругайте себя. Вы это увидели, а значит — уже начали выходить из роли.",
    (1,5): "☀️ День 5. Мой следующий шаг\n\nВы умеете слышать себя. Теперь — усилить.\n\nЗадание:\n- Посмотрите на записи за эти дни. Что стало самым важным открытием?\n- Напишите одно действие, которое расширит вашу «зону авторства» в ближайшую неделю. Это может быть: сказать честно о своей усталости, отказаться от задачи, которую вы обычно берёте «потому что надо», выделить час в день только для себя и никому не отчитываться.\n- Запишите это действие в календарь. Сделайте его неотменяемым.",
    (2,1): "☀️ День 1. Детектор утечки энергии\n\nВы устаёте не от дел. Вы устаёте от ролей, которые не ваши.\n\nЗадание:\n- Нарисуйте таблицу из 4 столбцов:\n    - Роль (сотрудница, жена, дочь, подруга, перфекционистка…)\n    - Энергия ЗАБИРАЕТ (1–10)\n    - Энергия ПРИНОСИТ (1–10)\n    - Разница (Приносит – Забирает)\n- Заполните. Будьте честны. Роль «хорошая мать» может забирать 8, а приносить 3 — и это нормально заметить.\n- Посмотрите на роли с отрицательной разницей. Выберите одну, которая истощает вас сильнее всего. Завтра мы продолжим.\n\nВы не плохая. Вы просто слишком долго раздаёте то, что не восполняется.",
    (2,2): "☀️ День 2. Чей это голос?\n\nМногие цели — не наши. Мы просто взяли их напрокат у родителей, начальников, общества.\n\nЗадание:\n- Выпишите 3 главные цели на этот год (карьера, деньги, статус).\n- Для каждой ответьте:\n    - Кто первым сказал, что это важно? (Мама? Партнёр? Коллеги?)\n    - Если бы НИКТО никогда не узнал о моём результате, мне всё ещё было бы это важно?\n    - Какой процент этого желания — попытка доказать что-то другим? (0–100%)\n- Посмотрите на проценты. Если больше 60% — скорее всего, цель не ваша. Если ответ «нет» — цель точно навязана.\n\nЭто может быть больно. Но это правда, которая освобождает. Я тоже через это прошла.",
    (2,3): "☀️ День 3. Тело не врёт\n\nПока голова думает, что всё нормально, тело уже кричит.\n\nЗадание:\n- Сядьте тихо. Закройте глаза. Спросите: «Где сейчас живёт моя усталость?»\n- Запишите все сигналы тела за последний месяц: напряжение в шее/плечах, ком в горле, бессонница, головные боли, проблемы с желудком.\n- Рядом с каждым сигналом напишите: «Что я делала в момент, когда это появилось? Что я чувствовала, но не выразила?»\n\nТело — ваш главный свидетель. Оно не врёт. Верните ему право голоса.",
    (2,4): "☀️ День 4. Маска спасателя\n\nСпасательство — это часто не доброта, а способ контролировать и чувствовать себя нужной.\n\nЗадание:\n- Вспомните одну конкретную ситуацию за последнюю неделю, где вы кого-то «спасали» (решали чужую проблему, брали на себя чужую ответственность).\n- Нарисуйте треугольник и поставьте себя в одну из ролей: Жертва, Спасатель, Преследователь.\n- Ответьте:\n    - Что я чувствовала ДО того, как начала спасать?\n    - Что я чувствовала В ПРОЦЕССЕ?\n    - Что я получила в итоге? (Благодарность? Ощущение контроля? Пустоту?)\n- Что будет, если в следующий раз вы не войдёте в эту роль? Страх, который возникнет — это и есть ваш ключ к выходу.",
    (2,5): "☀️ День 5. Один шаг к себе\n\nОсознание — это половина. Теперь — действие.\n\nЗадание:\n- Вернитесь к Дню 1. Посмотрите на роль, которая истощает вас сильнее всего.\n- Как вы можете «сыграть» её на 30% меньше?\n    - Не отвечать на рабочие сообщения после 20:00.\n    - Не быть жилеткой для подруги, если у самой нет сил.\n    - Сказать домашним: «Сегодня я готовлю только для себя».\n- Выберите одно маленькое действие и сделайте его в ближайшие 48 часов.",
    (3,1): "🕯️ День 1. Стоп-кран\n\nНикаких планов, никаких «надо». Сегодня мы просто останавливаемся.\n\nЗадание:\n- Найдите 15 минут тишины. Без телефона, без людей, без задач.\n- Сядьте или лягте удобно. Положите руку на грудь.\n- Задайте себе вопрос: «Что я сейчас чувствую на самом деле?»\n    - Не «что я должна чувствовать».\n    - Не «что от меня ждут».\n    - А просто — что внутри. Пустота? Грусть? Облегчение? Злость?\n- Запишите первое, что пришло. Даже если это «ничего». Это тоже ответ.\n\nСегодня не надо ничего решать. Просто разрешите себе быть.",
    (3,2): "🕯️ День 2. Моё тело говорит\n\nКогда вы забыли о себе, тело помнит всё.\n\nЗадание:\n- В течение дня делайте паузы. Каждые 2–3 часа спрашивайте: «Что сейчас чувствует моё тело?»\n- Запишите 3–5 сигналов, которые повторяются: усталость, боль, напряжение, пустота в груди.\n- Вечером возьмите записи и допишите рядом с каждым сигналом: «Это может говорить о том, что я…»\n\nНичего не исправляйте. Просто признайте: ваше тело говорило с вами всё это время.",
    (3,3): "🕯️ День 3. Чужие сценарии\n\nНекоторые правила мы выучили так давно, что считаем их своими.\n\nЗадание:\n- Вспомните фразы, которые вы часто слышали в детстве. От родителей, учителей, значимых взрослых. Например: «Ты должна быть сильной», «Не плачь, это стыдно», «Что люди подумают?», «Ты же девочка, будь удобной».\n- Выпишите 5 таких фраз.\n- Рядом с каждой напишите: «Так было тогда. Но сейчас я взрослая. И я могу…» и закончите по-новому.\n\nЭто не предательство. Это взросление.",
    (3,4): "🕯️ День 4. Я имею право\n\nСегодня мы будем возвращать себе то, что у вас когда-то отобрали.\n\nЗадание:\n- Напишите список из 10–15 пунктов, который начинается словами «Я имею право…». Например:\n    - Я имею право уставать.\n    - Я имею право просить о помощи.\n    - Я имею право злиться.\n    - Я имею право не справляться.\n    - Я имею право быть неудобной.\n    - Я имею право на отдых без чувства вины.\n- Прочитайте список вслух. Медленно. Пункт за пунктом.\n- Выберите один пункт, который труднее всего принять. Напишите его на листочке и повесьте на видное место.\n\nЭто не бунт. Это возвращение к себе.",
    (3,5): "🕯️ День 5. Первый контакт с желанием\n\nВы долго обслуживали чужие сценарии. Сегодня — только вы.\n\nЗадание:\n- Подумайте: что бы вы сделали сегодня, если бы никто не ждал от вас результата? Не «что полезно», а «что приятно».\n- Выберите одно микро-действие. Очень маленькое. Без цели и смысла. Просто для удовольствия: съесть любимое пирожное, не думая о калориях; включить музыку и танцевать; купить себе цветок; лечь в кровать в 19:00 и смотреть глупый сериал.\n- Сделайте это. И не объясняйте никому."
}

# --- Отправка утренних заданий ---
async def send_morning_task(update: Update, context: ContextTypes.DEFAULT_TYPE, track: int, day: int):
    user_id = update.effective_chat.id
    if not await is_subscribed(context.bot, user_id):
        keyboard = [[InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Вы отписались от канала. Чтобы получать задания челленджа, подпишитесь снова.",
            reply_markup=reply_markup
        )
        return

    text = MORNING_TEXTS.get((track, day), "Утреннее задание для этого дня ещё не подготовлено.")
    await context.bot.send_message(chat_id=user_id, text=text)

    evening_delay = 8 * 3600
    audio_path = AUDIO_FILES[f"track{track}"][f"day{day}_evening"]
    scheduler.add_job(
        send_evening_audio,
        trigger=DateTrigger(run_date=datetime.now() + timedelta(seconds=evening_delay)),
        args=[user_id, audio_path, track, day]
    )

async def send_evening_audio(chat_id, audio_path, track, day):
    try:
        bot = application.bot
        if not await is_subscribed(bot, chat_id):
            keyboard = [[InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await bot.send_message(
                chat_id=chat_id,
                text="❌ Вы отписались от канала. Чтобы получить вечернее голосовое сообщение, подпишитесь снова.",
                reply_markup=reply_markup
            )
            return

        with open(audio_path, 'rb') as f:
            await bot.send_voice(chat_id=chat_id, voice=f, caption="🌙 Ваше вечернее голосовое сообщение.")
        if day == 5:
            await send_final_invitation(chat_id)
        else:
            next_morning_delay = 16 * 3600
            if day < 5:
                scheduler.add_job(
                    send_morning_task_by_chat,
                    trigger=DateTrigger(run_date=datetime.now() + timedelta(seconds=next_morning_delay)),
                    args=[chat_id, track, day+1]
                )
    except Exception as e:
        logging.error(f"Ошибка отправки аудио: {e}")

async def send_morning_task_by_chat(chat_id, track, day):
    bot = application.bot
    if not await is_subscribed(bot, chat_id):
        keyboard = [[InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await bot.send_message(
            chat_id=chat_id,
            text="❌ Вы отписались от канала. Чтобы получить задания, подпишитесь снова.",
            reply_markup=reply_markup
        )
        return

    text = MORNING_TEXTS.get((track, day), "Утреннее задание для этого дня ещё не подготовлено.")
    await bot.send_message(chat_id=chat_id, text=text)

    evening_delay = 8 * 3600
    audio_path = AUDIO_FILES[f"track{track}"][f"day{day}_evening"]
    scheduler.add_job(
        send_evening_audio,
        trigger=DateTrigger(run_date=datetime.now() + timedelta(seconds=evening_delay)),
        args=[chat_id, audio_path, track, day]
    )

async def send_final_invitation(chat_id):
    bot = application.bot
    if not await is_subscribed(bot, chat_id):
        keyboard = [[InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await bot.send_message(
            chat_id=chat_id,
            text="❌ Вы отписались от канала. Чтобы получить финальное приглашение, подпишитесь.",
            reply_markup=reply_markup
        )
        return
    text = (
        "🌟 Вы прошли челлендж «5 дней ясности»!\n\n"
        "Если вы чувствуете, что хотите разобрать именно вашу ситуацию лично — приглашаю на сессию «Разворот».\n"
        "За 1,5 часа мы составим ваш индивидуальный маршрут.\n\n"
        "Напишите мне слово «РАЗВОРОТ» и узнайте детали. Это бесплатно и ни к чему вас не обязывает."
    )
    keyboard = [[InlineKeyboardButton("💬 Написать мне", url=DIAGNOSTIC_LINK)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)

# ================== ЗАПУСК ==================
def main():
    init_db()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.run_polling()

if __name__ == "__main__":
    main()
