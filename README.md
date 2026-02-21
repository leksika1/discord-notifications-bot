# Rise of Kingdoms Discord Notifications Bot

Бот отслеживает открытие новых kingdom и отправляет уведомления в Discord-канал.

## Что умеет сейчас
- Пуллит несколько web-источников (`CHECK_URLS`) на каждом цикле.
- Выбирает самое свежее значение `Total Kingdoms`, с опцией консенсуса (`MIN_SOURCE_AGREEMENT`).
- Имеет быстрый канал через Discord watcher (`WATCH_CHANNEL_IDS`): если в отслеживаемом канале появляется сообщение с номером kingdom, бот реагирует сразу.
- Не шлёт спам на первом запуске: сначала сохраняет текущее состояние.

## Структура
- `bot.py` - логика бота.
- `.env.example` - шаблон конфигурации.
- `Dockerfile` - образ приложения.
- `docker-compose.yml` - локальный запуск.
- `.github/workflows/deploy.yml` - CI/CD (build + deploy).
- `data/state.json` - последнее известное значение.

## Требования
- Python 3.12+ или Docker.
- Discord Bot Token.
- Права бота на канал уведомлений: `View Channels`, `Send Messages`, `Read Message History`.
- Если используешь watcher: включить `MESSAGE CONTENT INTENT` в Discord Developer Portal.

## Быстрый старт
1. Создай `.env` из шаблона:
```bash
# Windows (cmd)
copy .env.example .env
# Linux/macOS
cp .env.example .env
```

2. Заполни минимум:
- `DISCORD_TOKEN`
- `CHANNEL_ID`
- `CHECK_URLS`

3. Локальный запуск:
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
python bot.py
```

4. Docker запуск:
```bash
docker compose up --build -d
docker compose logs -f
```

## Основные переменные `.env`
- `DISCORD_TOKEN` - токен бота.
- `CHANNEL_ID` - ID канала, куда отправлять уведомления.
- `CHECK_EVERY_MIN` - интервал опроса web-источников.
- `CHECK_TIMEOUT_SEC` - timeout на HTTP запрос.
- `CHECK_URLS` - источники через запятую.
- `MIN_SOURCE_AGREEMENT` - сколько источников должны дать одинаковое значение (1 = максимально быстро).
- `WATCH_CHANNEL_IDS` - ID каналов (через запятую), которые бот слушает как быстрый источник.
- `MESSAGE_PATTERNS` - кастомные regex-паттерны через `||` для извлечения номера kingdom из сообщений.
- `MIN_KINGDOM_ID`, `MAX_KINGDOM_ID` - фильтр диапазона kingdom ID.
- `STATE_PATH` - путь к state-файлу.
- `MENTION_EVERYONE` - добавлять ли `@everyone`.
- `DEBUG_DUMPS` - сохранять HTML-дампы при проблеме парсинга.

## Рекомендуемая стратегия источников
Для скорости и стабильности:
- `CHECK_URLS`: основной источник `https://heroscroll.com/`.
- `MIN_SOURCE_AGREEMENT=1`: минимальная задержка.
- `WATCH_CHANNEL_IDS`: каналы комьюнити/анонсов, где новости появляются раньше.

Пример:
```env
CHECK_URLS=https://heroscroll.com/
MIN_SOURCE_AGREEMENT=1
WATCH_CHANNEL_IDS=123456789012345678,987654321098765432
```

## Troubleshooting
- `DISCORD_TOKEN is not set`: не заполнен токен.
- `CHANNEL_ID is not set or invalid`: неверный ID.
- `Unable to access notification channel`: бот не видит канал/нет прав.
- `All web sources failed`: недоступны источники или изменилась структура страницы.
- Watcher не реагирует: проверь `MESSAGE CONTENT INTENT`, `WATCH_CHANNEL_IDS` и regex-паттерны.

## Безопасность
- Не коммить `.env`.
- Если токен где-то светился, перевыпусти его в Discord Developer Portal.
