"""
Views для работы с AI моделью GPT-OSS-120B
"""
import json
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie
from functools import wraps
from django.db.models import Sum, Count, Avg
from datetime import datetime, date, timedelta
from django.utils import timezone

from .models import Sale, SalaryPayment, ProductionExpense, BitrixUser, Company, Employee, ExpenseType
from .llm_service import get_llm_service
from .llama_server_manager import get_manager
from .code_executor import CodeExecutor
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


def json_serialize_dates(obj):
    """
    Рекурсивно преобразует объекты date и datetime в строки для JSON сериализации.
    
    Args:
        obj: Объект для преобразования (может быть dict, list, date, datetime или другой тип)
        
    Returns:
        Объект с преобразованными датами в строки
    """
    if isinstance(obj, (date, datetime)):
        # Преобразуем date/datetime в строку ISO формата
        if isinstance(obj, datetime):
            return obj.isoformat()
        else:
            return obj.isoformat()
    elif isinstance(obj, dict):
        return {key: json_serialize_dates(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [json_serialize_dates(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(json_serialize_dates(item) for item in obj)
    else:
        return obj


def json_response_on_error(view_func):
    """Декоратор для обработки исключений и возврата JSON ответов"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            return view_func(request, *args, **kwargs)
        except Exception as e:
            logger.exception(f"Необработанное исключение в {view_func.__name__}: {e}")
            return JsonResponse({
                'success': False,
                'error': f'Внутренняя ошибка сервера: {str(e)}'
            }, status=500)
    return wrapper


@login_required
@ensure_csrf_cookie
def ai_analysis_view(request):
    """Основная страница для работы с AI анализом"""
    try:
        current_user = BitrixUser.objects.get(django_user=request.user)
        is_admin = current_user.is_admin if current_user else False
    except BitrixUser.DoesNotExist:
        current_user = None
        is_admin = False
    
    # Автоматический запуск llama-server, если включен
    auto_start = getattr(settings, 'LLAMA_AUTO_START', True)
    model_type = getattr(settings, 'GPT_MODEL_TYPE', 'llama-cpp')
    
    if auto_start and model_type == 'llama-server':
        try:
            manager = get_manager()
            if manager.ensure_running():
                logger.info("llama-server автоматически запущен или уже был запущен")
            else:
                logger.warning("Не удалось автоматически запустить llama-server")
        except Exception as e:
            logger.exception(f"Ошибка при автоматическом запуске llama-server: {e}")
    
    # Получаем данные для анализа
    data_summary = _get_data_summary(request, current_user, is_admin)
    
    context = {
        'data_summary': data_summary,
        'is_admin': is_admin,
    }
    
    return render(request, 'salary/ai_analysis.html', context)


@login_required
@require_http_methods(["POST"])
@json_response_on_error
def ai_analyze_data(request):
    """API endpoint для анализа данных через AI"""
    try:
        # Парсим JSON из тела запроса
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON: {e}")
            return JsonResponse({
                'success': False,
                'error': 'Неверный формат JSON в запросе'
            }, status=400)
        
        question = data.get('question', '')
        use_streaming = data.get('streaming', True)  # По умолчанию используем streaming
        
        try:
            current_user = BitrixUser.objects.get(django_user=request.user)
            is_admin = current_user.is_admin if current_user else False
        except BitrixUser.DoesNotExist:
            current_user = None
            is_admin = False
        
        # Получаем сводку данных
        try:
            data_summary = _get_data_summary(request, current_user, is_admin)
        except Exception as e:
            logger.exception(f"Ошибка при получении сводки данных: {e}")
            return JsonResponse({
                'success': False,
                'error': f'Ошибка при получении данных: {str(e)}'
            }, status=500)
        
        # Получаем LLM сервис
        try:
            llm_service = get_llm_service()
        except Exception as e:
            logger.exception(f"Ошибка при получении LLM сервиса: {e}")
            return JsonResponse({
                'success': False,
                'error': f'Ошибка при инициализации LLM сервиса: {str(e)}'
            }, status=500)
        
        # Если streaming включен и модель поддерживает его
        if use_streaming and llm_service.model_type == 'llama-server':
            def generate_stream():
                try:
                    logger.info(f"Начинаем streaming анализ данных через AI. Тип модели: {llm_service.model_type}")
                    logger.info(f"Вопрос пользователя: {question[:100] if question else 'Нет вопроса'}")
                    accumulated = ""
                    token_usage = {}
                    chunk_count = 0
                    has_data = False
                    
                    for chunk_data in llm_service.analyze_data(data_summary, question, use_streaming=True):
                        chunk_count += 1
                        if isinstance(chunk_data, dict):
                            chunk = chunk_data.get('chunk', '')
                            if 'usage' in chunk_data:
                                token_usage = chunk_data['usage']
                        else:
                            # Для обратной совместимости
                            chunk = chunk_data
                        
                        # Проверяем, не является ли chunk сообщением об ошибке
                        if chunk and chunk.startswith('Ошибка:'):
                            # Если это ошибка, отправляем её как error
                            logger.error(f"Получена ошибка от модели: {chunk}")
                            yield f"data: {json.dumps({'error': chunk}, ensure_ascii=False)}\n\n"
                            break
                        
                        if chunk:
                            has_data = True
                            accumulated += chunk
                            # Отправляем chunk в формате JSON для SSE
                            yield f"data: {json.dumps({'chunk': chunk, 'accumulated': accumulated, 'usage': token_usage}, ensure_ascii=False)}\n\n"
                    
                    # Проверяем, был ли получен хотя бы один chunk
                    logger.info(f"Streaming завершен. Получено чанков: {chunk_count}, Накопленный текст: {len(accumulated)} символов")
                    
                    # Если накопленный текст пустой, но не было ошибки, это проблема
                    if not accumulated and not has_data and chunk_count > 0:
                        logger.warning("Модель вернула пустой ответ без ошибок! Пробуем не-streaming режим...")
                        # Пробуем не-streaming режим как fallback
                        try:
                            logger.info("Пробуем не-streaming режим как fallback")
                            result = llm_service.analyze_data(data_summary, question, use_streaming=False)
                            if isinstance(result, dict):
                                analysis = result.get('text', '')
                                token_usage = result.get('usage', {})
                            else:
                                analysis = result
                                token_usage = {}
                            
                            if analysis and analysis.strip():
                                logger.info(f"Не-streaming режим успешно сгенерировал ответ: {len(analysis)} символов")
                                accumulated = analysis
                                token_usage = token_usage
                            else:
                                logger.error("Не-streaming режим также вернул пустой ответ")
                                error_msg = "Модель не сгенерировала ответ в обоих режимах. Возможно, промпт слишком большой или модель не может обработать запрос."
                                yield f"data: {json.dumps({'error': error_msg}, ensure_ascii=False)}\n\n"
                                return
                        except Exception as fallback_error:
                            logger.exception(f"Ошибка при fallback на не-streaming режим: {fallback_error}")
                            error_msg = "Модель не сгенерировала ответ. Возможно, промпт слишком большой или модель не может обработать запрос."
                            yield f"data: {json.dumps({'error': error_msg}, ensure_ascii=False)}\n\n"
                            return
                    
                    # Отправляем финальное сообщение с информацией о токенах
                    # Вычисляем total_tokens, если не указан
                    if 'total_tokens' not in token_usage:
                        prompt_tokens = token_usage.get('prompt_tokens', 0)
                        completion_tokens = token_usage.get('completion_tokens', 0)
                        if prompt_tokens or completion_tokens:
                            token_usage['total_tokens'] = prompt_tokens + completion_tokens
                    
                    logger.info(f"Финальный ответ: {len(accumulated)} символов, токены: {token_usage}")
                    
                    # Пытаемся извлечь и выполнить код из ответа
                    table_data = None
                    code_result = None
                    try:
                        # Передаем Django модели в CodeExecutor
                        models_dict = {
                            'Sale': Sale,
                            'SalaryPayment': SalaryPayment,
                            'ProductionExpense': ProductionExpense,
                            'BitrixUser': BitrixUser,
                            'Company': Company,
                            'Employee': Employee,
                            'ExpenseType': ExpenseType,
                        }
                        executor = CodeExecutor(data_summary, models=models_dict)
                        code = executor.extract_code_from_response(accumulated)
                        if code:
                            logger.info(f"Найден код в ответе модели, выполняем...")
                            logger.debug(f"Извлеченный код (первые 1000 символов):\n{code[:1000]}")
                            code_result = executor.execute_code(code)
                            logger.info(f"Результат выполнения кода: success={code_result.get('success')}, has_data={bool(code_result.get('data'))}, has_result={bool(code_result.get('result'))}")
                            
                            # Проверяем, есть ли данные в result или data
                            data_for_table = None
                            if code_result.get('success'):
                                # Сначала проверяем result (переменная result из кода)
                                if code_result.get('result'):
                                    data_for_table = code_result['result']
                                    logger.info(f"Используем данные из result: {type(data_for_table)}")
                                # Если result нет, проверяем data
                                elif code_result.get('data'):
                                    data_for_table = code_result['data']
                                    logger.info(f"Используем данные из data: {type(data_for_table)}")
                                
                                if data_for_table:
                                    table_data = executor.format_data_as_table(data_for_table)
                                    logger.info(f"Код выполнен успешно, получены данные для таблицы: {len(table_data.get('rows', []))} строк, {len(table_data.get('headers', []))} столбцов")
                                else:
                                    logger.warning("Код выполнен успешно, но данные не найдены ни в result, ни в data")
                            else:
                                logger.warning(f"Код не выполнен успешно: {code_result.get('error')}")
                    except Exception as e:
                        logger.exception(f"Ошибка при выполнении кода: {e}")
                        # Не прерываем выполнение, просто логируем ошибку
                    
                    # Преобразуем даты в строки перед JSON сериализацией
                    serializable_table_data = json_serialize_dates(table_data) if table_data else None
                    serializable_code_result = json_serialize_dates(code_result) if code_result else None
                    
                    yield f"data: {json.dumps({'done': True, 'full_text': accumulated, 'usage': token_usage, 'table_data': serializable_table_data, 'code_result': serializable_code_result}, ensure_ascii=False)}\n\n"
                except Exception as e:
                    logger.exception(f"Ошибка при streaming анализе данных через AI: {e}")
                    error_msg = str(e)
                    yield f"data: {json.dumps({'error': error_msg}, ensure_ascii=False)}\n\n"
            
            response = StreamingHttpResponse(generate_stream(), content_type='text/event-stream')
            response['Cache-Control'] = 'no-cache'
            response['X-Accel-Buffering'] = 'no'
            return response
        else:
            # Обычный не-streaming режим
            try:
                logger.info(f"Начинаем анализ данных через AI. Тип модели: {llm_service.model_type}")
                result = llm_service.analyze_data(data_summary, question, use_streaming=False)
                
                # Обрабатываем новый формат возврата (dict с 'text' и 'usage')
                if isinstance(result, dict):
                    analysis = result.get('text', '')
                    token_usage = result.get('usage', {})
                else:
                    # Для обратной совместимости
                    analysis = result
                    token_usage = {}
                
                logger.info(f"Анализ данных завершен успешно. Длина ответа: {len(analysis) if analysis else 0}")
                
                # Вычисляем total_tokens, если не указан
                if 'total_tokens' not in token_usage:
                    prompt_tokens = token_usage.get('prompt_tokens', 0)
                    completion_tokens = token_usage.get('completion_tokens', 0)
                    if prompt_tokens or completion_tokens:
                        token_usage['total_tokens'] = prompt_tokens + completion_tokens
                
                # Пытаемся извлечь и выполнить код из ответа
                table_data = None
                code_result = None
                try:
                    # Передаем Django модели в CodeExecutor
                    models_dict = {
                        'Sale': Sale,
                        'SalaryPayment': SalaryPayment,
                        'ProductionExpense': ProductionExpense,
                        'BitrixUser': BitrixUser,
                        'Company': Company,
                        'Employee': Employee,
                        'ExpenseType': ExpenseType,
                    }
                    executor = CodeExecutor(data_summary, models=models_dict)
                    code = executor.extract_code_from_response(analysis)
                    if code:
                        logger.info(f"Найден код в ответе модели, выполняем...")
                        logger.debug(f"Извлеченный код (первые 1000 символов):\n{code[:1000]}")
                        code_result = executor.execute_code(code)
                        logger.info(f"Результат выполнения кода: success={code_result.get('success')}, has_data={bool(code_result.get('data'))}, has_result={bool(code_result.get('result'))}")
                        
                        # Проверяем, есть ли данные в result или data
                        data_for_table = None
                        if code_result.get('success'):
                            # Сначала проверяем result (переменная result из кода)
                            if code_result.get('result'):
                                data_for_table = code_result['result']
                                logger.info(f"Используем данные из result: {type(data_for_table)}")
                            # Если result нет, проверяем data
                            elif code_result.get('data'):
                                data_for_table = code_result['data']
                                logger.info(f"Используем данные из data: {type(data_for_table)}")
                            
                            if data_for_table:
                                table_data = executor.format_data_as_table(data_for_table)
                                logger.info(f"Код выполнен успешно, получены данные для таблицы: {len(table_data.get('rows', []))} строк, {len(table_data.get('headers', []))} столбцов")
                            else:
                                logger.warning("Код выполнен успешно, но данные не найдены ни в result, ни в data")
                        else:
                            logger.warning(f"Код не выполнен успешно: {code_result.get('error')}")
                except Exception as e:
                    logger.exception(f"Ошибка при выполнении кода: {e}")
                    # Не прерываем выполнение, просто логируем ошибку
                
                # Преобразуем даты в строки перед JSON сериализацией
                serializable_table_data = json_serialize_dates(table_data) if table_data else None
                serializable_code_result = json_serialize_dates(code_result) if code_result else None
                serializable_data_summary = json_serialize_dates(data_summary) if data_summary else None
                
                return JsonResponse({
                    'success': True,
                    'analysis': analysis,
                    'usage': token_usage,
                    'data_summary': serializable_data_summary,
                    'table_data': serializable_table_data,
                    'code_result': serializable_code_result
                })
            except Exception as e:
                logger.exception(f"Ошибка при анализе данных через AI: {e}")
                error_msg = str(e)
                # Проверяем, связана ли ошибка с llama-server
                if 'llama-server' in error_msg.lower() or 'connection' in error_msg.lower() or 'html' in error_msg.lower():
                    if 'html' in error_msg.lower():
                        error_msg = 'llama-server возвращает HTML вместо JSON. Проверьте правильность endpoint\'а и настройки API.'
                    else:
                        error_msg = 'Не удалось подключиться к llama-server. Убедитесь, что сервер запущен и доступен на указанном адресе.'
                return JsonResponse({
                    'success': False,
                    'error': f'Ошибка при анализе данных: {error_msg}'
                }, status=500)
        
    except Exception as e:
        logger.exception(f"Неожиданная ошибка при анализе данных через AI: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Неожиданная ошибка: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["POST"])
@json_response_on_error
def ai_generate_insights(request):
    """API endpoint для генерации выводов и рекомендаций на основе данных таблицы"""
    try:
        # Парсим JSON из тела запроса
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON: {e}")
            return JsonResponse({
                'success': False,
                'error': 'Неверный формат JSON в запросе'
            }, status=400)
        
        table_data = data.get('table_data', {})
        question = data.get('question', '')
        
        if not table_data or not table_data.get('headers') or not table_data.get('rows'):
            return JsonResponse({
                'success': False,
                'error': 'Данные таблицы не предоставлены'
            }, status=400)
        
        # Получаем LLM сервис
        try:
            llm_service = get_llm_service()
        except Exception as e:
            logger.exception(f"Ошибка при получении LLM сервиса: {e}")
            return JsonResponse({
                'success': False,
                'error': f'Ошибка при инициализации LLM сервиса: {str(e)}'
            }, status=500)
        
        # Генерируем выводы и рекомендации
        try:
            insights = llm_service.generate_insights(table_data, question)
            
            # Убеждаемся, что insights - это строка
            if not isinstance(insights, str):
                logger.warning(f"generate_insights вернул не строку: {type(insights)}, преобразуем в строку")
                if insights is None:
                    insights = "Не удалось сгенерировать выводы. Попробуйте еще раз."
                else:
                    insights = str(insights)
            
            return JsonResponse({
                'success': True,
                'insights': insights
            })
        except Exception as e:
            logger.exception(f"Ошибка при генерации выводов: {e}")
            return JsonResponse({
                'success': False,
                'error': f'Ошибка при генерации выводов: {str(e)}'
            }, status=500)
    
    except Exception as e:
        logger.exception(f"Неожиданная ошибка при генерации выводов: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Внутренняя ошибка сервера: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["POST"])
@json_response_on_error
def ai_generate_chart(request):
    """API endpoint для генерации предложения по графику через AI"""
    try:
        # Парсим JSON из тела запроса
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON: {e}")
            return JsonResponse({
                'success': False,
                'error': 'Неверный формат JSON в запросе'
            }, status=400)
        
        try:
            current_user = BitrixUser.objects.get(django_user=request.user)
            is_admin = current_user.is_admin if current_user else False
        except BitrixUser.DoesNotExist:
            current_user = None
            is_admin = False
        
        # Получаем сводку данных
        try:
            data_summary = _get_data_summary(request, current_user, is_admin)
        except Exception as e:
            logger.exception(f"Ошибка при получении сводки данных: {e}")
            return JsonResponse({
                'success': False,
                'error': f'Ошибка при получении данных: {str(e)}'
            }, status=500)
        
        # Получаем LLM сервис
        try:
            llm_service = get_llm_service()
        except Exception as e:
            logger.exception(f"Ошибка при получении LLM сервиса: {e}")
            return JsonResponse({
                'success': False,
                'error': f'Ошибка при инициализации LLM сервиса: {str(e)}'
            }, status=500)
        
        # Генерируем предложение по графику
        try:
            chart_suggestion = llm_service.generate_chart_suggestion(data_summary)
        except Exception as e:
            logger.exception(f"Ошибка при генерации графика через AI: {e}")
            error_msg = str(e)
            # Проверяем, связана ли ошибка с llama-server
            if 'llama-server' in error_msg.lower() or 'connection' in error_msg.lower():
                error_msg = 'Не удалось подключиться к llama-server. Убедитесь, что сервер запущен и доступен на указанном адресе.'
            return JsonResponse({
                'success': False,
                'error': f'Ошибка при генерации графика: {error_msg}'
            }, status=500)
        
        return JsonResponse({
            'success': True,
            'chart': chart_suggestion
        })
        
    except Exception as e:
        logger.exception(f"Неожиданная ошибка при генерации графика через AI: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Неожиданная ошибка: {str(e)}'
        }, status=500)


@login_required
@ensure_csrf_cookie
@require_http_methods(["GET"])
def get_csrf_token(request):
    """Получение CSRF токена для AJAX запросов"""
    from django.middleware.csrf import get_token
    token = get_token(request)
    return JsonResponse({'csrf_token': token})


@login_required
@require_http_methods(["GET"])
def ai_check_model_status(request):
    """Проверка статуса модели"""
    try:
        llm_service = get_llm_service()
        
        # Для llama-server проверяем наличие API базового URL, а не путь к модели
        if llm_service.model_type == 'llama-server':
            if not llm_service.llama_server_api_base:
                return JsonResponse({
                    'status': 'not_configured',
                    'message': 'Модель не настроена. Укажите LLAMA_SERVER_API_BASE в настройках (.env файл).'
                })
            
            # Для llama-server проверяем реальную доступность сервера и состояние модели
            try:
                import requests
                base_url = llm_service.llama_server_api_base.rstrip('/')
                logger.info(f"Проверка статуса llama-server на {base_url}")
                
                # Сначала проверяем корневой URL, где обычно показывается статус загрузки
                server_available = False
                model_loading = False
                
                try:
                    root_response = requests.get(base_url, timeout=5)
                    logger.info(f"Ответ от корневого URL: статус {root_response.status_code}")
                    
                    if root_response.status_code == 200:
                        # Проверяем содержимое ответа на наличие сообщения о загрузке
                        response_text = root_response.text.lower()
                        logger.debug(f"Содержимое ответа (первые 200 символов): {response_text[:200]}")
                        
                        # Проверяем различные варианты сообщений о загрузке
                        loading_indicators = [
                            'model is loading',
                            'please wait',
                            'the model is loading',
                            'loading',
                            'загрузка'
                        ]
                        
                        for indicator in loading_indicators:
                            if indicator in response_text:
                                logger.info(f"Найдено сообщение о загрузке: '{indicator}'")
                                model_loading = True
                                break
                        
                        if model_loading:
                            # Сервер доступен, но модель загружается
                            return JsonResponse({
                                'status': 'loading',
                                'message': 'Модель загружается, пожалуйста подождите...'
                            })
                        
                        # Если сервер отвечает, но нет сообщения о загрузке, сервер доступен
                        server_available = True
                        logger.info("Сервер доступен, модель не загружается")
                    else:
                        logger.warning(f"Корневой URL вернул статус {root_response.status_code}")
                        server_available = False
                        
                except requests.exceptions.ConnectionError as e:
                    # Сервер недоступен
                    logger.error(f"Ошибка подключения к llama-server: {e}")
                    return JsonResponse({
                        'status': 'error',
                        'message': 'llama-server недоступен. Убедитесь, что сервер запущен и доступен на указанном адресе.'
                    })
                except requests.exceptions.Timeout:
                    # Таймаут - возможно сервер загружается
                    logger.warning("Таймаут при проверке корневого URL - возможно модель загружается")
                    return JsonResponse({
                        'status': 'loading',
                        'message': 'Модель загружается, пожалуйста подождите...'
                    })
                except Exception as e:
                    logger.warning(f"Ошибка при проверке корневого URL: {e}")
                    server_available = False
                
                # Если корневой URL не дал результата, пробуем другие endpoints
                if not server_available:
                    logger.info("Проверка альтернативных endpoints")
                    health_endpoints = ["/health", "/api/health", "/v1/health"]
                    for health_endpoint in health_endpoints:
                        health_url = f"{base_url}{health_endpoint}"
                        try:
                            response = requests.get(health_url, timeout=3)
                            if response.status_code == 200:
                                server_available = True
                                # Проверяем содержимое ответа на наличие сообщения о загрузке
                                response_text = response.text.lower()
                                if 'model is loading' in response_text or 'please wait' in response_text or ('loading' in response_text and 'model' in response_text):
                                    logger.info(f"Найдено сообщение о загрузке в {health_endpoint}")
                                    return JsonResponse({
                                        'status': 'loading',
                                        'message': 'Модель загружается, пожалуйста подождите...'
                                    })
                                break
                        except Exception as e:
                            logger.debug(f"Ошибка при проверке {health_endpoint}: {e}")
                            continue
                
                if not server_available:
                    logger.error("llama-server недоступен - не удалось получить ответ ни от одного endpoint")
                    return JsonResponse({
                        'status': 'error',
                        'message': 'llama-server недоступен. Убедитесь, что сервер запущен и доступен на указанном адресе.'
                    })
                
                # Проверяем, загружена ли модель, делая тестовый запрос
                # Если модель еще загружается, запрос может не пройти или занять много времени
                if not llm_service._initialized:
                    # Пробуем сделать простой тестовый запрос для проверки готовности модели
                    try:
                        test_url = f"{llm_service.llama_server_api_base.rstrip('/')}/v1/completions"
                        test_payload = {
                            "model": "gpt-oss-120b",
                            "prompt": "test",
                            "max_tokens": 1,
                            "temperature": 0.1
                        }
                        test_response = requests.post(test_url, json=test_payload, timeout=5)
                        
                        # Проверяем содержимое ответа на наличие сообщения о загрузке
                        if test_response.status_code == 200:
                            # Проверяем, не содержит ли ответ сообщение о загрузке
                            try:
                                response_data = test_response.json()
                                response_text = str(response_data).lower()
                                if 'model is loading' in response_text or 'please wait' in response_text or 'loading' in response_text:
                                    return JsonResponse({
                                        'status': 'loading',
                                        'message': 'Модель загружается, пожалуйста подождите...'
                                    })
                            except:
                                pass
                            # Модель готова, можно инициализировать
                            pass
                        elif test_response.status_code == 503 or test_response.status_code == 502:
                            # Сервис недоступен - модель загружается
                            return JsonResponse({
                                'status': 'loading',
                                'message': 'Модель загружается, пожалуйста подождите...'
                            })
                        else:
                            # Проверяем текст ответа на наличие сообщения о загрузке
                            response_text = test_response.text.lower()
                            if 'model is loading' in response_text or 'please wait' in response_text:
                                return JsonResponse({
                                    'status': 'loading',
                                    'message': 'Модель загружается, пожалуйста подождите...'
                                })
                            # Другие ошибки - возможно модель загружается
                            return JsonResponse({
                                'status': 'loading',
                                'message': 'Модель загружается, пожалуйста подождите...'
                            })
                    except requests.exceptions.Timeout:
                        # Таймаут - модель, вероятно, еще загружается
                        return JsonResponse({
                            'status': 'loading',
                            'message': 'Модель загружается, пожалуйста подождите...'
                        })
                    except requests.exceptions.ConnectionError:
                        # Ошибка подключения - сервер недоступен
                        return JsonResponse({
                            'status': 'error',
                            'message': 'Не удалось подключиться к llama-server. Убедитесь, что сервер запущен.'
                        })
                    except Exception as e:
                        # Другие ошибки - возможно модель загружается
                        logger.warning(f"Ошибка при проверке готовности модели: {e}")
                        return JsonResponse({
                            'status': 'loading',
                            'message': 'Модель загружается, пожалуйста подождите...'
                        })
            except Exception as e:
                logger.warning(f"Не удалось проверить доступность llama-server: {e}")
                # Продолжаем проверку, возможно сервер доступен, но health endpoint не работает
        else:
            # Для других типов моделей проверяем путь к модели
            if not llm_service.model_path:
                return JsonResponse({
                    'status': 'not_configured',
                    'message': 'Модель не настроена. Укажите GPT_MODEL_PATH в настройках (.env файл).'
                })
        
        # Инициализируем модель, если она еще не инициализирована
        if not llm_service._initialized:
            initialized = llm_service.initialize()
            if not initialized:
                if llm_service.model_type == 'llama-server':
                    return JsonResponse({
                        'status': 'error',
                        'message': 'Не удалось подключиться к llama-server. Убедитесь, что llama-server запущен и доступен на указанном адресе.'
                    })
                else:
                    return JsonResponse({
                        'status': 'error',
                        'message': 'Не удалось инициализировать модель. Проверьте путь к модели и настройки.'
                    })
        
        response_data = {
            'status': 'ready',
            'message': 'Модель готова к работе',
            'model_type': llm_service.model_type,
        }
        
        # Добавляем информацию о пути или API в зависимости от типа модели
        if llm_service.model_type == 'llama-server':
            response_data['api_base'] = llm_service.llama_server_api_base
        else:
            response_data['model_path'] = llm_service.model_path
        
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.exception(f"Ошибка при проверке статуса модели: {e}")
        return JsonResponse({
            'status': 'error',
            'message': f'Ошибка: {str(e)}'
        }, status=500)


def _get_data_summary(request, current_user, is_admin):
    """Получение сводки данных для анализа"""
    # Получаем параметры фильтрации
    month = request.GET.get('month')
    year_param = request.GET.get('year')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    filter_type = request.GET.get('filter_type', 'month')
    
    # Базовые запросы
    sales = Sale.objects.select_related('manager', 'company').all()
    salary_payments = SalaryPayment.objects.select_related('manager').all()
    expenses = ProductionExpense.objects.select_related('employee', 'expense_type').all()
    
    # Фильтрация по пользователю
    if not is_admin and current_user:
        sales = sales.filter(manager=current_user)
        salary_payments = salary_payments.filter(manager=current_user)
    
    # Применяем фильтры по дате
    if filter_type == 'date_range' and date_from and date_to:
        try:
            date_start_naive = datetime.strptime(date_from, "%Y-%m-%d")
            date_end_naive = datetime.strptime(date_to, "%Y-%m-%d")
            tz = timezone.get_current_timezone()
            date_start = timezone.make_aware(date_start_naive, tz)
            date_end = timezone.make_aware(datetime.combine(date_end_naive, datetime.max.time()), tz)
            
            sales = sales.filter(closing_date__range=(date_start.date(), date_end.date()))
            salary_payments = salary_payments.filter(
                payment_datetime__gte=date_start, 
                payment_datetime__lte=date_end
            )
            expenses = expenses.filter(
                expense_date__gte=date_start, 
                expense_date__lte=date_end
            )
        except ValueError:
            pass
    elif year_param:
        try:
            year_int = int(year_param)
            sales = sales.filter(closing_date__year=year_int)
            salary_payments = salary_payments.filter(payment_datetime__year=year_int)
            expenses = expenses.filter(expense_date__year=year_int)
            
            if month:
                month_int = int(month)
                sales = sales.filter(closing_date__month=month_int)
                start_date = datetime(year_int, month_int, 1, tzinfo=timezone.get_current_timezone())
                if month_int == 12:
                    end_date = datetime(year_int + 1, 1, 1, tzinfo=timezone.get_current_timezone())
                else:
                    end_date = datetime(year_int, month_int + 1, 1, tzinfo=timezone.get_current_timezone())
                salary_payments = salary_payments.filter(
                    payment_datetime__gte=start_date, 
                    payment_datetime__lt=end_date
                )
                expenses = expenses.filter(
                    expense_date__gte=start_date, 
                    expense_date__lt=end_date
                )
        except (ValueError, TypeError):
            pass
    
    # Агрегируем данные
    total_sales = sales.aggregate(total=Sum('sale'))['total'] or 0
    total_salary = sales.aggregate(total=Sum('salary'))['total'] or 0
    total_salary_paid = salary_payments.aggregate(total=Sum('amount'))['total'] or 0
    total_expenses = expenses.aggregate(total=Sum('amount'))['total'] or 0
    sales_count = sales.count()
    payments_count = salary_payments.count()
    expenses_count = expenses.count()
    
    # Средние значения
    avg_sale = sales.aggregate(avg=Avg('sale'))['avg'] or 0
    avg_salary = sales.aggregate(avg=Avg('salary'))['avg'] or 0
    avg_expense = expenses.aggregate(avg=Avg('amount'))['avg'] or 0
    
    # Данные по менеджерам
    manager_stats = sales.values('manager__name', 'manager__last_name').annotate(
        total_sales=Sum('sale'),
        total_salary=Sum('salary'),
        count=Count('id')
    ).order_by('-total_sales')[:10]
    
    manager_data = [
        {
            'name': f"{m.get('manager__last_name', '')} {m.get('manager__name', '')}",
            'total_sales': float(m['total_sales'] or 0),
            'total_salary': float(m['total_salary'] or 0),
            'count': m['count']
        }
        for m in manager_stats
    ]
    
    # Данные по месяцам (только записи с валидными датами)
    # Используем Python для группировки, чтобы избежать проблем с часовыми поясами в БД
    monthly_sales = sales.filter(closing_date__isnull=False).select_related('manager', 'company')
    monthly_dict = {}
    for sale in monthly_sales:
        try:
            if sale.closing_date:
                month_key = sale.closing_date.strftime('%Y-%m')
                if month_key not in monthly_dict:
                    monthly_dict[month_key] = {
                        'total_sales': 0,
                        'total_salary': 0,
                        'count': 0
                    }
                monthly_dict[month_key]['total_sales'] += float(sale.sale or 0)
                monthly_dict[month_key]['total_salary'] += float(sale.salary or 0)
                monthly_dict[month_key]['count'] += 1
        except (AttributeError, ValueError, TypeError):
            continue
    
    monthly_data = [
        {
            'month': month_key,
            'total_sales': float(data['total_sales']),
            'total_salary': float(data['total_salary']),
            'count': data['count']
        }
        for month_key, data in sorted(monthly_dict.items())[:12]
    ]
    
    # Данные по типам расходов
    expense_type_stats = expenses.values('expense_type__name').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')[:10]
    
    expense_type_data = [
        {
            'type': e['expense_type__name'],
            'total': float(e['total'] or 0),
            'count': e['count']
        }
        for e in expense_type_stats
    ]
    
    # Данные по расходам по месяцам (только записи с валидными датами)
    # Используем Python для группировки, чтобы избежать проблем с часовыми поясами в БД
    expense_monthly_list = expenses.filter(expense_date__isnull=False).select_related('employee', 'expense_type')
    expense_monthly_dict = {}
    for expense in expense_monthly_list:
        try:
            if expense.expense_date:
                month_key = expense.expense_date.strftime('%Y-%m')
                if month_key not in expense_monthly_dict:
                    expense_monthly_dict[month_key] = {
                        'total': 0,
                        'count': 0
                    }
                expense_monthly_dict[month_key]['total'] += float(expense.amount or 0)
                expense_monthly_dict[month_key]['count'] += 1
        except (AttributeError, ValueError, TypeError):
            continue
    
    expense_monthly_data = [
        {
            'month': month_key,
            'total': float(data['total']),
            'count': data['count']
        }
        for month_key, data in sorted(expense_monthly_dict.items())[:12]
    ]
    
    # Данные по расходам по сотрудникам
    expense_employee_stats = expenses.values('employee__name').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')[:10]
    
    expense_employee_data = [
        {
            'employee': e['employee__name'],
            'total': float(e['total'] or 0),
            'count': e['count']
        }
        for e in expense_employee_stats
    ]
    
    # Данные по компаниям (ВСЕ компании, без ограничений)
    company_stats = sales.values('company__title').annotate(
        total_sales=Sum('sale'),
        total_salary=Sum('salary'),
        count=Count('id')
    ).order_by('-total_sales')  # Все компании по сумме продаж
    
    company_data = [
        {
            'company': c['company__title'] or 'Без компании',
            'total_sales': float(c['total_sales'] or 0),
            'total_salary': float(c['total_salary'] or 0),
            'count': c['count']
        }
        for c in company_stats
    ]
    
    # Также сортируем по количеству сделок (топ-10 для быстрого доступа)
    company_by_count = sorted(company_data, key=lambda x: x['count'], reverse=True)[:10]
    
    # Детальные данные о продажах по менеджерам и месяцам (для ответов на конкретные вопросы)
    # Словарь русских названий месяцев
    month_names_ru = {
        1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
        5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
        9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь',
    }
    
    # Данные по менеджерам и месяцам (используем Python для группировки)
    manager_monthly_sales = sales.filter(closing_date__isnull=False).select_related('manager', 'company')
    manager_monthly_dict = {}
    for sale in manager_monthly_sales:
        try:
            if sale.closing_date and sale.manager:
                manager_name = f"{sale.manager.last_name or ''} {sale.manager.name or ''}".strip()
                month_key = sale.closing_date.strftime('%Y-%m')
                dict_key = f"{manager_name}|{month_key}"
                
                if dict_key not in manager_monthly_dict:
                    manager_monthly_dict[dict_key] = {
                        'manager': manager_name,
                        'month': month_key,
                        'month_name_ru': f"{month_names_ru.get(sale.closing_date.month, '')} {sale.closing_date.year}".strip(),
                        'total_sales': 0,
                        'total_salary': 0,
                        'count': 0
                    }
                manager_monthly_dict[dict_key]['total_sales'] += float(sale.sale or 0)
                manager_monthly_dict[dict_key]['total_salary'] += float(sale.salary or 0)
                manager_monthly_dict[dict_key]['count'] += 1
        except (AttributeError, ValueError, TypeError):
            continue
    
    # Сортируем по менеджеру и месяцу
    manager_monthly_data = [
        {
            'manager': data['manager'],
            'month': data['month'],
            'month_name_ru': data['month_name_ru'],
            'total_sales': float(data['total_sales']),
            'total_salary': float(data['total_salary']),
            'count': data['count']
        }
        for dict_key, data in sorted(manager_monthly_dict.items(), key=lambda x: (x[1]['manager'], x[1]['month']))
    ]
    
    # Детальные данные о продажах (ограничиваем до 50 для предотвращения перегрузки промпта)
    detailed_sales = sales.select_related('manager', 'company').order_by('-closing_date', '-id')[:50]
    detailed_sales_data = []
    for sale in detailed_sales:
        sale_data = {
            'id': sale.id,
            'id_number': sale.id_number,  # Счет-фактура (ID номер)
            'manager': f"{sale.manager.last_name if sale.manager else ''} {sale.manager.name if sale.manager else ''}".strip(),
            'manager_id': sale.manager.user_id if sale.manager else None,
            'company': sale.company.title if sale.company else '',
            'company_id': sale.company.company_id if sale.company else None,
            'sale': float(sale.sale or 0),  # Сумма продажи
            'salary': float(sale.salary or 0),  # Зарплата
            'account_number': sale.account_number,  # Номер счета
            'closing_date': sale.closing_date.strftime('%Y-%m-%d') if sale.closing_date else '',
            'closing_date_formatted': sale.closing_date.strftime('%d.%m.%Y') if sale.closing_date else '',  # Например: "15.07.2025"
            'title': sale.title  # Название сделки
        }
        # Добавляем русское название месяца для лучшего сопоставления
        if sale.closing_date:
            month_ru = month_names_ru.get(sale.closing_date.month, '')
            sale_data['month_name_ru'] = f"{month_ru} {sale.closing_date.year}" if month_ru else ''
            sale_data['month'] = sale.closing_date.strftime('%Y-%m')
        else:
            sale_data['month_name_ru'] = ''
            sale_data['month'] = ''
        detailed_sales_data.append(sale_data)
    
    # Все менеджеры со всеми полями
    all_managers = BitrixUser.objects.all()
    all_managers_data = []
    for manager in all_managers:
        all_managers_data.append({
            'id': manager.id,
            'user_id': manager.user_id,
            'name': manager.name,
            'last_name': manager.last_name,
            'full_name': f"{manager.last_name} {manager.name}".strip(),
            'is_admin': manager.is_admin
        })
    
    # Все компании со всеми полями
    all_companies = Company.objects.all()
    all_companies_data = []
    for company in all_companies:
        all_companies_data.append({
            'id': company.id,
            'company_id': company.company_id,
            'title': company.title
        })
    
    # Все зарплатные выплаты (детальные данные, ограничиваем до 50)
    all_salary_payments = salary_payments.select_related('manager').order_by('-payment_datetime')[:50]
    all_salary_payments_data = []
    for payment in all_salary_payments:
        try:
            if payment.payment_datetime:
                payment_datetime_str = payment.payment_datetime.strftime('%Y-%m-%d %H:%M:%S')
                payment_date_str = payment.payment_datetime.strftime('%Y-%m-%d')
                payment_date_formatted_str = payment.payment_datetime.strftime('%d.%m.%Y')
                year = payment.payment_datetime.year
                month = payment.payment_datetime.month
                month_name_ru = month_names_ru.get(month, '')
            else:
                payment_datetime_str = ''
                payment_date_str = ''
                payment_date_formatted_str = ''
                year = None
                month = None
                month_name_ru = ''
        except (AttributeError, ValueError, TypeError):
            payment_datetime_str = ''
            payment_date_str = ''
            payment_date_formatted_str = ''
            year = None
            month = None
            month_name_ru = ''
        
        all_salary_payments_data.append({
            'id': payment.id,
            'manager': f"{payment.manager.last_name if payment.manager else ''} {payment.manager.name if payment.manager else ''}".strip(),
            'manager_id': payment.manager.user_id if payment.manager else None,
            'amount': float(payment.amount or 0),
            'payment_datetime': payment_datetime_str,
            'payment_date': payment_date_str,
            'payment_date_formatted': payment_date_formatted_str,
            'year': year,
            'month': month,
            'month_name_ru': month_name_ru
        })
    
    # Все расходы (детальные данные, ограничиваем до 50, только с валидными датами)
    all_expenses = expenses.filter(
        expense_date__isnull=False
    ).select_related('employee', 'expense_type').order_by('-expense_date')[:50]
    all_expenses_data = []
    for expense in all_expenses:
        try:
            if expense.expense_date:
                expense_date_str = expense.expense_date.strftime('%Y-%m-%d %H:%M:%S')
                expense_date_formatted_str = expense.expense_date.strftime('%d.%m.%Y')
                year = expense.expense_date.year
                month = expense.expense_date.month
                month_name_ru = month_names_ru.get(month, '')
            else:
                expense_date_str = ''
                expense_date_formatted_str = ''
                year = None
                month = None
                month_name_ru = ''
        except (AttributeError, ValueError, TypeError):
            expense_date_str = ''
            expense_date_formatted_str = ''
            year = None
            month = None
            month_name_ru = ''
        
        all_expenses_data.append({
            'id': expense.id,
            'employee': expense.employee.name if expense.employee else '',
            'expense_type': expense.expense_type.name if expense.expense_type else '',
            'amount': float(expense.amount or 0),
            'expense_date': expense_date_str,
            'expense_date_formatted': expense_date_formatted_str,
            'year': year,
            'month': month,
            'month_name_ru': month_name_ru,
            'comment': expense.comment or ''
        })
    
    # Все сотрудники
    all_employees = Employee.objects.all()
    all_employees_data = [{'id': emp.id, 'name': emp.name} for emp in all_employees]
    
    # Все типы расходов
    all_expense_types = ExpenseType.objects.all()
    all_expense_types_data = [{'id': et.id, 'name': et.name} for et in all_expense_types]
    
    # Формируем сводку
    summary = {
        'summary': {
            'total_sales': float(total_sales),
            'total_salary': float(total_salary),
            'total_salary_paid': float(total_salary_paid),
            'salary_left': float(total_salary - total_salary_paid),
            'total_expenses': float(total_expenses),
            'sales_count': sales_count,
            'payments_count': payments_count,
            'expenses_count': expenses_count,
            'avg_sale': float(avg_sale),
            'avg_salary': float(avg_salary),
            'avg_expense': float(avg_expense),
            'expenses_to_sales_ratio': float(total_expenses / total_sales * 100) if total_sales > 0 else 0,
        },
        'managers': manager_data,  # Топ менеджеров по продажам
        'all_managers': all_managers_data,  # ВСЕ менеджеры со всеми полями (id, user_id, name, last_name, is_admin)
        'monthly': monthly_data,
        'manager_monthly': manager_monthly_data,  # Детальные данные по менеджерам и месяцам
        'detailed_sales': detailed_sales_data,  # Детальные данные о продажах (id, id_number, account_number, title и т.д.)
        'expense_types': expense_type_data,  # Топ типов расходов
        'expense_monthly': expense_monthly_data,  # Расходы по месяцам
        'expense_employees': expense_employee_data,  # Расходы по сотрудникам
        'all_expense_types': all_expense_types_data,  # ВСЕ типы расходов
        'companies': company_data,  # Топ компаний по сумме продаж
        'companies_by_count': company_by_count,  # Топ компаний по количеству сделок
        'all_companies': all_companies_data,  # ВСЕ компании со всеми полями (id, company_id, title)
        'all_salary_payments': all_salary_payments_data,  # ВСЕ зарплатные выплаты (id, manager, amount, payment_datetime)
        'all_expenses': all_expenses_data,  # ВСЕ расходы (id, employee, expense_type, amount, expense_date, comment)
        'all_employees': all_employees_data,  # ВСЕ сотрудники
        'period': {
            'filter_type': filter_type,
            'year': year_param,
            'month': month,
            'date_from': date_from,
            'date_to': date_to
        }
    }
    
    return summary
