# Настройка llama-server для GPT-OSS-120B

## Обзор

Ваша конфигурация использует `llama-server.exe` для запуска модели GPT-OSS-120B. Это оптимальный подход для больших моделей, так как сервер работает отдельно и Django приложение подключается к нему через HTTP API.

## Команда запуска llama-server

```bash
"C:\Users\vmare\llama-b6936-bin-win-cuda-12.4-x64\llama-server.exe" -m "C:\Users\vmare\Downloads\gpt-oss-120b-mxfp4-00001-of-00003.gguf" -fa 1 -ncmoe 25 -ngl 40 -ub 2048 -b 2048 -c 32768 --jinja
```

### Параметры команды:

- `-m` - путь к модели GGUF
- `-fa 1` - включить flash attention
- `-ncmoe 25` - количество экспертов для Mixtral MoE модели
- `-ngl 40` - количество слоев на GPU (40 из общего количества)
- `-ub 2048` - размер unaligned buffer
- `-b 2048` - размер batch
- `-c 32768` - размер контекстного окна (32K токенов)
- `--jinja` - поддержка Jinja шаблонов

## Настройка .env файла

Создайте файл `.env` в корне проекта со следующим содержимым:

```env
# Тип модели: llama-server (использует HTTP API)
GPT_MODEL_TYPE=llama-server

# API базовый URL для llama-server (по умолчанию порт 8080)
LLAMA_SERVER_API_BASE=http://localhost:8080

# Путь к модели (для информации)
GPT_MODEL_PATH=C:\Users\vmare\Downloads\gpt-oss-120b-mxfp4-00001-of-00003.gguf
```

## Порядок запуска

### 1. Запустите llama-server

Откройте командную строку и выполните:

```bash
cd C:\Users\vmare
"C:\Users\vmare\llama-b6936-bin-win-cuda-12.4-x64\llama-server.exe" -m "C:\Users\vmare\Downloads\gpt-oss-120b-mxfp4-00001-of-00003.gguf" -fa 1 -ncmoe 25 -ngl 40 -ub 2048 -b 2048 -c 32768 --jinja
```

Дождитесь сообщения о том, что сервер запущен (обычно на порту 8080).

### 2. Запустите Django сервер

В другом терминале:

```bash
cd C:\Users\vmare\salary(cursor).ver.2.1
python manage.py runserver
```

### 3. Откройте страницу AI анализа

Перейдите на: `http://localhost:8000/ai-analysis/`

## Проверка работы

1. На странице AI анализа проверьте статус модели
2. Должно быть "Готово к работе" если llama-server запущен
3. Попробуйте запустить анализ данных

## Устранение проблем

### Ошибка: "Не удалось подключиться к llama-server"

- Убедитесь, что llama-server запущен
- Проверьте порт в `.env` файле (по умолчанию 8080)
- Проверьте, что llama-server слушает на `http://localhost:8080`

### Ошибка: "Сервер вернул статус 404"

- Проверьте, что llama-server запущен с правильными параметрами
- Убедитесь, что порт в `.env` совпадает с портом llama-server

### llama-server не запускается

- Проверьте путь к модели
- Убедитесь, что у вас достаточно VRAM для модели (40 GPU слоев)
- Проверьте, что CUDA установлена и работает

## Альтернативные порты

Если порт 8080 занят, llama-server может использовать другой порт. В этом случае обновите `.env`:

```env
LLAMA_SERVER_API_BASE=http://localhost:ПОРТ
```

## Производительность

- **GPU слои**: `-ngl 40` означает, что 40 слоев будут на GPU, остальные на CPU
- **Контекстное окно**: `-c 32768` позволяет обрабатывать до 32K токенов
- **Batch size**: `-b 2048` влияет на скорость обработки

## Рекомендации

1. Держите llama-server запущенным во время работы с Django
2. Можно создать bat-файл для быстрого запуска llama-server
3. Для production используйте systemd или Windows Service для автоматического запуска

## Создание bat-файла для запуска

Создайте файл `start_llama_server.bat`:

```batch
@echo off
cd C:\Users\vmare
"C:\Users\vmare\llama-b6936-bin-win-cuda-12.4-x64\llama-server.exe" -m "C:\Users\vmare\Downloads\gpt-oss-120b-mxfp4-00001-of-00003.gguf" -fa 1 -ncmoe 25 -ngl 40 -ub 2048 -b 2048 -c 32768 --jinja
pause
```

Запустите его перед запуском Django сервера.
