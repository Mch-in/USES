"""
Сервис для работы с локальной GPT-OSS-120B моделью
Поддерживает различные форматы моделей (llama-cpp, transformers, vLLM)
"""
import os
import json
import logging
from typing import Optional, Dict, Any, List
from django.conf import settings

logger = logging.getLogger(__name__)

class LLMService:
    """Сервис для работы с локальной LLM моделью"""
    
    def __init__(self):
        self.model = None
        self.model_path = getattr(settings, 'GPT_MODEL_PATH', '')
        self.model_type = getattr(settings, 'GPT_MODEL_TYPE', 'llama-cpp')
        self.n_ctx = getattr(settings, 'GPT_N_CTX', 4096)
        self.n_threads = getattr(settings, 'GPT_N_THREADS', 4)
        self.n_gpu_layers = getattr(settings, 'GPT_N_GPU_LAYERS', 0)
        self.llama_server_api_base = getattr(settings, 'LLAMA_SERVER_API_BASE', 'http://localhost:8080')
        self._initialized = False
        
    def initialize(self):
        """Инициализация модели"""
        if self._initialized:
            return True
        
        # Для llama-server не требуется проверка пути к модели (модель запущена отдельно)
        if self.model_type == 'llama-server':
            # Проверяем только настройки API
            if not self.llama_server_api_base:
                logger.warning("LLAMA_SERVER_API_BASE не установлен. Модель не будет загружена.")
                return False
        else:
            # Для других типов моделей проверяем путь
            if not self.model_path:
                logger.warning("GPT_MODEL_PATH не установлен. Модель не будет загружена.")
                return False
            
            if not os.path.exists(self.model_path):
                logger.error(f"Путь к модели не существует: {self.model_path}")
                return False
            
        try:
            if self.model_type == 'llama-cpp':
                self._initialize_llama_cpp()
            elif self.model_type == 'llama-server':
                self._initialize_llama_server()
            elif self.model_type == 'transformers':
                self._initialize_transformers()
            elif self.model_type == 'vllm':
                self._initialize_vllm()
            else:
                logger.error(f"Неизвестный тип модели: {self.model_type}")
                return False
                
            self._initialized = True
            if self.model_type == 'llama-server':
                logger.info(f"Модель {self.model_type} успешно подключена к {self.llama_server_api_base}")
            else:
                logger.info(f"Модель {self.model_type} успешно загружена из {self.model_path}")
            return True
        except Exception as e:
            logger.exception(f"Ошибка при инициализации модели: {e}")
            return False
    
    def _initialize_llama_cpp(self):
        """Инициализация модели через llama-cpp-python"""
        try:
            from llama_cpp import Llama
            
            self.model = Llama(
                model_path=self.model_path,
                n_ctx=self.n_ctx,
                n_threads=self.n_threads,
                n_gpu_layers=self.n_gpu_layers,
                verbose=False
            )
        except ImportError:
            logger.error("llama-cpp-python не установлен. Установите: pip install llama-cpp-python")
            raise
        except Exception as e:
            logger.error(f"Ошибка при загрузке модели через llama-cpp: {e}")
            raise
    
    def _initialize_transformers(self):
        """Инициализация модели через transformers"""
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
                device_map="auto" if torch.cuda.is_available() else None,
                low_cpu_mem_usage=True
            )
            if not torch.cuda.is_available():
                self.model = self.model.to('cpu')
        except ImportError:
            logger.error("transformers не установлен. Установите: pip install transformers torch")
            raise
        except Exception as e:
            logger.error(f"Ошибка при загрузке модели через transformers: {e}")
            raise
    
    def _initialize_llama_server(self):
        """Инициализация модели через llama-server API"""
        try:
            import requests
            
            # Проверяем доступность сервера - пробуем разные endpoints
            health_endpoints = ["/health", "/", "/api/health", "/v1/health"]
            server_available = False
            
            for health_endpoint in health_endpoints:
                health_url = f"{self.llama_server_api_base.rstrip('/')}{health_endpoint}"
                try:
                    response = requests.get(
                        health_url, 
                        timeout=5,
                        headers={'Accept-Encoding': 'identity'}  # Отключаем gzip
                    )
                    # Проверяем, что это не HTML страница ошибки
                    content_type = response.headers.get('Content-Type', '').lower()
                    if response.status_code == 200 and 'text/html' not in content_type:
                        logger.info(f"llama-server доступен на {self.llama_server_api_base}")
                        self.api_base = self.llama_server_api_base
                        self.requests = requests
                        server_available = True
                        break
                    elif response.status_code == 200:
                        # Если HTML, но статус 200, возможно сервер работает, но endpoint не тот
                        logger.info(f"llama-server отвечает на {health_url}, но возвращает HTML")
                        self.api_base = self.llama_server_api_base
                        self.requests = requests
                        server_available = True
                        break
                except requests.exceptions.RequestException:
                    continue
            
            if not server_available:
                # Если health endpoints не сработали, просто сохраняем настройки
                # Реальная проверка будет при первом запросе
                logger.warning(f"Не удалось проверить доступность llama-server на {self.llama_server_api_base}, но продолжим инициализацию")
                self.api_base = self.llama_server_api_base
                self.requests = requests
                
        except ImportError:
            logger.error("requests не установлен. Установите: pip install requests")
            raise
        except Exception as e:
            logger.error(f"Ошибка при подключении к llama-server API: {e}")
            raise
    
    def _initialize_vllm(self):
        """Инициализация модели через vLLM API"""
        try:
            from openai import OpenAI
            
            # vLLM обычно работает через OpenAI-совместимый API
            api_base = getattr(settings, 'VLLM_API_BASE', 'http://localhost:8000/v1')
            self.client = OpenAI(
                base_url=api_base,
                api_key="not-needed"
            )
            self.model_type = 'vllm-api'
        except ImportError:
            logger.error("openai не установлен для vLLM. Установите: pip install openai")
            raise
        except Exception as e:
            logger.error(f"Ошибка при подключении к vLLM API: {e}")
            raise
    
    def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7, 
                  stop: Optional[List[str]] = None):
        """Генерация ответа на основе промпта
        
        Returns:
            dict с ключами 'text' и 'usage' (информация о токенах), или строка для обратной совместимости
        """
        try:
            if not self._initialized:
                if not self.initialize():
                    error_msg = "Ошибка: Модель не загружена."
                    if self.model_type == 'llama-server':
                        error_msg += " Проверьте, что llama-server запущен и LLAMA_SERVER_API_BASE указан правильно."
                    else:
                        error_msg += " Проверьте настройки GPT_MODEL_PATH."
                    return {'text': error_msg, 'usage': {}}
            
            try:
                if self.model_type == 'llama-cpp':
                    text = self._generate_llama_cpp(prompt, max_tokens, temperature, stop)
                    return {'text': text, 'usage': {}}
                elif self.model_type == 'llama-server':
                    result = self._generate_llama_server(prompt, max_tokens, temperature, stop)
                    # Если вернулся словарь, возвращаем как есть
                    if isinstance(result, dict):
                        return result
                    # Если вернулась строка (для обратной совместимости)
                    return {'text': result, 'usage': {}}
                elif self.model_type == 'transformers':
                    text = self._generate_transformers(prompt, max_tokens, temperature, stop)
                    return {'text': text, 'usage': {}}
                elif self.model_type == 'vllm-api':
                    text = self._generate_vllm(prompt, max_tokens, temperature, stop)
                    return {'text': text, 'usage': {}}
                else:
                    return {'text': "Ошибка: Неизвестный тип модели", 'usage': {}}
            except Exception as e:
                error_msg = str(e)
                logger.exception(f"Ошибка при генерации через {self.model_type}: {e}")
                
                # Форматируем понятное сообщение об ошибке
                if 'llama-server' in error_msg.lower() or 'connection' in error_msg.lower() or 'timeout' in error_msg.lower():
                    error_msg = f"Ошибка подключения к llama-server: {error_msg}. Убедитесь, что llama-server запущен на {self.api_base if hasattr(self, 'api_base') else self.llama_server_api_base}."
                else:
                    error_msg = f"Ошибка при генерации ответа: {error_msg}"
                return {'text': error_msg, 'usage': {}}
        except Exception as e:
            logger.exception(f"Критическая ошибка при генерации: {e}")
            return {'text': f"Критическая ошибка: {str(e)}", 'usage': {}}
    
    def _generate_llama_cpp(self, prompt: str, max_tokens: int, temperature: float, stop: Optional[List[str]]) -> str:
        """Генерация через llama-cpp"""
        response = self.model(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=stop or [],
            echo=False
        )
        return response['choices'][0]['text'].strip()
    
    def _generate_llama_server(self, prompt: str, max_tokens: int, temperature: float, stop: Optional[List[str]]) -> str:
        """Генерация через llama-server API"""
        import requests
        
        # llama-server API endpoint для генерации
        # Попробуем разные варианты endpoints
        endpoints = [
            "/completion",
            "/api/completion",
            "/v1/completions",
            "/api/v1/completions"
        ]
        
        # Для генерации кода увеличиваем n_predict, если max_tokens слишком мал
        # Минимум 512 токенов для кода, максимум 2048
        n_predict = max(max_tokens, 512)
        n_predict = min(n_predict, 2048)
        
        # Базовый payload для llama-server (не OpenAI-совместимый)
        base_payload = {
            "prompt": prompt,
            "n_predict": n_predict,
            "temperature": temperature,
            "stop": stop or [],
            "stream": False
        }
        
        last_error = None
        
        # Пробуем разные endpoints
        for endpoint in endpoints:
            url = f"{self.api_base.rstrip('/')}{endpoint}"
            try:
                logger.info(f"Попытка запроса к llama-server: {url}")
                logger.info(f"Параметры запроса: max_tokens={max_tokens}, temperature={temperature}")
                
                # Для OpenAI-совместимого API используем другой формат
                if endpoint in ['/v1/completions', '/api/v1/completions']:
                    payload = {
                        "model": "default",
                        "prompt": prompt,
                        "max_tokens": n_predict,
                        "temperature": temperature,
                        "stop": stop or []
                    }
                else:
                    payload = base_payload
                
                import time
                start_time = time.time()
                try:
                    response = self.requests.post(
                        url, 
                        json=payload, 
                        timeout=1200,  # Увеличиваем timeout до 20 минут для больших моделей
                        headers={
                            'Content-Type': 'application/json',
                            'Accept-Encoding': 'identity'  # Отключаем gzip для llama-server
                        }
                    )
                    elapsed_time = time.time() - start_time
                    logger.info(f"Запрос к llama-server выполнен за {elapsed_time:.2f} секунд")
                except requests.exceptions.Timeout as timeout_err:
                    elapsed_time = time.time() - start_time
                    logger.error(f"Таймаут запроса к llama-server после {elapsed_time:.2f} секунд")
                    raise Exception(f"Запрос к llama-server превысил лимит времени (20 минут). Модель обрабатывает слишком долго. Попробуйте уменьшить max_tokens или упростить запрос.")
                
                # Проверяем, что ответ не HTML (даже если Content-Type не указывает на это)
                content_type = response.headers.get('Content-Type', '').lower()
                response_text_preview = response.text[:100].strip() if response.text else ''
                
                # Проверяем, начинается ли ответ с HTML тегов
                if response_text_preview.startswith('<!DOCTYPE') or response_text_preview.startswith('<html') or 'text/html' in content_type:
                    logger.warning(f"Сервер вернул HTML вместо JSON на {url}. Статус: {response.status_code}")
                    logger.warning(f"Первые 500 символов ответа: {response.text[:500]}")
                    # Пробуем следующий endpoint
                    continue
                
                # Проверяем статус код перед raise_for_status
                if response.status_code == 404:
                    logger.debug(f"Endpoint {url} не найден (404), пробуем следующий")
                    continue
                
                response.raise_for_status()
                
                # Проверяем, что ответ - это JSON
                # Некоторые серверы могут возвращать text/plain, но с JSON содержимым
                try:
                    data = response.json()
                except ValueError as e:
                    # Если не удалось распарсить как JSON, проверяем, не HTML ли это
                    if response_text_preview.startswith('<!DOCTYPE') or response_text_preview.startswith('<html'):
                        logger.error(f"Сервер вернул HTML вместо JSON на {url}")
                        logger.error(f"Первые 500 символов ответа: {response.text[:500]}")
                        continue
                    
                    # Пробуем распарсить вручную
                    try:
                        data = json.loads(response.text)
                    except (ValueError, json.JSONDecodeError) as json_err:
                        logger.error(f"Ответ не является валидным JSON от {url}: {json_err}")
                        logger.error(f"Первые 500 символов ответа: {response.text[:500]}")
                        # Если это ошибка gzip, пробуем следующий endpoint
                        if 'gzip' in response.text.lower():
                            logger.warning(f"Сервер вернул ошибку gzip, пробуем следующий endpoint")
                        continue
                
                # Извлекаем сгенерированный текст и информацию о токенах
                # llama-server возвращает ответ в формате: {"index": 0, "content": "...", ...}
                text_content = None
                token_info = {}
                
                # Извлекаем информацию о токенах из ответа
                if 'tokens_evaluated' in data:
                    token_info['prompt_tokens'] = data['tokens_evaluated']
                if 'tokens_predicted' in data:
                    token_info['completion_tokens'] = data['tokens_predicted']
                if 'tokens_total' in data:
                    token_info['total_tokens'] = data['tokens_total']
                if 'usage' in data:
                    # OpenAI-совместимый формат
                    usage = data['usage']
                    if 'prompt_tokens' in usage:
                        token_info['prompt_tokens'] = usage['prompt_tokens']
                    if 'completion_tokens' in usage:
                        token_info['completion_tokens'] = usage['completion_tokens']
                    if 'total_tokens' in usage:
                        token_info['total_tokens'] = usage['total_tokens']
                
                # Извлекаем текст
                if 'content' in data:
                    content = data['content']
                    logger.info(f"Успешно получен ответ от llama-server на {url}")
                    if isinstance(content, str):
                        text_content = content.strip()
                    else:
                        logger.warning(f"Поле 'content' не является строкой: {type(content)}")
                        text_content = str(content).strip()
                elif 'text' in data:
                    # Убираем оригинальный промпт из ответа
                    text = data['text']
                    if text.startswith(prompt):
                        text = text[len(prompt):].strip()
                    text_content = text
                elif 'choices' in data and len(data['choices']) > 0:
                    # OpenAI-совместимый формат
                    choice = data['choices'][0]
                    if 'text' in choice:
                        text = choice['text']
                        if text.startswith(prompt):
                            text = text[len(prompt):].strip()
                        text_content = text
                    elif 'message' in choice and 'content' in choice['message']:
                        text_content = choice['message']['content'].strip()
                
                if text_content:
                    # Вычисляем total_tokens, если не указан
                    if 'total_tokens' not in token_info:
                        prompt_tokens = token_info.get('prompt_tokens', 0)
                        completion_tokens = token_info.get('completion_tokens', 0)
                        if prompt_tokens or completion_tokens:
                            token_info['total_tokens'] = prompt_tokens + completion_tokens
                    
                    return {
                        'text': text_content,
                        'usage': token_info
                    }
                else:
                    # Если content пустой, но есть другие данные, проверяем почему
                    if 'content' in data and data['content'] == '':
                        # Проверяем, не остановилась ли модель на стоп-слове
                        if 'stopping_word' in data:
                            stopping_word = data.get('stopping_word', '')
                            logger.warning(f"Модель остановилась на стоп-слове: '{stopping_word}'. Content пустой.")
                            # Если модель остановилась слишком рано, пробуем без стоп-слов или с другими параметрами
                            if stopping_word in ['We need', 'We have', 'We can', 'We should', 'We must']:
                                logger.info("Модель остановилась на английском стоп-слове. Пробуем без этих стоп-слов...")
                                # Пробуем с минимальными стоп-словами только для кода
                                minimal_stop = ['```\n\n', '\n\n\n']
                                payload_minimal = payload.copy()
                                payload_minimal['stop'] = minimal_stop
                                payload_minimal['n_predict'] = max_tokens * 2  # Увеличиваем лимит
                                try:
                                    response_minimal = self.requests.post(
                                        url,
                                        json=payload_minimal,
                                        timeout=1200,
                                        headers={
                                            'Content-Type': 'application/json',
                                            'Accept-Encoding': 'identity'
                                        }
                                    )
                                    response_minimal.raise_for_status()
                                    data_minimal = response_minimal.json()
                                    if 'content' in data_minimal and data_minimal['content']:
                                        text_content = data_minimal['content'].strip()
                                        logger.info(f"Успешно получен ответ с минимальными стоп-словами: {len(text_content)} символов")
                                        # Обновляем token_info
                                        if 'tokens_predicted' in data_minimal:
                                            token_info['completion_tokens'] = data_minimal['tokens_predicted']
                                        if 'tokens_evaluated' in data_minimal:
                                            token_info['prompt_tokens'] = data_minimal['tokens_evaluated']
                                        if 'total_tokens' not in token_info:
                                            prompt_tokens = token_info.get('prompt_tokens', 0)
                                            completion_tokens = token_info.get('completion_tokens', 0)
                                            if prompt_tokens or completion_tokens:
                                                token_info['total_tokens'] = prompt_tokens + completion_tokens
                                        return {
                                            'text': text_content,
                                            'usage': token_info
                                        }
                                except Exception as e:
                                    logger.warning(f"Не удалось получить ответ с минимальными стоп-словами: {e}")
                    
                    logger.warning(f"Неожиданный формат ответа от llama-server на {url}: {data}")
                    # Пробуем следующий endpoint
                    continue
                    
            except requests.exceptions.Timeout as e:
                # Таймаут - это особая ошибка, которая уже обработана выше
                last_error = e
                logger.error(f"Таймаут при запросе к {url}: {e}")
                # Не пробуем другие endpoints при таймауте, так как проблема в производительности
                raise Exception(f"Запрос к llama-server превысил лимит времени. Сервер обрабатывает запрос слишком долго. Попробуйте уменьшить размер запроса или подождите, пока сервер завершит обработку.")
            except requests.exceptions.HTTPError as e:
                # Если это 404, пробуем следующий endpoint
                if e.response and e.response.status_code == 404:
                    logger.debug(f"Endpoint {url} не найден (404), пробуем следующий")
                    last_error = e
                    continue
                else:
                    # Для других HTTP ошибок логируем детали и пробуем следующий endpoint
                    status_code = e.response.status_code if e.response else None
                    error_text = e.response.text[:500] if e.response else str(e)
                    logger.warning(f"HTTP ошибка при запросе к {url}: {status_code} - {error_text}")
                    
                    # Если это 400 Bad Request, логируем размер промпта и детали запроса
                    if status_code == 400:
                        prompt_size = len(prompt)
                        logger.error(f"400 Bad Request от llama-server на {url}")
                        logger.error(f"Размер промпта: {prompt_size} символов (~{prompt_size // 4} токенов)")
                        logger.error(f"Параметры запроса: {json.dumps(payload, ensure_ascii=False, indent=2)}")
                        logger.error(f"Первые 1000 символов промпта: {prompt[:1000]}")
                        logger.error(f"Ответ сервера: {error_text}")
                        
                        # Для OpenAI-совместимого API (/v1/completions) нужен другой формат
                        if endpoint == '/v1/completions':
                            logger.info("Пробуем OpenAI-совместимый формат для /v1/completions")
                            openai_payload = {
                                "model": "default",
                                "prompt": prompt,
                                "max_tokens": n_predict,
                                "temperature": temperature,
                                "stop": stop or []
                            }
                            try:
                                response_openai = self.requests.post(
                                    url,
                                    json=openai_payload,
                                    timeout=1200,
                                    headers={
                                        'Content-Type': 'application/json',
                                        'Accept-Encoding': 'identity'
                                    }
                                )
                                if response_openai.status_code == 200:
                                    data_openai = response_openai.json()
                                    if 'choices' in data_openai and len(data_openai['choices']) > 0:
                                        text_content = data_openai['choices'][0].get('text', '').strip()
                                        if text_content:
                                            logger.info(f"Успешно получен ответ через OpenAI-совместимый формат: {len(text_content)} символов")
                                            # Обновляем token_info
                                            if 'usage' in data_openai:
                                                token_info = data_openai['usage']
                                            return {
                                                'text': text_content,
                                                'usage': token_info
                                            }
                            except Exception as openai_err:
                                logger.warning(f"Не удалось использовать OpenAI-совместимый формат: {openai_err}")
                    
                    last_error = e
                    continue
            except requests.exceptions.RequestException as e:
                last_error = e
                logger.debug(f"Ошибка при запросе к {url}: {e}")
                # Пробуем следующий endpoint
                continue
        
        # Если все endpoints не сработали
        if last_error:
            logger.exception(f"Ошибка при запросе к llama-server: {last_error}")
            error_msg = f"Не удалось подключиться к llama-server. Проверьте, что сервер запущен на {self.api_base}. Ошибка: {str(last_error)}"
            raise Exception(error_msg)
        else:
            # Проверяем, запущен ли llama-server вообще
            try:
                import requests
                health_check = requests.get(
                    self.api_base.rstrip('/'),
                    timeout=2,
                    headers={'Accept-Encoding': 'identity'}
                )
                if health_check.status_code == 200 and ('<!DOCTYPE' in health_check.text or '<html' in health_check.text):
                    error_msg = f"llama-server отвечает на {self.api_base}, но возвращает HTML вместо JSON. Проверьте правильность endpoint'а. Возможно, используется неправильный API endpoint."
                else:
                    error_msg = f"Не удалось получить JSON ответ от llama-server на {self.api_base}. Проверьте доступность сервера и формат API. Попробованы endpoints: {', '.join(endpoints)}"
            except Exception as check_err:
                error_msg = f"llama-server недоступен на {self.api_base}. Проверьте, что сервер запущен. Ошибка проверки: {str(check_err)}"
            
            logger.error(error_msg)
            raise Exception(error_msg)
    
    def _generate_transformers(self, prompt: str, max_tokens: int, temperature: float, stop: Optional[List[str]]) -> str:
        """Генерация через transformers"""
        import torch
        inputs = self.tokenizer(prompt, return_tensors="pt")
        
        if hasattr(self.model, 'device'):
            inputs = {k: v.to(self.model.device) for k, v in inputs.items()}
        
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=temperature,
                do_sample=True,
                pad_token_id=self.tokenizer.eos_token_id
            )
        
        generated_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        # Убираем оригинальный промпт из ответа
        if generated_text.startswith(prompt):
            generated_text = generated_text[len(prompt):].strip()
        
        return generated_text
    
    def _generate_vllm(self, prompt: str, max_tokens: int, temperature: float, stop: Optional[List[str]]) -> str:
        """Генерация через vLLM API"""
        response = self.client.completions.create(
            model="default",
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=stop or []
        )
        return response.choices[0].text.strip()
    
    def analyze_data(self, data_summary: Dict[str, Any], question: str = "", use_streaming: bool = False):
        """Анализ данных с использованием модели
        
        Args:
            data_summary: Сводка данных для анализа (не используется в промпте, так как модель собирает данные через код)
            question: Вопрос для анализа
            use_streaming: Если True, возвращает генератор для streaming ответов
        
        Returns:
            Если use_streaming=False: dict с ключами 'text' и 'usage' (информация о токенах)
            Если use_streaming=True: генератор, который возвращает части ответа (последний чанк содержит usage)
        """
        # data_summary не передается в промпт - модель будет собирать данные через Python код
        prompt = self._build_analysis_prompt(data_summary, question)
        # Используем LLAMA_CONTEXT из настроек для max_tokens
        max_context = getattr(settings, 'LLAMA_CONTEXT', 32768)
        # Убеждаемся, что max_context - это число
        if isinstance(max_context, str):
            try:
                max_context = int(max_context)
            except (ValueError, TypeError):
                max_context = 32768
        elif not isinstance(max_context, int):
            max_context = 32768
        
        # Для генерации кода используем минимальные стоп-токены, чтобы не останавливать генерацию слишком рано
        # Убираем агрессивные стоп-токены типа "We need", так как они могут остановить генерацию кода
        stop_tokens = [
            "\n\n\n\n",  # Множественные пустые строки
            "```\n\n```",  # Пустой блок кода
        ]
        
        # Увеличиваем max_tokens для генерации кода (до 2048 токенов)
        code_max_tokens = min(int(max_context), 2048)
        
        if use_streaming and self.model_type == 'llama-server':
            return self.generate_stream(prompt, max_tokens=code_max_tokens, temperature=0.3, stop=stop_tokens)
        else:
            return self.generate(prompt, max_tokens=code_max_tokens, temperature=0.3, stop=stop_tokens)
    
    def generate_stream(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7, 
                       stop: Optional[List[str]] = None):
        """Генерация ответа через streaming (постепенная передача)"""
        if not self._initialized:
            if not self.initialize():
                error_msg = "Ошибка: Модель не загружена."
                if self.model_type == 'llama-server':
                    error_msg += " Проверьте, что llama-server запущен и LLAMA_SERVER_API_BASE указан правильно."
                else:
                    error_msg += " Проверьте настройки GPT_MODEL_PATH."
                yield {'chunk': error_msg, 'usage': {}}
                return
        
        if self.model_type == 'llama-server':
            yield from self._generate_llama_server_stream(prompt, max_tokens, temperature, stop)
        else:
            # Для других типов моделей возвращаем полный ответ
            full_response = self.generate(prompt, max_tokens, temperature, stop)
            if isinstance(full_response, dict):
                # Если вернулся словарь, возвращаем chunk
                yield {'chunk': full_response.get('text', ''), 'usage': full_response.get('usage', {})}
            else:
                # Для обратной совместимости
                yield full_response
    
    def _generate_llama_server_stream(self, prompt: str, max_tokens: int, temperature: float, stop: Optional[List[str]]) -> str:
        """Генерация через llama-server API с streaming"""
        import requests
        
        endpoints = ["/completion", "/api/completion", "/v1/completions", "/api/v1/completions"]
        
        payload = {
            "prompt": prompt,
            "n_predict": max_tokens,
            "temperature": temperature,
            "stop": stop or [],
            "stream": True  # Включаем streaming
        }
        
        for endpoint in endpoints:
            url = f"{self.api_base.rstrip('/')}{endpoint}"
            try:
                logger.info(f"Попытка streaming запроса к llama-server: {url}")
                response = self.requests.post(
                    url,
                    json=payload,
                    timeout=1200,
                    stream=True,  # Включаем streaming для requests
                    headers={
                        'Content-Type': 'application/json',
                        'Accept-Encoding': 'identity'
                    }
                )
                
                if response.status_code == 404:
                    logger.debug(f"Endpoint {url} не найден (404), пробуем следующий")
                    continue
                
                response.raise_for_status()
                
                # Читаем потоковые данные
                accumulated_text = ""
                token_info = {}
                for line in response.iter_lines():
                    if line:
                        try:
                            # Парсим JSON из каждой строки
                            line_text = line.decode('utf-8')
                            if line_text.startswith('data: '):
                                line_text = line_text[6:]  # Убираем префикс "data: "
                            
                            if line_text.strip() == '[DONE]' or line_text.strip() == '':
                                break
                            
                            data = json.loads(line_text)
                            
                            # Собираем информацию о токенах из каждого чанка
                            if 'tokens_evaluated' in data:
                                token_info['prompt_tokens'] = data['tokens_evaluated']
                            if 'tokens_predicted' in data:
                                token_info['completion_tokens'] = data['tokens_predicted']
                            if 'tokens_total' in data:
                                token_info['total_tokens'] = data['tokens_total']
                            if 'usage' in data:
                                usage = data['usage']
                                if 'prompt_tokens' in usage:
                                    token_info['prompt_tokens'] = usage['prompt_tokens']
                                if 'completion_tokens' in usage:
                                    token_info['completion_tokens'] = usage['completion_tokens']
                                if 'total_tokens' in usage:
                                    token_info['total_tokens'] = usage['total_tokens']
                            
                            # Извлекаем текст из ответа
                            if 'content' in data:
                                content = data['content']
                                if isinstance(content, str):
                                    accumulated_text += content
                                    yield {'chunk': content, 'usage': token_info.copy()}
                                elif content is not None:
                                    content_str = str(content)
                                    accumulated_text += content_str
                                    yield {'chunk': content_str, 'usage': token_info.copy()}
                            elif 'text' in data:
                                text = data['text']
                                if text and text not in accumulated_text:
                                    new_text = text[len(accumulated_text):] if text.startswith(accumulated_text) else text
                                    accumulated_text = text
                                    if new_text:
                                        yield {'chunk': new_text, 'usage': token_info.copy()}
                            elif 'choices' in data and len(data['choices']) > 0:
                                choice = data['choices'][0]
                                if 'delta' in choice and 'content' in choice['delta']:
                                    content = choice['delta']['content']
                                    accumulated_text += content
                                    yield {'chunk': content, 'usage': token_info.copy()}
                                elif 'text' in choice:
                                    text = choice['text']
                                    if text and text not in accumulated_text:
                                        new_text = text[len(accumulated_text):] if text.startswith(accumulated_text) else text
                                        accumulated_text = text
                                        if new_text:
                                            yield {'chunk': new_text, 'usage': token_info.copy()}
                        except json.JSONDecodeError:
                            # Пропускаем не-JSON строки
                            continue
                        except Exception as e:
                            logger.warning(f"Ошибка при обработке streaming данных: {e}")
                            continue
                
                # Если получили данные, выходим
                if accumulated_text:
                    logger.info(f"Успешно получен streaming ответ от {url}, длина: {len(accumulated_text)}")
                    return
                else:
                    logger.warning(f"Streaming запрос к {url} не вернул данных")
                    
            except requests.exceptions.RequestException as e:
                logger.debug(f"Ошибка при streaming запросе к {url}: {e}")
                continue
            except Exception as e:
                logger.exception(f"Неожиданная ошибка при streaming запросе к {url}: {e}")
                continue
        
        # Если все endpoints не сработали
        yield {'chunk': "Ошибка: Не удалось получить streaming ответ от llama-server.", 'usage': {}}
    
    def generate_chart_suggestion(self, data_summary: Dict[str, Any]) -> Dict[str, Any]:
        """Генерация предложения по графику на основе данных"""
        prompt = self._build_chart_prompt(data_summary)
        response = self.generate(prompt, max_tokens=512, temperature=0.3)
        
        # Пытаемся распарсить JSON из ответа
        try:
            # Ищем JSON в ответе
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start != -1 and json_end > json_start:
                json_str = response[json_start:json_end]
                return json.loads(json_str)
        except:
            pass
        
        # Если не удалось распарсить, возвращаем базовую структуру
        return {
            "chart_type": "bar",
            "title": "Анализ данных",
            "description": response,
            "labels": [],
            "datasets": []
        }
    
    def generate_insights(self, table_data: Dict[str, Any], question: str = "") -> str:
        """Генерация выводов и рекомендаций на основе данных таблицы
        
        Args:
            table_data: Данные таблицы в формате {headers: [...], rows: [...]}
            question: Исходный вопрос пользователя (если есть)
        
        Returns:
            Текст с выводами и рекомендациями
        """
        prompt = self._build_insights_prompt(table_data, question)
        
        # Используем более высокую temperature для более креативных выводов
        # Увеличиваем max_tokens до 4096, чтобы ответ не обрезался (1500-2000 слов = ~3000-4000 токенов)
        # Убираем агрессивные стоп-слова, которые могут остановить генерацию
        stop_tokens = [
            "\n\n\n\n",  # Множественные пустые строки
        ]
        
        result = self.generate(prompt, max_tokens=4096, temperature=0.7, stop=stop_tokens)
        
        # Метод generate возвращает словарь с ключами 'text' и 'usage'
        if isinstance(result, dict):
            text = result.get('text', '')
            if not text:
                # Если text пустой, пытаемся получить из других ключей
                text = result.get('response', result.get('content', ''))
            if not text:
                text = "Не удалось сгенерировать выводы. Попробуйте еще раз."
        elif isinstance(result, str):
            text = result
        else:
            # Если результат не словарь и не строка, преобразуем в строку
            logger.warning(f"generate_insights получил неожиданный тип результата: {type(result)}")
            text = str(result) if result else "Не удалось сгенерировать выводы. Попробуйте еще раз."
        
        # Фильтруем английские слова из ответа
        text = self._filter_english_words(text)
        
        return text
    
    def _filter_english_words(self, text: str) -> str:
        """Удаление английских слов из ответа"""
        import re
        
        # Список английских слов и фраз, которые нужно заменить
        english_replacements = [
            (r'\bWe\s+need\b', 'Необходимо'),
            (r'\bWe\s+can\b', 'Можно'),
            (r'\bWe\s+should\b', 'Следует'),
            (r'\bWe\s+must\b', 'Необходимо'),
            (r'\bWe\s+have\b', 'Имеется'),
            (r'\bWe\s+are\b', 'Имеется'),
            (r'\bWe\b', 'Анализ показывает'),
            (r'\bThe\s+data\b', 'Данные'),
            (r'\bThe\s+analysis\b', 'Анализ'),
            (r'\bThe\s+table\b', 'Таблица'),
            (r'\bThe\b', ''),
            (r'\bOkay\b', 'Примечательно'),
            (r'\bKey\s+findings\b', 'Ключевые выводы'),
            (r'\bTrend\s+analysis\b', 'Анализ тенденций'),
            (r'\bRecommendations\b', 'Рекомендации'),
            (r'\bProblem\s+areas\b', 'Проблемные области'),
            (r'\bAnalysis\b', 'Анализ'),
            (r'\bData\b', 'Данные'),
            (r'\bTable\b', 'Таблица'),
        ]
        
        # Заменяем известные английские фразы и слова
        for pattern, replacement in english_replacements:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        
        # Удаляем одиночные английские слова в начале предложений
        # Список английских слов, которые часто встречаются в начале предложений
        english_start_words = ['We', 'The', 'This', 'That', 'These', 'Those', 'It', 'They', 'There', 'Here']
        
        lines = text.split('\n')
        filtered_lines = []
        
        for line in lines:
            if not line.strip():
                filtered_lines.append(line)
                continue
            
            # Проверяем, начинается ли строка с английского слова
            words = line.split()
            if words:
                first_word = re.sub(r'[^\w]', '', words[0])
                if first_word in english_start_words:
                    # Заменяем первое слово
                    if first_word == 'We':
                        words[0] = re.sub(r'\bWe\b', 'Анализ показывает', words[0], flags=re.IGNORECASE)
                    elif first_word == 'The':
                        words[0] = re.sub(r'\bThe\b', '', words[0], flags=re.IGNORECASE)
                    else:
                        # Удаляем английское слово в начале
                        words = words[1:]
            
            # Удаляем одиночные английские слова в середине предложения
            # Но только если это явно английские слова (не аббревиатуры, не числа)
            filtered_words = []
            for word in words:
                clean_word = re.sub(r'[^\w]', '', word)
                # Проверяем, является ли слово английским
                # Игнорируем короткие слова (меньше 3 символов), слова с цифрами, аббревиатуры
                if (len(clean_word) >= 3 and 
                    clean_word.isalpha() and 
                    clean_word.isascii() and
                    clean_word.lower() in ['we', 'the', 'this', 'that', 'these', 'those', 'it', 'they', 'okay', 'key', 'trend', 'analysis', 'data', 'table', 'recommendations']):
                    # Это известное английское слово - пропускаем
                    logger.warning(f"Обнаружено английское слово в ответе: {word}, пропускаем")
                    continue
                filtered_words.append(word)
            
            if filtered_words:
                filtered_lines.append(' '.join(filtered_words))
            elif line.strip():  # Сохраняем пустые строки для форматирования
                filtered_lines.append('')
        
        filtered_text = '\n'.join(filtered_lines)
        
        # Удаляем множественные пробелы
        filtered_text = re.sub(r' +', ' ', filtered_text)
        filtered_text = re.sub(r'\n\s*\n\s*\n+', '\n\n', filtered_text)
        
        # Удаляем пустые строки в начале и конце
        filtered_text = filtered_text.strip()
        
        return filtered_text
    
    def _build_insights_prompt(self, table_data: Dict[str, Any], question: str = "") -> str:
        """Построение промпта для генерации выводов и рекомендаций"""
        headers = table_data.get('headers', [])
        rows = table_data.get('rows', [])
        
        # Форматируем данные таблицы для промпта
        table_text = "Заголовки: " + ", ".join(headers) + "\n\n"
        table_text += "Данные:\n"
        
        # Добавляем первые 20 строк для анализа (чтобы не перегружать промпт)
        max_rows = min(20, len(rows))
        for i, row in enumerate(rows[:max_rows]):
            row_text = " | ".join([str(cell) if cell is not None else "" for cell in row])
            table_text += f"{i+1}. {row_text}\n"
        
        if len(rows) > max_rows:
            table_text += f"\n... (всего {len(rows)} строк)\n"
        
        prompt = f"""Ты - эксперт по анализу данных и бизнес-консультант.

═══════════════════════════════════════════════════════════════
КРИТИЧЕСКИ ВАЖНО - ЯЗЫК ОТВЕТА:
═══════════════════════════════════════════════════════════════
- ОТВЕЧАЙ ТОЛЬКО НА РУССКОМ ЯЗЫКЕ - ЭТО ОБЯЗАТЕЛЬНО
- НЕ ИСПОЛЬЗУЙ АНГЛИЙСКИЙ ЯЗЫК НИ В КАКОЙ ЧАСТИ ОТВЕТА
- ВСЕ ЗАГОЛОВКИ, ПОДЗАГОЛОВКИ, ТАБЛИЦЫ, ТЕКСТ - ТОЛЬКО РУССКИЙ
- ДАЖЕ ТЕХНИЧЕСКИЕ ТЕРМИНЫ ПЕРЕВОДИ НА РУССКИЙ
- ВСЕ ЧИСЛА, РАСЧЕТЫ, ПРОЦЕНТЫ - С ПОДПИСЯМИ НА РУССКОМ
- ЕСЛИ В ОТВЕТЕ БУДЕТ ХОТЯ БЫ ОДНО АНГЛИЙСКОЕ СЛОВО - ЭТО ОШИБКА

СТРОГО ЗАПРЕЩЕНО ИСПОЛЬЗОВАТЬ:
- "We" - НЕ ИСПОЛЬЗУЙ! Пиши "Анализ показывает", "Данные свидетельствуют"
- "The" - НЕ ИСПОЛЬЗУЙ! Используй русские артикли или опускай
- "Okay" - НЕ ИСПОЛЬЗУЙ! Пиши "Хорошо" или "Примечательно"
- "Key findings" - НЕ ИСПОЛЬЗУЙ! Пиши "Ключевые выводы"
- "Trend analysis" - НЕ ИСПОЛЬЗУЙ! Пиши "Анализ тенденций"
- "Recommendations" - НЕ ИСПОЛЬЗУЙ! Пиши "Рекомендации"
- Любые английские слова: "trend", "analysis", "data", "table", "chart"
- Английские фразы: "We need", "We can", "We should", "The data"

ОБЯЗАТЕЛЬНО ИСПОЛЬЗОВАТЬ:
- Все заголовки на русском: "Ключевые выводы", "Анализ тенденций", "Проблемные области", "Рекомендации"
- Все описания, расчеты, выводы - только на русском
- Все таблицы с заголовками на русском языке
- Начинай предложения с русских слов: "Анализ показывает", "Данные свидетельствуют", "Следует отметить"

ПРИМЕРЫ ПРАВИЛЬНОГО НАЧАЛА ОТВЕТА:
✅ ПРАВИЛЬНО:
"Анализ данных показывает следующие ключевые выводы. Общая сумма продаж составляет 28 159 129,74 рублей..."

❌ НЕПРАВИЛЬНО:
"We need to analyze the data. The total sum is..."
═══════════════════════════════════════════════════════════════

Проанализируй следующие данные из таблицы и предоставь полный детальный анализ:

1. **Ключевые выводы** - основные наблюдения и закономерности в данных
   - Используй конкретные числа из таблицы
   - Выдели аномалии и выбросы
   - Проанализируй концентрацию данных
   - Рассчитай средние значения, проценты, соотношения

2. **Анализ трендов** - какие тенденции можно выделить
   - Опиши динамику и закономерности
   - Выяви связи между показателями

3. **Проблемные области** - что требует внимания
   - Низкая эффективность сделок
   - Высокая концентрация рисков
   - Неравномерное распределение

4. **Рекомендации** - конкретные предложения по улучшению или оптимизации
   - Практические шаги на основе данных
   - Приоритетные направления работы

Данные таблицы:
{table_text}

"""
        
        if question:
            prompt += f"Исходный вопрос пользователя: {question}\n\n"
        
        prompt += """═══════════════════════════════════════════════════════════════
ТРЕБОВАНИЯ К ОТВЕТУ:
═══════════════════════════════════════════════════════════════

ЯЗЫК - КРИТИЧЕСКИ ВАЖНО:
- Ответ должен быть ПОЛНОСТЬЮ на русском языке - БЕЗ ИСКЛЮЧЕНИЙ
- НИ ОДНОГО английского слова в ответе
- Все заголовки: "Ключевые выводы", "Анализ тенденций", "Проблемные области", "Рекомендации"
- Все подзаголовки, описания, выводы - только на русском
- Все таблицы с заголовками на русском языке
- Все расчеты с пояснениями на русском
- НЕ НАЧИНАЙ предложения с "We", "The", "Okay" - используй русские фразы

СТРУКТУРА И СОДЕРЖАНИЕ:
- Используй структурированный формат с заголовками
- Применяй маркированные списки для удобства чтения
- Включай конкретные расчеты и цифры из таблицы
- Используй таблицы для сравнения данных, если это уместно
- Будь детальным и конкретным
- НЕ ОБРЕЗАЙ ОТВЕТ - предоставь полный анализ всех разделов
- Минимальная длина ответа: 1500-2000 слов
- НЕ ОСТАНАВЛИВАЙСЯ раньше времени - продолжай генерацию до конца

ПРИМЕР ПРАВИЛЬНОГО НАЧАЛА ОТВЕТА:
"Анализ данных показывает следующие ключевые выводы. Общая сумма продаж составляет 28 159 129,74 рублей. Средняя сумма на компанию равна 2 815 912,97 рублей. Топ-3 компании концентрируют 49,5% от общей суммы продаж..."

ПОВТОРЯЮ ЕЩЕ РАЗ:
- ОТВЕЧАЙ ТОЛЬКО НА РУССКОМ ЯЗЫКЕ
- НЕ ИСПОЛЬЗУЙ АНГЛИЙСКИЙ ЯЗЫК
- НЕ ИСПОЛЬЗУЙ "We", "The", "Okay" и другие английские слова
- ВСЕ ЗАГОЛОВКИ НА РУССКОМ: "Ключевые выводы", "Анализ тенденций", "Проблемные области", "Рекомендации"
- НАЧИНАЙ предложения с русских фраз: "Анализ показывает", "Данные свидетельствуют", "Следует отметить"
═══════════════════════════════════════════════════════════════

Сформулируй полный детальный ответ ТОЛЬКО на русском языке.
НЕ ИСПОЛЬЗУЙ английские слова. НЕ ОСТАНАВЛИВАЙСЯ раньше времени.

Выводы и рекомендации:"""
        
        return prompt
    
    def _build_analysis_prompt(self, data_summary: Dict[str, Any], question: str) -> str:
        """Построение промпта для анализа данных
        
        ВАЖНО: Мы НЕ передаем данные в промпт, так как модель будет собирать их через Python код
        """
        # Не передаем данные в промпт - модель будет собирать их через код
        # Только логируем для отладки
        logger.info(f"Создаем промпт для генерации Python кода. Вопрос: {question[:100] if question else 'Нет вопроса'}")
        
        # Используем обычную строку вместо f-строки, чтобы избежать проблем с экранированием
        prompt = """Ты - эксперт по написанию Python кода для работы с базой данных Django.

КРИТИЧЕСКИ ВАЖНО: 
- ТЫ ДОЛЖЕН ГЕНЕРИРОВАТЬ ТОЛЬКО PYTHON КОД, БЕЗ ТЕКСТОВЫХ ОТВЕТОВ
- НЕ ПИШИ никаких объяснений, комментариев вне кода, текстовых ответов
- НЕ ПИШИ на английском или русском языке - ТОЛЬКО КОД
- Код должен быть в markdown блоке ```python ... ```
- Код должен собирать данные из базы данных используя Django ORM напрямую
- Код должен создавать переменную `result` со списком словарей для таблицы
- Каждый словарь в списке - это строка таблицы, ключи - названия столбцов на русском языке
- ВАЖНО: В f-строках правильно экранируй фигурные скобки - используй двойные скобки для экранирования
- ВАЖНО: Все фигурные скобки в f-строках должны быть правильно закрыты

ДОСТУПНЫЕ МОДЕЛИ DJANGO (УЖЕ ИМПОРТИРОВАНЫ, НЕ ИМПОРТИРУЙ ИХ!):
- Sale - модель продаж (поля: id_number, manager, sale, company, account_number, salary, closing_date, title)
- SalaryPayment - модель зарплатных выплат (поля: manager, amount, payment_datetime)
- ProductionExpense - модель расходов (поля: employee, expense_type, amount, expense_date, comment)
- BitrixUser - модель менеджеров (поля: user_id, name, last_name, is_admin)
- Company - модель компаний (поля: company_id, title)
- Employee - модель сотрудников (поля: name)
- ExpenseType - модель типов расходов (поля: name)

КРИТИЧЕСКИ ВАЖНО - ИМПОРТ МОДЕЛЕЙ:
- НЕ ИСПОЛЬЗУЙ импорты моделей типа: from myapp.models import Sale
- НЕ ИСПОЛЬЗУЙ импорты моделей типа: from salary_app.models import Sale
- Модели Sale, SalaryPayment, ProductionExpense, BitrixUser, Company, Employee, ExpenseType УЖЕ ДОСТУПНЫ в коде
- Просто используй Sale.objects.all() БЕЗ импорта!
- Импортируй ТОЛЬКО функции Django ORM: from django.db.models import Sum, Count, Avg, Max, Min, Q, F

ДОСТУПНЫЕ ФУНКЦИИ DJANGO ORM (ИМПОРТИРУЙ ИХ):
- Sum, Count, Avg, Max, Min - агрегатные функции (импортируй: from django.db.models import Sum, Count)
- Q, F - для сложных запросов (импортируй: from django.db.models import Q, F)
- timezone, datetime, timedelta - для работы с датами (импортируй: from django.utils import timezone, from datetime import datetime, timedelta)

ПРИМЕРЫ КОДА:

Пример 1 - Анализ расходов по типам:
```python
from django.db.models import Sum, Count
# НЕ ИМПОРТИРУЙ ProductionExpense - она уже доступна!

expenses = ProductionExpense.objects.all()
result = []

expense_types = expenses.values('expense_type__name').annotate(
    total=Sum('amount'),
    count=Count('id')
).order_by('-total')

for exp_type in expense_types:
    result.append({{
        'Тип расхода': exp_type.get('expense_type__name', ''),
        'Сумма': float(exp_type.get('total', 0) or 0),
        'Количество': exp_type.get('count', 0)
    }})
```

Пример 2 - Продажи по менеджерам:
```python
from django.db.models import Sum, Count
# НЕ ИМПОРТИРУЙ Sale - она уже доступна!

sales = Sale.objects.all()
result = []

managers = sales.values('manager__name', 'manager__last_name').annotate(
    total_sales=Sum('sale'),
    count=Count('id')
).order_by('-total_sales')

for manager in managers:
    last_name = manager.get('manager__last_name', '') or ''
    first_name = manager.get('manager__name', '') or ''
    result.append({{
        'Менеджер': f"{{last_name}} {{first_name}}".strip() or 'Не указан',
        'Сумма продаж': float(manager.get('total_sales', 0) or 0),
        'Количество сделок': manager.get('count', 0)
    }})
```

Пример 3 - Расходы по месяцам:
```python
from django.db.models import Sum, Count
from django.utils import timezone
# НЕ ИМПОРТИРУЙ ProductionExpense - она уже доступна!

expenses = ProductionExpense.objects.all()
result = []

monthly = expenses.extra(
    select={{'month': "DATE_FORMAT(expense_date, '%%Y-%%m')"}}
).values('month').annotate(
    total=Sum('amount'),
    count=Count('id')
).order_by('month')

for month_data in monthly:
    result.append({{
        'Месяц': month_data.get('month', ''),
        'Сумма': float(month_data.get('total', 0) or 0),
        'Количество': month_data.get('count', 0)
    }})
```

ВАЖНО:
- Используй только Django ORM для работы с БД
- Всегда создавай переменную `result` со списком словарей
- Названия столбцов должны быть на русском языке
- Числовые значения должны быть float для правильного отображения
- Сортируй результаты по убыванию суммы/количества, если это уместно
- ВАЖНО: Используй .get() для доступа к значениям словарей, чтобы избежать ошибок
- ВАЖНО: Не используй словари как ключи в других словарях или множествах
- ВАЖНО: При работе с .values() всегда используй строковые ключи, не словари
- ВАЖНО: При доступе к значениям из .values() используй .get() вместо прямого доступа по ключу

Вопрос пользователя: """ + (question if question else "Проанализируй данные") + """

Сгенерируй ТОЛЬКО Python код без каких-либо текстовых объяснений:

"""
        
        return prompt
    
    def _build_chart_prompt(self, data_summary: Dict[str, Any]) -> str:
        """Построение промпта для генерации предложения по графику"""
        prompt = f"""Ты - эксперт по визуализации данных. На основе следующих данных предложи оптимальный тип графика и его структуру.

ВАЖНО: Весь ответ должен быть ТОЛЬКО на русском языке. Все названия, описания и метки должны быть на русском языке.

Данные:
{json.dumps(data_summary, ensure_ascii=False, indent=2)}

Верни ответ в формате JSON:
{{
    "chart_type": "bar|line|pie|doughnut",
    "title": "Название графика",
    "description": "Описание что показывает график",
    "labels": ["метка1", "метка2", ...],
    "datasets": [
        {{
            "label": "Название набора данных",
            "data": [значение1, значение2, ...]
        }}
    ]
}}

КРИТИЧЕСКИ ВАЖНО: Ответ должен быть только валидным JSON. Все текстовые поля (title, description, labels, label) должны быть на русском языке. Не используй английский язык."""
        return prompt


# Глобальный экземпляр сервиса (singleton)
_llm_service = None

def get_llm_service() -> LLMService:
    """Получение глобального экземпляра LLM сервиса"""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
