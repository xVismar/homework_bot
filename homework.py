import json
import logging
import os
import time
from http import HTTPStatus
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv
from telebot import TeleBot
from telebot.apihelper import ApiException
import requests

load_dotenv()

PRACTICUM_TOKEN = os.getenv('YA_TOKEN')
TELEGRAM_TOKEN = os.getenv('TOKEN')
TELEGRAM_CHAT_ID = os.getenv('MASTER_ID')

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}


HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}

if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG,
        filename=os.path.expanduser('~/program.log'),
        format='%(asctime)s, %(levelname)s, %(message)s, %(name)s',
        filemode='w',
        encoding='utf-8'
    )
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(
    'program.log', maxBytes=50000000, backupCount=5)
logger.addHandler(handler)


def check_tokens():
    """Проверяет наличие необходимых пременных окружения."""
    tokens = [PRACTICUM_TOKEN, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]
    for token in tokens:
        if not token:
            logging.critical(f'Отсутствует {token}.')
            return False
    logging.debug('Все токены получены успешно.')
    return all(tokens)


def send_message(bot, message):
    """Отправляет сообщение в Telegram чат."""
    try:
        logging.info('Сообщение отправляется.')
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        logging.debug('Сообщение успешно отправлено.')
    except ApiException as error:
        logging.error(error, exc_info=True)
        logging.debug(f'Сообщение не отправлено - {error}.')


def get_api_answer(timestamp):
    """Делает запрос к API."""
    try:
        if not isinstance(timestamp, int):
            raise TypeError
        payload = {'from_date': timestamp}
        logging.info('Отправляю запрос к API.')
        response = requests.get(
            ENDPOINT, headers=HEADERS, params=payload)
        if response.status_code != HTTPStatus.OK:
            logging.error('API вернул код, отличный от 200.')
            raise requests.exceptions.HTTPError
        return response.json()
    except json.JSONDecodeError as error:
        logging.error(f'Не удалось обработать JSON {error}.')
        return None
    except requests.exceptions.RequestException as error:
        errors = (
            (400, 'некорректный запрос к API'),
            (420, 'слишком много запросов'),
            (500, 'внутренняя ошибка сервера'),
            (403, 'нельзя отправить сообщение'),
        )
        for status, message in errors:
            if error.status_code == status:
                logging.error(f'Ошибка отправки запроса - {message} {status}.')
                raise KeyError
    except Exception:
        raise TypeError


def check_response(response):
    """Проверяет ответ API."""
    if not response:
        logging.error('Нет ответа от сервера.')
        raise Exception
    if not isinstance(response, dict):
        logging.error('Ответ от сервера - не словарь.')
        raise TypeError
    if 'homeworks' not in response:
        logging.error('В ответе API отсутствует ключ - домашние работы.')
        raise KeyError
    if not isinstance(response['homeworks'], list):
        logging.error('В ответе API домашние работы - не список.')
        raise TypeError
    return response['homeworks']


def parse_status(homework):
    """Получения статуса домашней работы."""
    logging.debug('Начинаю парсинг.')
    homework_name = homework.get('homework_name')
    homework_status = homework.get('status')
    if all([homework_name, homework_status]):
        verdict = HOMEWORK_VERDICTS.get(homework_status)
        if not verdict:
            raise ValueError(
                f'Недокументированный '
                f'статус домашней работы - {homework_status}.')
    else:
        raise KeyError('В ответе API отсутствует имя работы или статус.')
    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def main():
    """Основная логика работы бота."""
    if not check_tokens():
        logging.critical('Валидных токенов не обнаружено.')
        raise SystemExit(-1)
    bot = TeleBot(token=TELEGRAM_TOKEN)
    send_message(bot, 'Старт бота')
    timestamp1 = 1
    timestamp2 = 0
    while True:
        try:
            response = get_api_answer(timestamp1)
            homework = check_response(response)
            timestamp2 = response.get('current_date')
            if homework and timestamp1 != timestamp2:
                timestamp1 = timestamp2
                message = parse_status(homework[0])
                send_message(bot, message)
        except Exception as error:
            message = f'Сбой в работе программы: {error}.'
            send_message(bot, message)
            logging.error(message)
        finally:
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
