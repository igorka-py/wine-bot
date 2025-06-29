import asyncio
import json
import random
import os
from enum import Enum, auto
from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv

from aiohttp import web
import aisqlite 
from pathlib import Path



# --- Класс для типов вопросов, пока не используется для JSON ---
class QuestionType(Enum):
    SPOILER = auto()
    QUIZ = auto()

# --- Загрузка вопросов из файла с обработкой ошибок ---
try:
    with open("questions.json", "r", encoding="utf-8") as file:
        QUESTIONS = json.load(file)
    if not QUESTIONS:
        raise ValueError("Файл questions.json пуст!")
except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
    print(f"Ошибка загрузки вопросов: {e}")
    QUESTIONS = []

load_dotenv()
API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# --- FSM: определение состояний викторины ---
class QuizStates(StatesGroup):
    in_quiz = State()

async def start_web_server():
    app = web.Application()
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, port=port)
    await site.start()
    print(f"веб сервер запущен на порту'{port}")


# --- Функция показа вопроса ---
async def ask_question(chat_id: int, state: FSMContext):
    if not QUESTIONS:
        await bot.send_message(chat_id, "❌ Вопросы не загружены. Обратитесь к администратору.")
        return

    # Получаем из состояния очередь вопросов, либо создаём новую случайным образом
    data = await state.get_data()
    question_queue = data.get("question_queue", random.sample(QUESTIONS, len(QUESTIONS)))

    # Если очередь пуста — начинаем новый круг вопросов
    if not question_queue:
        question_queue = random.sample(QUESTIONS, len(QUESTIONS))
        await bot.send_message(chat_id, "🔁 Все вопросы пройдены! Начинаем новый раунд.")

    # Берём следующий вопрос из начала списка (чтобы порядок был стабильнее)
    question = question_queue.pop(0)
    await state.update_data(current_question=question, question_queue=question_queue)

    progress = f"[{len(QUESTIONS) - len(question_queue)}/{len(QUESTIONS)}]"

    q_type = question.get("type")
    if q_type == "spoiler":
        # Вопрос с "спойлером" — сначала без ответа, есть кнопка "Показать ответ"
        await bot.send_message(
            chat_id,
            f"{progress} ❓ {question['question']}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Показать ответ 👀", callback_data="reveal_answer")]
            ])
        )
    elif q_type == "quiz":
        # Вопрос с вариантами ответа — создаём кнопки под ними
        buttons = [
            [InlineKeyboardButton(text=opt, callback_data=f"answer_{i}")]
            for i, opt in enumerate(question.get("options", []))
        ]
        await bot.send_message(
            chat_id,
            f"{progress} ❓ {question['question']}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
    else:
        # Если тип вопроса неизвестен — предупреждаем пользователя
        await bot.send_message(chat_id, "❗️ Тип вопроса не распознан.")

# --- Обработчик команды /start ---
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    if not QUESTIONS:
        await message.answer("Вопросы не загружены")
        return
    
    await state.set_state(QuizStates.in_quiz)
    await message.answer(
        "🍷 Добро пожаловать в викторину о винах!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Начать", callback_data="start_quiz")]
        ])
    )

# --- Запуск викторины по кнопке ---
@dp.callback_query(F.data == "start_quiz")
async def start_quiz(callback: CallbackQuery, state: FSMContext):
    await ask_question(callback.message.chat.id, state)
    await callback.answer

# --- Показ ответа (спойлер) ---
@dp.callback_query(F.data == "reveal_answer")
async def reveal_answer(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    question = data.get("current_question", {})

    if not question:
        await callback.answer("Ошибка: вопрос не найден.", show_alert=True)
        return

    await callback.message.edit_text(
        f"❓ {question.get('question', '')}\n\nОтвет: <tg-spoiler>{question.get('answer', '')}</tg-spoiler>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Следующий вопрос ➡️", callback_data="next_question")]
        ])
    )
    await callback.answer()

# --- Переход к следующему вопросу ---
@dp.callback_query(F.data == "next_question")
async def next_question(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_reply_markup(reply_markup=None)  # Убираем кнопки старого вопроса
    await ask_question(callback.message.chat.id, state)
    await callback.answer()

# --- Обработка ответов на викторину ---
@dp.callback_query(F.data.startswith("answer_"))
async def answer_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    question = data.get("current_question", {})

    if not question:
        await callback.answer("Ошибка: вопрос не найден.", show_alert=True)
        return

    try:
        selected_index = int(callback.data.split("_")[1])
        correct_index = question.get("correct_index", -1)

        if selected_index == correct_index:
            await callback.answer("✅ Верно!", show_alert=True)
        else:
            correct_answer = question.get("options", [])[correct_index]
            await callback.answer(f"❌ Неправильно! Правильно: {correct_answer}", show_alert=True)

        await callback.message.edit_reply_markup(reply_markup=None)
        await ask_question(callback.message.chat.id, state)
    except (IndexError, ValueError):
        await callback.answer("Ошибка обработки ответа.", show_alert=True)

# --- Запуск бота ---
async def main():
    if not QUESTIONS:
        print("ОШИБКА: Не удалось загрузить вопросы.")
        return
    
    await start_web_server()
    print ("бот пашет как лошадка в поле!")
    await dp.start_polling(bot)
if __name__ == "__main__":
    asyncio.run(main())
