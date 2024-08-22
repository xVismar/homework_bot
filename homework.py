import json
import logging
import os
import sys
import time
from datetime import datetime
from http import HTTPStatus

import requests
from dotenv import load_dotenv
from telebot import TeleBot
from telebot.apihelper import ApiException
from telebot.handler_backends import ContinueHandling
from xmlrpc.client import ResponseError


load_dotenv()

PRACTICUM_TOKEN = os.getenv('YA_TOKEN')
TELEGRAM_TOKEN = os.getenv('TOKEN')
TELEGRAM_CHAT_ID = os.getenv('MASTER_ID')
POLLING_REFRESH_PERIOD_SECONDS = 600  # 600 Секунд - 10 минут
RETRY_PERIOD = POLLING_REFRESH_PERIOD_SECONDS  # @Pytest
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}
HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}


# Фильтр для сообщений\уровней информации и разделение метода вывода информации
# Оригинал кода - https://stackoverflow.com/a/28743317
class LogFilter(logging.Filter):
    """Фильтр (пропускающий) сообщений уровня ниже LEVEL."""

    def __init__(self, level):
        """Присвоение уровня логгера при создании."""
        self.level = level

    def filter(self, record):
        """Условия фильтрации."""
        return record.levelno < self.level


MIN_LEVEL = logging.INFO
stdout_handler = logging.StreamHandler(sys.stdout)
stderr_handler = logging.StreamHandler(sys.stderr)
log_filter = LogFilter(logging.WARNING)
stdout_handler.addFilter(log_filter)
stdout_handler.setLevel(MIN_LEVEL)
stderr_handler.setLevel(max(MIN_LEVEL, logging.WARNING))

if __name__ == '__main__':
    logging.basicConfig(
        filename=os.path.expanduser('~/program.log'),
        format='%(asctime)s, %(levelname)s, %(message)s, %(name)s',
        filemode='w',
        encoding='utf-8',
    )
    rootLogger = logging.getLogger()
    rootLogger.addHandler(stdout_handler)
    rootLogger.addHandler(stderr_handler)
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)


def check_tokens():
    """Проверяет наличие необходимых пременных окружения."""
    tokens = [PRACTICUM_TOKEN, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]
    for token in tokens:
        if not token:
            logging.critical(f'Отсутствует {token}.')
            raise
    logging.info('Все токены получены успешно.')
    return tokens


def send_message(bot, message):
    """Отправляет сообщение в Telegram чат."""
    logging.info('Сообщение отправляется.')
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        # сообщение с уровнем debug = @Pytest
        logging.debug('Сообщение успешно отправлено.')
    except ApiException as error:
        # Можно поменять общий APIException на APITelegramException, но @Pytest
        logging.error(error, exc_info=True)
        logging.error(f'Сообщение не отправлено - {error}.')
        return ContinueHandling()


def get_api_answer(timestamp):
    """Делает запрос к API."""
    logging.info('Отправляю запрос к API.')
    assert isinstance(timestamp, int), (
        'Дата передана в запрос в неверном формате.'
    )
    payload = {'from_date': timestamp}

    try:
        response = requests.get(ENDPOINT, headers=HEADERS, params=payload)
        if response.status_code != HTTPStatus.OK:
            raise requests.exceptions.HTTPError(response)
    except requests.exceptions.RequestException as error:
        logging.error('API вернул код, отличный от 200.')
        errors = (
            (400, 'некорректный запрос к API'),
            (420, 'слишком много запросов'),
            (500, 'внутренняя ошибка сервера'),
            (403, 'нельзя отправить сообщение'),
        )
        for status, message in errors:
            if error.status_code == status:
                logging.debug(
                    f'API вернул статус {error.status_code}'
                    f' - {message}'
                )
    try:
        response.json()
    except json.JSONDecodeError as error:
        logging.error(f'Не удалось обработать JSON {error}.')
    return response.json()


def check_response(response):
    """Проверяет ответ API."""
    if not response:
        logging.error('Нет ответа от сервера.')
        raise ResponseError
    if not isinstance(response, dict):
        logging.error('Ответ от сервера - не словарь.')
        raise TypeError
    if 'homeworks' not in response:
        logging.error('В ответе API отсутствует ключ - домашние работы.')
        raise KeyError
    homeworks = response['homeworks']
    if not isinstance(homeworks, list):
        logging.error('В ответе API домашние работы - не список.')
        raise TypeError
    return homeworks


def parse_status(homework):
    """Получения статуса домашней работы."""
    logging.info('Начинаю парсинг.')
    homework_name = homework.get('homework_name')
    homework_status = homework.get('status')
    if not all((homework_name, homework_status,)):
        raise KeyError('В ответе API отсутствует имя работы или статус.')
    verdict = HOMEWORK_VERDICTS.get(homework_status)
    if not verdict:
        raise ValueError(
            f'Недокументированный '
            f'статус домашней работы - {homework_status}.')
    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def main():
    """Основная логика работы бота."""
    if not check_tokens():
        logging.critical('Валидных токенов не обнаружено.')
        raise SystemExit(-1)
    bot = TeleBot(token=TELEGRAM_TOKEN)
    send_message(bot, 'Старт бота')
    timestamp_1 = 1
    timestamp_2 = 0
    while True:
        try:
            parsed_response_content = get_api_answer(timestamp_1)
            homeworks = check_response(parsed_response_content)
            timestamp_2 = (
                parsed_response_content.get('current_date') if True
                else datetime.today()
            )
            if homeworks and timestamp_1 != timestamp_2:
                for homework in homeworks:
                    timestamp_1 = timestamp_2
                    message = parse_status(homework)
                    send_message(bot, message)
        except Exception as error:
            message = f'Сбой в работе программы: {error}.'
            if error != ApiException:
                send_message(bot, message)
            logging.error(message)
        finally:
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
