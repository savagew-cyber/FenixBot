import os
import threading
import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler
from aiogram import Bot, Dispatcher, types, F
from google import genai

# --- 1. Dummy HTTP-сервер для прохождения Health Check (Render/Railway/Koyeb) ---

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


# --- 2. Логика безопасной нарезки текста под лимиты Telegram ---

def split_text(text: str, max_size: int = 4000) -> list[str]:
    """
    Разбивает текст на блоки не более 4000 символов,
    аккуратно сохраняя границы строк и абзацев.
    """
    if not text:
        return []
    if len(text) <= max_size:
        return [text]

    chunks = []
    lines = text.split("\n")
    current_chunk = ""

    for line in lines:
        # Если даже одна строка больше 4000 символов (редкий случай без переносов)
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


# --- 3. Инициализация бота и Google AI ---

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
ai_client = genai.Client(api_key=GEMINI_KEY)


# --- 4. Обработчик сообщений ---

@dp.message(F.text)
async def handle_message(message: types.Message):
    await bot.send_chat_action(message.chat.id, "typing")
    try:
        response = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=message.text,
        )
        
        reply_text = response.text or "ИИ вернул пустой ответ."

        # Режем ответ на фрагменты до 4000 знаков
        messages_to_send = split_text(reply_text, max_size=4000)

        # Отправляем фрагменты по очереди
        for chunk in messages_to_send:
            await message.answer(chunk)
            # Небольшая пауза, чтобы избежать Telegram Flood Wait (429)
            await asyncio.sleep(0.2)

    except Exception as e:
        await message.answer(f"Ошибка ИИ: {e}")


# --- 5. Точка входа ---

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
