import asyncio
import logging
import os

import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandStart
from aiogram.utils.deep_linking import create_start_link

# --- Конфигурация ---
API_TOKEN = os.getenv('API_TOKEN')
if not API_TOKEN:
    raise ValueError("Не найден API_TOKEN в переменных окружения")

DB_FILE = "referrals.db"
REFERRAL_GOAL = 10

# --- Настройка логирования ---
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# --- Инициализация диспетчера ---
dp = Dispatcher()


# --- Логика базы данных ---
async def init_db():
    """Инициализирует базу данных и создает таблицу, если она не существует."""
    # Примечание: если вы запускали старую версию, удалите файл referrals.db для создания новой структуры.
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                invited_by INTEGER,
                referrals INTEGER DEFAULT 0,
                goal_achieved_notified INTEGER DEFAULT 0
            )
        """)
        await db.commit()
    log.info("База данных инициализирована.")

async def add_user(user_id: int):
    """Добавляет нового пользователя в БД, если его там еще нет."""
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.commit()

async def process_referral(user_id: int, inviter_id: int) -> bool:
    """
    Обрабатывает реферальную ссылку, связывая нового пользователя с пригласившим.
    Возвращает True, если реферал был успешно засчитан.
    """
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT invited_by FROM users WHERE user_id = ?", (user_id,))
        result = await cursor.fetchone()

        if result and result[0] is None and user_id != inviter_id:
            await db.execute("UPDATE users SET invited_by = ? WHERE user_id = ?", (inviter_id, user_id))
            await db.execute("UPDATE users SET referrals = referrals + 1 WHERE user_id = ?", (inviter_id,))
            await db.commit()
            log.info(f"Пользователь {user_id} был приглашен {inviter_id}")
            return True
    return False

async def check_and_notify_on_goal(bot: Bot, inviter_id: int):
    """Проверяет, достиг ли пригласивший цели, и уведомляет его, если это произошло впервые."""
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT referrals, goal_achieved_notified FROM users WHERE user_id = ?", (inviter_id,))
        result = await cursor.fetchone()
        if not result:
            return

        referrals, notified = result
        if referrals >= REFERRAL_GOAL and not notified:
            try:
                await bot.send_message(
                    inviter_id,
                    f"🎉 Поздравляем! Вы достигли цели в {REFERRAL_GOAL} рефералов!\n"
                    f"Вот ваш инсайд: [ТУТ БУДЕТ СТАВКА]"
                )
                await db.execute("UPDATE users SET goal_achieved_notified = 1 WHERE user_id = ?", (inviter_id,))
                await db.commit()
                log.info(f"Пользователь {inviter_id} достиг цели и был уведомлен.")
            except Exception as e:
                log.error(f"Не удалось отправить уведомление пользователю {inviter_id}: {e}")

async def get_user_referrals(user_id: int) -> int:
    """Получает количество рефералов для указанного пользователя."""
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT referrals FROM users WHERE user_id = ?", (user_id,))
        result = await cursor.fetchone()
        return result[0] if result else 0


# --- Обработчики бота ---
@dp.message(CommandStart())
async def handle_start(message: types.Message, bot: Bot):
    """Обрабатывает команду /start, включая реферальную логику."""
    user_id = message.from_user.id
    await add_user(user_id)

    args = message.get_args()
    if args and args.isdigit():
        inviter_id = int(args)
        if inviter_id != user_id:
            await add_user(inviter_id)
            if await process_referral(user_id=user_id, inviter_id=inviter_id):
                # Проверяем, не достиг ли пригласивший цели
                await check_and_notify_on_goal(bot, inviter_id)

    referral_link = await create_start_link(bot, str(user_id), encode=True)

    await message.answer(
        f"👋 Привет! Хочешь получить ЖБ СТАВКУ с кэфом выше 15?\n\n"
        f"❗️Нужно пригласить {REFERRAL_GOAL} человек в этого бота!\n\n"
        f"🔗 Вот твоя реф. ссылка:\n{referral_link}\n\n"
        f"📊 Чтобы узнать сколько уже пригласил, введи /progress"
    )

@dp.message(Command("progress"))
async def handle_progress(message: types.Message):
    user_id = message.from_user.id
    referrals = await get_user_referrals(user_id)

    if referrals >= REFERRAL_GOAL:
        await message.answer(
            f"🎉 Красавец! Ты пригласил {referrals} человек(а)!\n"
            f"Ты уже должен был получить свой приз. Можешь продолжать приглашать друзей!"
        )
    else:
        remaining = REFERRAL_GOAL - referrals
        await message.answer(
            f"👥 Ты пригласил {referrals} человек(а). "
            f"Осталось пригласить еще {remaining} для получения ставки."
        )

# --- Запуск бота ---
async def main():
    """Основная функция для запуска бота."""
    bot = Bot(token=API_TOKEN)
    await init_db()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
