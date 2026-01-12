# Создание .env файла

## Быстрая инструкция

Создайте файл `.env` в корне проекта (там же, где `manage.py`) со следующим содержимым:

```env
# GPT-OSS-120B Model Settings
# Используется llama-server.exe (автоматический запуск)
# Команда для запуска (для справки):
# "C:\Users\vmare\llama-b6936-bin-win-cuda-12.4-x64\llama-server.exe" -m "C:\Users\vmare\Downloads\gpt-oss-120b-mxfp4-00001-of-00003.gguf" -fa 1 -ncmoe 25 -ngl 40 -ub 2048 -b 2048 -c 32768 --jinja

# Тип модели: llama-server (использует HTTP API llama-server)
GPT_MODEL_TYPE=llama-server

# API базовый URL для llama-server (по умолчанию порт 8080)
LLAMA_SERVER_API_BASE=http://localhost:8080

# Автоматический запуск llama-server (True/False)
LLAMA_AUTO_START=True

# Путь к llama-server.exe (для автоматического запуска)
LLAMA_SERVER_PATH=C:\Users\vmare\llama-b6936-bin-win-cuda-12.4-x64\llama-server.exe

# Путь к модели
GPT_MODEL_PATH=C:\Users\vmare\Downloads\gpt-oss-120b-mxfp4-00001-of-00003.gguf

# Параметры llama-server (из вашей команды)
LLAMA_FLASH_ATTENTION=1
LLAMA_NCMOE=25
LLAMA_NGL=40
LLAMA_UB=2048
LLAMA_BATCH=2048
LLAMA_CONTEXT=32768
LLAMA_JINJA=True
```

## Создание файла в Windows

### Способ 1: Через Блокнот

1. Откройте Блокнот (Notepad)
2. Скопируйте содержимое выше
3. Сохраните файл как `.env` в корне проекта
4. **Важно**: В диалоге сохранения выберите "Все файлы" в типе файла, иначе сохранится как `.env.txt`

### Способ 2: Через PowerShell

Откройте PowerShell в корне проекта и выполните:

```powershell
@"
GPT_MODEL_TYPE=llama-server
LLAMA_SERVER_API_BASE=http://localhost:8080
GPT_MODEL_PATH=C:\Users\vmare\Downloads\gpt-oss-120b-mxfp4-00001-of-00003.gguf
"@ | Out-File -FilePath .env -Encoding utf8
```

### Способ 3: Копировать из .env.example

Скопируйте файл `.env.example` (если он есть) и переименуйте в `.env`, затем отредактируйте при необходимости.

## Проверка

После создания файла `.env`, перезапустите Django сервер:

```bash
python manage.py runserver
```

## Важные замечания

1. **Файл `.env` должен быть в корне проекта** (там же, где `manage.py`)
2. **Не коммитьте `.env` в git** - он содержит чувствительные данные
3. **Проверьте пути** - используйте правильные пути для вашей системы
4. **Порт llama-server** - если llama-server запущен на другом порту, измените `LLAMA_SERVER_API_BASE`
