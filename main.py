import os
import threading
import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler
from aiogram import Bot, Dispatcher, types, F
from google import genai

# ==========================================
# 1. Веб-сервер Health Check для облачного хостинга
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
# 2. Нарезка сообщений под лимит Telegram (4096 символов)
# ==========================================

def split_text(text: str, max_size: int = 4000) -> list[str]:
    """Разбивает текст на блоки не более 4000 символов, не ломая предложения и строки."""
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
# 3. Инициализация клиентов и жесткий сценарий СЮЦАЙ
# ==========================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
ai_client = genai.Client(api_key=GEMINI_KEY)

SYUTSAI_SYSTEM_INSTRUCTION = """
Ты — помощник, который отвечает только на русском языке и только в рамках методологии СЮЦАЙ.

Используй только знания, принципы и понятия методологии СЮЦАЙ. Не добавляй сведения из других методов, медицинских систем, психологии, астрологии или личные догадки.

Если вопрос не относится к СЮЦАЙ или в доступных знаниях нет точного ответа, напиши:
«Этот вопрос выходит за рамки методологии СЮЦАЙ, поэтому я не могу ответить на него в рамках своей специализации».

Не выдумывай факты. Не ставь диагнозы, не обещай лечение и не советуй отменять назначенное врачом лечение.
"""


# ==========================================
# 4. Обработка входящих сообщений
# ==========================================

@dp.message(F.text)
async def handle_message(message: types.Message):
    await bot.send_chat_action(message.chat.id, "typing")
    try:
        response = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=message.text,
            config={
                "system_instruction": SYUTSAI_SYSTEM_INSTRUCTION,
                "temperature": 0.2,
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
# 5. Запуск бота
# ==========================================

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
