# Rise of Kingdoms Discord Notifications Bot

Бот для Discord, который отслеживает количество kingdom-серверов на источнике и отправляет уведомление в канал, когда появляется новый.

## Что делает бот
- Периодически проверяет страницу (`CHECK_URL`) и ищет значение `Total Kingdoms: N`.
- Хранит последнее значение в `state.json`.
- При росте значения отправляет сообщение в Discord-канал.
- На первом запуске только инициализирует состояние, без рассылки.

## Структура проекта
- `bot.py` - логика бота и парсер.
- `requirements.txt` - Python-зависимости.
- `Dockerfile` - сборка контейнера.
- `docker-compose.yml` - запуск контейнера с volume для состояния.
- `data/` - локальное состояние (`state.json`).
- `.env.example` - шаблон переменных окружения.

## Требования
- Python 3.12+ (локальный запуск), или Docker + Docker Compose.
- Discord Bot Token.
- Права бота на чтение/отправку сообщений в целевом канале.

## Настройка Discord
1. Создай приложение: `https://discord.com/developers/applications`
2. Вкладка `Bot`:
- создай бота;
- включи `MESSAGE CONTENT INTENT` не требуется для этого проекта;
- скопируй token.
3. Пригласи бота на сервер с правами:
- `View Channels`
- `Send Messages`
- `Read Message History`
- `Mention Everyone` (только если нужен `@everyone`)
4. Включи Developer Mode в Discord и скопируй ID канала.

## Настройка окружения
1. Скопируй шаблон:
```bash
# Windows (cmd)
copy .env.example .env
# Linux/macOS
cp .env.example .env
```
2. Заполни `.env`:
- `DISCORD_TOKEN` - токен бота.
- `CHANNEL_ID` - ID канала.
- `CHECK_EVERY_MIN` - интервал проверки в минутах.
- `CHECK_URL` - источник для парсинга.
- `STATE_PATH` - путь к файлу состояния.
- `MENTION_EVERYONE=true|false` - упоминать ли `@everyone`.
- `DEBUG_DUMPS=true|false` - сохранять HTML-дампы при ошибке парсинга.

## Локальный запуск (Python)
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
python bot.py
```

## Запуск через Docker Compose
```bash
docker compose up --build -d
docker compose logs -f
```

Остановка:
```bash
docker compose down
```

## Как проверить, что всё работает
- В логах должен быть вход бота в Discord.
- На первом цикле в логах появится `Initial state saved`.
- При увеличении `Total Kingdoms` бот отправит уведомление в канал.

## Возможные проблемы
- `DISCORD_TOKEN is not set`: не заполнен `.env`.
- `CHANNEL_ID is not set or invalid`: неверный ID канала.
- `Unable to access channel`: у бота нет прав или бот не добавлен на сервер.
- `Could not parse 'Total Kingdoms'`: структура страницы изменилась. Включи `DEBUG_DUMPS=true` и проверь сохранённые HTML рядом с `STATE_PATH`.

## Безопасность
- Не коммить `.env` в репозиторий.
- Если токен бота уже светился где-либо (чат, скриншоты, публичные файлы), его нужно перевыпустить в Discord Developer Portal.
