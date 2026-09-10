import os
import asyncio
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from google import genai


# ==========================================
# 1. Логирование
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


# ==========================================
# 2. Переменные окружения
# ==========================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_KEY")

if not TELEGRAM_TOKEN:
    raise RuntimeError(
        "Не найдена переменная окружения TELEGRAM_TOKEN. "
        "Добавь её в Render → Environment."
    )

if not GEMINI_KEY:
    raise RuntimeError(
        "Не найдена переменная окружения GEMINI_KEY. "
        "Добавь её в Render → Environment."
    )


# ==========================================
# 3. Health Check сервер для Render Web Service
# ==========================================

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        logger.info(
            "Health check: %s - %s",
            self.address_string(),
            format % args,
        )


def run_health_server():
    port_value = os.getenv("PORT", "10000")

    try:
        port = int(port_value)
    except ValueError:
        raise RuntimeError(
            f"Переменная PORT имеет неправильное значение: {port_value}"
        )

    server_address = ("0.0.0.0", port)
    server = HTTPServer(server_address, HealthCheckHandler)

    logger.info(
        "Health Check сервер запущен на 0.0.0.0:%s",
        port,
    )

    try:
        server.serve_forever()
    except Exception:
        logger.exception("Ошибка Health Check сервера")
    finally:
        server.server_close()
        logger.info("Health Check сервер остановлен")


def start_health_server():
    thread = Thread(
        target=run_health_server,
        name="health-check-server",
        daemon=True,
    )
    thread.start()
    return thread


# ==========================================
# 4. Разделение длинного текста
# ==========================================

def split_text(text: str, max_size: int = 4000) -> list[str]:
    if not text:
        return []

    if len(text) <= max_size:
        return [text]

    chunks = []
    current_chunk = ""

    for line in text.split("\n"):
        if len(line) > max_size:
            words = line.split()

            for word in words:
                if len(word) > max_size:
                    if current_chunk.strip():
                        chunks.append(current_chunk.strip())
                        current_chunk = ""

                    for start in range(0, len(word), max_size):
                        chunks.append(word[start:start + max_size])

                elif len(current_chunk) + len(word) + 1 > max_size:
                    if current_chunk.strip():
                        chunks.append(current_chunk.strip())

                    current_chunk = word + " "
                else:
                    current_chunk += word + " "

        elif len(current_chunk) + len(line) + 1 > max_size:
            if current_chunk.strip():
                chunks.append(current_chunk.strip())

            current_chunk = line + "\n"

        else:
            current_chunk += line + "\n"

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


# ==========================================
# 5. FSM регистрации
# ==========================================

class RegistrationState(StatesGroup):
    waiting_for_name = State()
    waiting_for_birthdate = State()


# ==========================================
# 6. Инициализация Telegram и Gemini
# ==========================================

storage = MemoryStorage()
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=storage)
ai_client = genai.Client(api_key=GEMINI_KEY)


SYUTSAI_SYSTEM_INSTRUCTION = """
Ты — помощник, который отвечает только на русском языке
и только в рамках методологии СЮЦАЙ.

Используй только знания, принципы и понятия методологии СЮЦАЙ.
Не добавляй сведения из других методов, медицинских систем,
психологии, астрологии или личные догадки.

Если вопрос не относится к СЮЦАЙ или в доступных знаниях
нет точного ответа, напиши:

«Этот вопрос выходит за рамки методологии СЮЦАЙ, поэтому я не могу
ответить на него в рамках своей специализации».

Не выдумывай факты.
Не ставь диагнозы.
Не обещай лечение.
Не советуй отменять назначенное врачом лечение.
"""


# ==========================================
# 7. Регистрация пользователя
# ==========================================

@dp.message(CommandStart())
@dp.message(Command("reset"))
async def cmd_start(
    message: types.Message,
    state: FSMContext,
):
    await state.clear()
    await state.set_state(RegistrationState.waiting_for_name)

    await message.answer(
        "Здравствуйте! Чтобы начать консультацию "
        "в рамках методологии Сюцай, представьтесь, пожалуйста.\n\n"
        "Как вас зовут?"
    )


@dp.message(RegistrationState.waiting_for_name, F.text)
async def process_name(
    message: types.Message,
    state: FSMContext,
):
    user_name = message.text.strip()

    if not user_name:
        await message.answer("Пожалуйста, напишите ваше имя.")
        return

    await state.update_data(user_name=user_name)
    await state.set_state(RegistrationState.waiting_for_birthdate)

    await message.answer(
        f"Приятно познакомиться, {user_name}!\n\n"
        "Теперь укажите вашу полную дату рождения "
        "в формате ДД.ММ.ГГГГ.\n\n"
        "Например: 26.09.1981"
    )


@dp.message(RegistrationState.waiting_for_birthdate, F.text)
async def process_birthdate(
    message: types.Message,
    state: FSMContext,
):
    birthdate = message.text.strip()

    if not birthdate:
        await message.answer(
            "Пожалуйста, укажите дату рождения "
            "в формате ДД.ММ.ГГГГ."
        )
        return

    await state.update_data(birthdate=birthdate)

    user_data = await state.get_data()
    name = user_data.get("user_name", "не указано")

    await state.set_state(None)

    await message.answer(
        f"Данные сохранены!\n"
        f"Имя: {name}\n"
        f"Дата рождения: {birthdate}\n\n"
        "Теперь вы можете задать любой вопрос "
        "по методологии Сюцай.\n\n"
        "Если захотите сменить данные, отправьте команду /reset."
    )


# ==========================================
# 8. Запрос к Gemini
# ==========================================

@dp.message(F.text)
async def handle_ai_message(
    message: types.Message,
    state: FSMContext,
):
    user_data = await state.get_data()

    name = user_data.get("user_name")
    birthdate = user_data.get("birthdate")

    if not name or not birthdate:
        await state.set_state(RegistrationState.waiting_for_name)

        await message.answer(
            "Для консультации мне нужны ваши данные.\n\n"
            "Пожалуйста, напишите, как вас зовут?"
        )
        return

    await bot.send_chat_action(
        chat_id=message.chat.id,
        action="typing",
    )

    prompt_with_context = (
        f"Данные пользователя:\n"
        f"Имя: {name}\n"
        f"Дата рождения: {birthdate}\n\n"
        f"Вопрос пользователя:\n"
        f"{message.text}"
    )

    try:
        response = await asyncio.to_thread(
            ai_client.models.generate_content,
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=prompt_with_context,
            config={
                "system_instruction": SYUTSAI_SYSTEM_INSTRUCTION,
            },
        )

        reply_text = getattr(response, "text", None)

        if not reply_text:
            reply_text = "ИИ вернул пустой ответ."

        messages_to_send = split_text(reply_text)

        for chunk in messages_to_send:
            await message.answer(chunk)
            await asyncio.sleep(0.2)

    except Exception:
        logger.exception("Ошибка при обращении к Gemini")

        await message.answer(
            "Произошла ошибка при обращении к ИИ. "
            "Попробуйте повторить запрос немного позже."
        )


# ==========================================
# 9. Запуск бота
# ==========================================

async def main():
    logger.info("Запуск Telegram-бота через polling")

    await bot.delete_webhook(drop_pending_updates=True)

    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            handle_signals=False,
        )
    finally:
        await bot.session.close()
        logger.info("Telegram-бот остановлен")


if __name__ == "__main__":
    start_health_server()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную")
