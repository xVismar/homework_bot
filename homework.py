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
from telebot.apihelper import ApiException, ApiTelegramException


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


MIN_LEVEL = logging.INFO
stdout_handler = logging.StreamHandler(sys.stdout)
stderr_handler = logging.StreamHandler(sys.stderr)
stdout_handler.setLevel(MIN_LEVEL)
stderr_handler.setLevel(max(MIN_LEVEL, logging.WARNING))

if __name__ == '__main__':
    logging.basicConfig(
        filename=os.path.expanduser('~/program.log'),
        format='%(asctime)s, %(levelname)s, %(message)s, %(name)s',
        filemode='w',
        encoding='utf-8',
        stream=sys.stdout,
        handlers=(stdout_handler,)
    )
rootLogger = logging.getLogger()
rootLogger.addHandler(stdout_handler)
rootLogger.addHandler(stderr_handler)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def check_tokens():
    """Проверяет наличие необходимых пременных окружения."""
    tokens = (PRACTICUM_TOKEN, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)
    for token in tokens:
        if not token:
            logger.critical(f'Отсутствует {token}.')
            return False
    logger.info('Все токены получены успешно.')
    return True


def send_message(bot, message):
    """Отправляет сообщение в Telegram чат."""
    logger.info('Сообщение отправляется.')
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
    except ApiTelegramException as error:
        logger.error(f'Сообщение не отправлено Ошибка Telegram - {error}.')
        return False
    except ApiException as e:
        logger.error(f'Ошибка отправки сообщения - {e}')
        return False
    # Cообщение с уровнем debug = @Pytest
    logger.debug('Сообщение успешно отправлено.')
    return True


def get_api_answer(timestamp):
    """Делает запрос к API."""
    logger.info('Отправляю запрос к API.')
    assert isinstance(timestamp, int), (
        'Дата передана в запрос в неверном формате.'
    )
    payload = {'from_date': timestamp}
    try:
        response = requests.get(ENDPOINT, headers=HEADERS, params=payload)
        if response.status_code != HTTPStatus.OK:
            raise requests.RequestException(response)
    except requests.RequestException as error:
        logger.error('API вернул код, отличный от 200.')
        errors = (
            (400, 'некорректный запрос к API'),
            (420, 'слишком много запросов'),
            (500, 'внутренняя ошибка сервера'),
            (403, 'нельзя отправить сообщение'),
        )
        for status, message in errors:
            if error.status_code == status:
                logger.debug(
                    f'API вернул статус {error.status_code}'
                    f' - {message}'
                )
    try:
        return response.json()
    except json.JSONDecodeError as error:
        logger.error(f'Не удалось обработать JSON {error}.')


class ServerNoResponse(Exception):
    """Класс исключения для перехвата редкой ошибки - не получен ответ."""

    logger.error('Нет ответа от сервера.')


def check_response(response):
    """Проверяет ответ API."""
    if not response:
        raise ServerNoResponse
    if not isinstance(response, dict):
        raise TypeError(logger.error('Ответ от сервера - не словарь.'))
    if 'homeworks' not in response:
        raise KeyError(
            logger.error('В ответе API отсутствует ключ - домашние работы.')
        )
    homeworks = response['homeworks']
    if not isinstance(homeworks, list):
        raise TypeError(
            logging.error('В ответе API домашние работы - не список.')
        )
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
        logger.critical('Валидных токенов не обнаружено.')
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
        except ApiTelegramException as tele_error:
            logger.error(f'Сбой в работе - Telegram error: {tele_error}.')
        except Exception as e:
            message = (f'Сбой в работе программы - {e}')
            logger.error(message)
            send_message(bot, message)
        finally:
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
