# Freemius

GUI SSH-клиент для Linux на **PyQt6 + paramiko + pyte**.

## Возможности

- Графический интерфейс для SSH-подключений
- Полноценный эмулятор терминала с ANSI-цветами
- Автоматический resize PTY при изменении окна
- Сохранение подключений в `~/.config/freemius/connections.json`
- Аутентификация по паролю и по ключу (в т.ч. `~/.ssh/id_*` и ssh-agent)
- Логирование SSH-сессии в stdout

## Скриншот

_(добавь свой скриншот сюда)_

## Установка

```bash
git clone git@github.com:Sornodod/Freemius.git
cd Freemius
python3 -m venv venv
source venv/bin/activate.fish   # или venv/bin/activate для bash/zsh
pip install -r requirements.txt
```

## Запуск

```bash
python main.py
```

## Использование

1. Заполни поля **Хост / Порт / Пользователь / Пароль / Ключ**.
2. Нажми **Сохранить**, чтобы запомнить подключение (пароль не сохраняется).
3. Выбирай сохранённые подключения из выпадающего списка.
4. Нажми **Подключиться** — откроется терминал.

## Хранилище подключений

Файл: `~/.config/freemius/connections.json` (права `600`).
Пароли **не** сохраняются — только хост, порт, пользователь и путь к ключу.

## Требования

- Python 3.10+
- PyQt6, paramiko, pyte
- Linux (тестировалось на Debian/Ubuntu)
