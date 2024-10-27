import os
import requests
import sqlite3
import time
import threading
from dotenv import load_dotenv
import telebot
from telebot import types
import schedule

# Загружаем переменные окружения из файла .env
load_dotenv('/home/admin/tokens.env')

BOT_TOKEN = os.getenv('BOT_TOKEN')  # Замените на ваш токен
WEATHER_API_KEY = os.getenv('WEATHER_API_KEY')

# Проверяем наличие токенов
if BOT_TOKEN is None or WEATHER_API_KEY is None:
    raise ValueError("BOT_TOKEN or WEATHER_API_KEY is not set in the environment variables.")

bot = telebot.TeleBot(BOT_TOKEN)

# Подключение к базе данных
def create_db():
    conn = sqlite3.connect('weather_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            city TEXT,
            interval INTEGER
        )
    ''')
    conn.commit()
    conn.close()

create_db()

# Команда /start
@bot.message_handler(commands=['start'])
def start_bot(message):
    bot.send_message(message.chat.id, "👋 Привет! Я ваш погодный бот! 🌤️\n"
                                      "Введите название города для прогноза погоды. "
                                      "Для остановки рассылки используйте команду /stop или нажмите соответствующую кнопку.")

# Команда /stop для остановки рассылки
@bot.message_handler(commands=['stop'])
def stop_command(message):
    chat_id = message.chat.id
    schedule.clear(chat_id)
    bot.send_message(chat_id, "🚫 Рассылка прогноза погоды остановлена.")

# Обработка простого текста как название города
@bot.message_handler(func=lambda message: True)
def handle_city_input(message):
    city = message.text.strip()
    chat_id = message.chat.id
    save_city(chat_id, city)  # Сохраняем город для пользователя
    send_weather_forecast(chat_id, city)  # Отправляем прогноз погоды и предлагаем выбрать периодичность

# Функция для отправки прогноза погоды и выбора периодичности
def send_weather_forecast(chat_id, city):
    try:
        response = requests.get(f'http://api.weatherapi.com/v1/current.json?key={WEATHER_API_KEY}&q={city}')
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        bot.send_message(chat_id, "❌ Произошла ошибка при запросе к WeatherAPI. Пожалуйста, попробуйте позже.")
        print(f"Ошибка запроса: {e}")
        return

    if response.status_code == 200:
        data = response.json()
        description = data['current']['condition']['text']  # Описание погоды
        temperature = data['current']['temp_c']  # Температура в градусах Цельсия
        humidity = data['current']['humidity']  # Влажность в процентах
        
        # Отправляем информацию о погоде и клавиатуру с интервалами
        weather_message = (f"🌆 Погода в городе {city}:\n"
                           f"☁️ Описание: {description}\n"
                           f"🌡️ Температура: {temperature}°C\n"
                           f"💧 Влажность: {humidity}%\n\n"
                           "Как часто вы хотите получать обновления погоды?")
        bot.send_message(chat_id, weather_message, reply_markup=get_frequency_keyboard())
    else:
        bot.send_message(chat_id, "❌ Город не найден. Пожалуйста, проверьте название и попробуйте снова.")

# Функция для создания клавиатуры с интервалами
def get_frequency_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    minute_1_button = types.InlineKeyboardButton("Каждые 1 минуту", callback_data='1')  # 1 минута
    hour_1_button = types.InlineKeyboardButton("Каждый час", callback_data='60')  # 1 час (60 минут)
    hour_3_button = types.InlineKeyboardButton("Каждые 3 часа", callback_data='180')  # 3 часа (180 минут)
    hour_6_button = types.InlineKeyboardButton("Каждые 6 часов", callback_data='360')  # 6 часов (360 минут)

    keyboard.add(minute_1_button, hour_1_button, hour_3_button, hour_6_button)
    return keyboard

# Функция для сохранения города пользователя
def save_city(chat_id, city):
    conn = sqlite3.connect('weather_bot.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO users (chat_id, city, interval) VALUES (?, ?, ?)", (chat_id, city, None))
    conn.commit()
    conn.close()

# Обработчик выбора интервала
@bot.callback_query_handler(func=lambda call: call.data.isdigit())
def handle_frequency_selection(call):
    chat_id = call.message.chat.id
    interval_minutes = int(call.data)

    # Получаем город из базы данных
    conn = sqlite3.connect('weather_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT city FROM users WHERE chat_id=?", (chat_id,))
    result = cursor.fetchone()

    if result:
        city = result[0]
        # Сохраняем интервал обновлений в базе данных
        cursor.execute("UPDATE users SET interval=? WHERE chat_id=?", (interval_minutes, chat_id))
        conn.commit()
        bot.send_message(chat_id, f"✅ Вы будете получать обновления погоды в городе {city} каждые {interval_minutes} минут(ы)! ⏰")
        # Запускаем обновления
        schedule_updates(chat_id, city, interval_minutes)
    else:
        bot.send_message(chat_id, "❌ Ошибка при сохранении данных. Пожалуйста, попробуйте снова.")
    conn.close()

# Функция планирования обновлений
def schedule_updates(chat_id, city, interval_minutes):
    schedule.clear(chat_id)
    schedule.every(interval_minutes).minutes.do(send_periodic_weather, chat_id, city).tag(chat_id)

# Функция отправки периодического прогноза с кнопкой остановки
def send_periodic_weather(chat_id, city):
    try:
        response = requests.get(f'http://api.weatherapi.com/v1/current.json?key={WEATHER_API_KEY}&q={city}', timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Ошибка запроса: {e}")
        return

    if response.status_code == 200:
        data = response.json()
        description = data['current']['condition']['text']
        temperature = data['current']['temp_c']
        humidity = data['current']['humidity']
        
        # Создаем кнопку для остановки рассылки
        stop_keyboard = types.InlineKeyboardMarkup()
        stop_button = types.InlineKeyboardButton("Остановить рассылку", callback_data=f'stop_{chat_id}')
        stop_keyboard.add(stop_button)
        
        weather_message = (f"🌆 Погода в {city}:\n"
                           f"☁️ Описание: {description}\n"
                           f"🌡️ Температура: {temperature}°C\n"
                           f"💧 Влажность: {humidity}%")
        bot.send_message(chat_id, weather_message, reply_markup=stop_keyboard)
    else:
        print(f"Ошибка API: {response.status_code}")

# Обработчик нажатия на кнопку "Остановить рассылку"
@bot.callback_query_handler(func=lambda call: call.data.startswith("stop_"))
def stop_updates(call):
    chat_id = int(call.data.split("_")[1])
    # Удаляем задачи из расписания для данного пользователя
    schedule.clear(chat_id)
    bot.send_message(chat_id, "🚫 Рассылка прогноза погоды остановлена.")

# Запуск планировщика в отдельном потоке
def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)

# Запуск планировщика
threading.Thread(target=run_scheduler, daemon=True).start()
bot.infinity_polling()
