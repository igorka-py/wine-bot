import asyncio
import json
import os
import random

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiohttp import web
from dotenv import load_dotenv

# ✅ Новый keep_alive, без threading!
async def keep_alive():
    async def handle(request):
        return web.Response(text="OK")

    app = web.Application()
    app.router.add_get("/", handle)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    print("🌐 Web-сервер запущен на порту 8080")

# --- Загрузка вопросов ---
try:
    with open("questions.json", "r", encoding="utf-8") as file:
        QUESTIONS = json.load(file)
except Exception as e:
    print(f"Ошибка загрузки вопросов: {e}")
    QUESTIONS = []

load_dotenv()
API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# --- FSM ---
class QuizStates(StatesGroup):
    in_quiz = State()

# --- Вопросы ---
async def ask_question(chat_id: int, state: FSMContext):
    data = await state.get_data()
    question_queue = data.get("question_queue", random.sample(QUESTIONS, len(QUESTIONS)))

    if not question_queue:
        question_queue = random.sample(QUESTIONS, len(QUESTIONS))
        await bot.send_message(chat_id, "🔁 Новый раунд!")

    question = question_queue.pop(0)
    await state.update_data(current_question=question, question_queue=question_queue)

    progress = f"[{len(QUESTIONS) - len(question_queue)}/{len(QUESTIONS)}]"

    q_type = question.get("type")
    if q_type == "spoiler":
        await bot.send_message(
            chat_id,
            f"{progress} ❓ {question['question']}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Показать ответ 👀", callback_data="reveal_answer")]
            ])
        )
    elif q_type == "quiz":
        buttons = [[InlineKeyboardButton(text=opt, callback_data=f"answer_{i}")]
                   for i, opt in enumerate(question.get("options", []))]
        await bot.send_message(
            chat_id,
            f"{progress} ❓ {question['question']}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
    else:
        await bot.send_message(chat_id, "❗️ Тип вопроса не распознан.")

# --- Команда /start ---
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.set_state(QuizStates.in_quiz)
    await message.answer(
        "🍷 Добро пожаловать в викторину!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Начать", callback_data="start_quiz")]
        ])
    )

# --- Кнопки ---
@dp.callback_query(F.data == "start_quiz")
async def start_quiz(callback: CallbackQuery, state: FSMContext):
    await ask_question(callback.message.chat.id, state)
    await callback.answer()

@dp.callback_query(F.data == "reveal_answer")
async def reveal_answer(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    question = data.get("current_question", {})
    await callback.message.edit_text(
        f"❓ {question.get('question')}\n\nОтвет: <tg-spoiler>{question.get('answer')}</tg-spoiler>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Следующий ➡️", callback_data="next_question")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data == "next_question")
async def next_question(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_reply_markup(reply_markup=None)
    await ask_question(callback.message.chat.id, state)
    await callback.answer()

@dp.callback_query(F.data.startswith("answer_"))
async def answer_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    question = data.get("current_question", {})
    try:
        selected = int(callback.data.split("_")[1])
        correct = question.get("correct_index", -1)
        if selected == correct:
            await callback.answer("✅ Верно!", show_alert=True)
        else:
            correct_answer = question.get("options", [])[correct]
            await callback.answer(f"❌ Неправильно! Правильно: {correct_answer}", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=None)
        await ask_question(callback.message.chat.id, state)
    except:
        await callback.answer("Ошибка ответа.", show_alert=True)

# --- Главная точка запуска ---
async def main():
    asyncio.create_task(keep_alive())  # ✅ Вот тут запускаем web-сервер
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
