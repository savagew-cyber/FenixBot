import os
import asyncio
from aiogram import Bot, Dispatcher, types, F
from openai import AsyncOpenAI

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
AI_API_KEY = os.environ.get("AI_API_KEY")

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# Подключение к OpenRouter
ai_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=AI_API_KEY,
)

@dp.message(F.text)
async def handle_message(message: types.Message):
    await bot.send_chat_action(message.chat.id, "typing")
    try:
        response = await ai_client.chat.completions.create(
            model="deepseek/deepseek-r1:free",
            messages=[
                {"role": "system", "content": "Ты полезный и точный ИИ-ассистент."},
                {"role": "user", "content": message.text}
            ],
            max_tokens=1024,
        )
        await message.answer(response.choices[0].message.content)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
