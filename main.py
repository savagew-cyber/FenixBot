import os
import threading
import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from google import genai

# ==========================================
# 1. Health Check Сервер (для Render/Railway)
# ==========================================

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()


# ==========================================
# 2. Нарезка длинного текста под лимит 4000 знаков
# ==========================================

def split_text(text: str, max_size: int = 4000) -> list[str]:
    if not text:
        return []
    if len(text) <= max_size:
        return [text]

    chunks = []
    lines = text.split("\n")
    current_chunk = ""

    for line in lines:
        if len(line) > max_size:
            words = line.split(" ")
            for word in words:
                if len(current_chunk) + len(word) + 1 > max_size:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = word + " "
                else:
                    current_chunk += word + " "
        elif len(current_chunk) + len(line) + 1 > max_size:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


# ==========================================
# 3. Настройка FSM (Состояния анкеты)
# ==========================================

class RegistrationState(StatesGroup):
    waiting_for_name = State()
    waiting_for_birthdate = State()


# ==========================================
# 4. Инициализация клиентов и Сценарий СЮЦАЙ
# ==========================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

storage = MemoryStorage()
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=storage)
ai_client = genai.Client(api_key=GEMINI_KEY)

SYUTSAI_SYSTEM_INSTRUCTION = """
Ты — помощник, который отвечает только на русском языке и только в рамках методологии СЮЦАЙ.

Используй только знания, принципы и понятия методологии СЮЦАЙ. Не добавляй сведения из других методов, медицинских систем, психологии, астрологии или личные догадки.

Если вопрос не относится к СЮЦАЙ или в доступных знаниях нет точного ответа, напиши:
«Этот вопрос выходит за рамки методологии СЮЦАЙ, поэтому я не могу ответить на него в рамках своей специализации».

Не выдумывай факты. Не ставь диагнозы, не обещай лечение и не советуй отменять назначенное врачом лечение.
"""


# ==========================================
# 5. Обработка регистрации (Имя и Дата рождения)
# ==========================================

@dp.message(CommandStart())
@dp.message(Command("reset"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(RegistrationState.waiting_for_name)
    await message.answer(
        "Здравствуйте! Чтобы начать консультацию в рамках методологии Сюцай, представьтесь, пожалуйста.\n\n"
        "Как вас зовут?"
    )

@dp.message(RegistrationState.waiting_for_name, F.text)
async def process_name(message: types.Message, state: FSMContext):
    user_name = message.text.strip()
    await state.update_data(user_name=user_name)
    await state.set_state(RegistrationState.waiting_for_birthdate)
    await message.answer(
        f"Приятно познакомиться, {user_name}!\n\n"
        "Теперь укажите вашу полную дату рождения в формате ДД.ММ.ГГГГ (например, 26.09.1981):"
    )

@dp.message(RegistrationState.waiting_for_birthdate, F.text)
async def process_birthdate(message: types.Message, state: FSMContext):
    birthdate = message.text.strip()
    await state.update_data(birthdate=birthdate)
    
    user_data = await state.get_data()
    name = user_data.get("user_name")
    
    await state.set_state(None)
    await message.answer(
        f"Данные сохранены!\n"
        f"Имя: {name}\n"
        f"Дата рождения: {birthdate}\n\n"
        "Теперь вы можете задать любой вопрос по методологии Сюцай. "
        "Если захотите сменить данные, отправьте команду /reset."
    )


# ==========================================
# 6. Основной диалог с Gemini 3.6 Flash
# ==========================================

@dp.message(F.text)
async def handle_ai_message(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    name = user_data.get("user_name")
    birthdate = user_data.get("birthdate")

    if not name or not birthdate:
        await state.set_state(RegistrationState.waiting_for_name)
        await message.answer(
            "Для точного расчета по методологии Сюцай мне нужны ваши данные.\n\n"
            "Пожалуйста, напишите, как вас зовут?"
        )
        return

    await bot.send_chat_action(message.chat.id, "typing")
    try:
        prompt_with_context = (
            f"Данные пользователя:\n"
            f"Имя: {name}\n"
            f"Дата рождения: {birthdate}\n\n"
            f"Вопрос пользователя: {message.text}"
        )

        response = ai_client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt_with_context,
            config={
                "system_instruction": SYUTSAI_SYSTEM_INSTRUCTION,
            }
        )

        reply_text = response.text or "ИИ вернул пустой ответ."
        messages_to_send = split_text(reply_text, max_size=4000)

        for chunk in messages_to_send:
            await message.answer(chunk)
            await asyncio.sleep(0.2)

    except Exception as e:
        await message.answer(f"Ошибка ИИ: {e}")


# ==========================================
# 7. Запуск бота
# ==========================================

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
