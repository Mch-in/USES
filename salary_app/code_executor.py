"""
Модуль для безопасного выполнения Python кода, сгенерированного GPT-OSS-120B
"""
import io
import sys
import json
import re
import logging
from typing import Dict, Any, Optional, List
from contextlib import redirect_stdout, redirect_stderr

logger = logging.getLogger(__name__)


class CodeExecutor:
    """Класс для безопасного выполнения Python кода"""
    
    # Разрешенные модули для импорта
    ALLOWED_MODULES = {
        'json', 'datetime', 'collections', 'itertools', 'operator',
        'math', 'statistics', 'decimal', 'fractions', 'time'
    }
    
    # Запрещенные функции и операторы (__import__ разрешен через безопасную обертку)
    FORBIDDEN_NAMES = {
        'eval', 'exec', 'compile', 'open', 'file',
        'input', 'raw_input', 'exit', 'quit', 'help', 'license',
        'credits', 'copyright', 'vars', 'dir', 'globals', 'locals',
        '__builtins__', '__file__', '__name__', '__package__'
    }
    
    def __init__(self, data_summary: Dict[str, Any], models=None):
        """
        Инициализация исполнителя кода
        
        Args:
            data_summary: Сводка данных для анализа
            models: Словарь с Django моделями для доступа к БД
        """
        self.data_summary = data_summary
        self.models = models or {}
        self.safe_globals = self._create_safe_globals()
        self.safe_locals = {}
    
    def _safe_import(self, name, globals=None, locals=None, fromlist=(), level=0):
        """Безопасная обертка для __import__, разрешающая только Django модули"""
        import builtins
        
        # Разрешенные модули для импорта
        allowed_modules = {
            'django.db.models',
            'django.utils',
            'django.db',
            'django',
            'datetime',
            'json',
            'collections',
            'itertools',
            'operator',
            'math',
            'statistics',
            'decimal',
            'fractions',
            'time',
        }
        
        # Проверяем, разрешен ли модуль
        # Разрешаем модули, которые точно в списке разрешенных, или начинаются с разрешенного префикса
        is_allowed = (
            name in allowed_modules or 
            any(name.startswith(allowed + '.') for allowed in allowed_modules) or
            any(name == allowed.split('.')[0] for allowed in allowed_modules if '.' in allowed)
        )
        
        if is_allowed:
            # Используем встроенный __import__ из builtins
            return builtins.__import__(name, globals, locals, fromlist, level)
        else:
            raise ImportError(f"Импорт модуля '{name}' запрещен. Разрешены только Django модули и стандартные библиотеки.")
    
    def _create_safe_globals(self) -> Dict[str, Any]:
        """Создание безопасного глобального контекста"""
        from django.db.models import Sum, Count, Avg, Max, Min, Q, F
        from django.utils import timezone
        from datetime import datetime, timedelta
        
        safe_globals = {
            '__builtins__': {
                'len': len,
                'str': str,
                'int': int,
                'float': float,
                'bool': bool,
                'list': list,
                'dict': dict,
                'tuple': tuple,
                'set': set,
                'sum': sum,
                'max': max,
                'min': min,
                'abs': abs,
                'round': round,
                'sorted': sorted,
                'reversed': reversed,
                'enumerate': enumerate,
                'zip': zip,
                'range': range,
                'print': print,
                'json': json,
                '__import__': self._safe_import,  # Безопасная обертка для импорта
            },
            'data': self.data_summary,
            'json': json,
            # Django ORM функции
            'Sum': Sum,
            'Count': Count,
            'Avg': Avg,
            'Max': Max,
            'Min': Min,
            'Q': Q,
            'F': F,
            'timezone': timezone,
            'datetime': datetime,
            'timedelta': timedelta,
        }
        
        # Добавляем Django модели
        for model_name, model_class in self.models.items():
            safe_globals[model_name] = model_class
        
        # Добавляем разрешенные модули
        for module_name in self.ALLOWED_MODULES:
            try:
                safe_globals[module_name] = __import__(module_name)
            except ImportError:
                pass
        
        return safe_globals
    
    def _clean_code(self, code: str) -> str:
        """Очистка кода от недопустимых символов и мусора"""
        import unicodedata
        import string
        
        # Разрешенные символы: ASCII printable + кириллица + основные знаки препинания
        allowed_chars = set(string.printable + 'абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ')
        
        cleaned_lines = []
        for line in code.split('\n'):
            # Ищем, где заканчивается валидный код (до мусора)
            valid_end = len(line)
            found_invalid = False
            
            for i, char in enumerate(line):
                # Проверяем, является ли символ допустимым
                if char not in allowed_chars:
                    # Проверяем категорию Unicode для специальных символов
                    if ord(char) >= 0x2000:
                        cat = unicodedata.category(char)
                        # Разрешаем только определенные категории Unicode
                        if cat not in ['Lu', 'Ll', 'Nd', 'Po', 'Pd', 'Pe', 'Ps', 'Sm', 'So', 'Zs', 'Mn', 'Mc']:
                            # Нашли недопустимый символ - обрезаем строку здесь
                            valid_end = i
                            found_invalid = True
                            break
                    else:
                        # Символ не в allowed_chars и не в разрешенных категориях
                        valid_end = i
                        found_invalid = True
                        break
            
            # Обрезаем строку до валидного конца
            cleaned_line = line[:valid_end].rstrip()
            
            # Если строка не пустая или это первая строка, добавляем её
            if cleaned_line.strip() or not cleaned_lines:
                cleaned_lines.append(cleaned_line)
            
            # Если нашли недопустимый символ, НЕ прекращаем обработку сразу
            # Пробуем продолжить, так как мусор может быть в середине строки
            # Прекращаем только если нашли недопустимый символ в начале строки
            # (это обычно означает, что начался мусор)
            if found_invalid and i == 0 and not cleaned_line.strip():
                # Если недопустимый символ в начале пустой строки - это мусор
                break
        
        return '\n'.join(cleaned_lines)
    
    def _fix_fstring_braces(self, code: str) -> str:
        """Исправление двойных фигурных скобок в f-строках и обычных словарях
        
        В промпте используются {{ и }} для экранирования, но в реальном коде
        они должны быть одинарными { и }
        """
        # Сначала исправляем двойные скобки в f-строках
        lines = code.split('\n')
        fixed_lines = []
        
        for line in lines:
            fixed_line = line
            
            # Проверяем, есть ли в строке f-строка
            if 'f"' in line or "f'" in line:
                # Исправляем двойные скобки в f-строках
                # В f-строках {{ должно быть { для экранирования, но модель может генерировать {{ неправильно
                # Заменяем {{ на { и }} на } в f-строках
                fixed_line = fixed_line.replace('{{', '{')
                fixed_line = fixed_line.replace('}}', '}')
                logger.debug(f"Исправлена f-строка: {line[:100]} -> {fixed_line[:100]}")
            
            fixed_lines.append(fixed_line)
        
        fixed_code = '\n'.join(fixed_lines)
        
        # Теперь исправляем двойные скобки в обычных словарях (не в f-строках)
        # Это нужно, потому что модель может генерировать result.append({{ вместо result.append({
        # После исправления f-строк, все оставшиеся двойные скобки - это ошибки, которые нужно исправить
        if '{{' in fixed_code or '}}' in fixed_code:
            # Простая замена всех оставшихся двойных скобок на одинарные
            # Это безопасно, потому что:
            # 1. В f-строках двойные скобки уже исправлены на первом этапе
            # 2. В обычных словарях двойные скобки - это ошибка, которую нужно исправить
            original_code = fixed_code
            fixed_code = fixed_code.replace('{{', '{')
            fixed_code = fixed_code.replace('}}', '}')
            
            if original_code != fixed_code:
                logger.info(f"Исправлены двойные скобки в обычных словарях: {original_code.count('{{') + original_code.count('}}')} замен")
        
        return fixed_code
    
    def extract_code_from_response(self, response: str) -> Optional[str]:
        """
        Извлечение Python кода из ответа модели
        
        Args:
            response: Ответ модели, который может содержать код в markdown блоках
            
        Returns:
            Извлеченный код или None, если код не найден
        """
        # Ищем код в markdown блоках ```python ... ```
        # Паттерн для поиска блоков кода
        patterns = [
            r'```python\s*\n(.*?)\n```',  # ```python ... ```
            r'```\s*\n(.*?)\n```',  # ``` ... ```
            r'<code>(.*?)</code>',  # HTML теги
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, response, re.DOTALL)
            if matches:
                code = matches[0].strip()
                if code and len(code) > 10:  # Минимальная длина кода
                    original_length = len(code)
                    # Очищаем код от недопустимых символов
                    code = self._clean_code(code)
                    # Исправляем двойные фигурные скобки в f-строках
                    code = self._fix_fstring_braces(code)
                    cleaned_length = len(code)
                    if original_length != cleaned_length:
                        logger.warning(f"Код был очищен: {original_length} -> {cleaned_length} символов (удалено {original_length - cleaned_length} символов)")
                    logger.info(f"Найден код в ответе модели (длина: {len(code)} символов, строк: {len(code.split(chr(10)))}):")
                    # Логируем код для отладки
                    logger.info(f"Первые 1000 символов кода:\n{code[:1000]}")
                    if len(code) > 1000:
                        logger.info(f"... (еще {len(code) - 1000} символов)")
                    return code
        
        # Если код не найден в блоках, проверяем, не является ли весь ответ кодом
        # (если он начинается с ключевых слов Python)
        python_keywords = ['import ', 'from ', 'def ', 'class ', 'data =', 'result =']
        if any(response.strip().startswith(keyword) for keyword in python_keywords):
            logger.info("Весь ответ похож на Python код")
            code = response.strip()
            # Очищаем код от недопустимых символов
            code = self._clean_code(code)
            # Исправляем двойные фигурные скобки в f-строках
            code = self._fix_fstring_braces(code)
            logger.debug(f"Первые 500 символов кода: {code[:500]}")
            return code
        
        return None
    
    def execute_code(self, code: str) -> Dict[str, Any]:
        """
        Безопасное выполнение Python кода
        
        Args:
            code: Python код для выполнения
            
        Returns:
            Словарь с результатами выполнения:
            {
                'success': bool,
                'result': Any,  # Результат выполнения (если есть переменная result)
                'output': str,  # Вывод print
                'error': str,  # Ошибка (если есть)
                'data': Any  # Данные для таблицы (если код возвращает данные)
            }
        """
        # Проверка на запрещенные конструкции
        if self._check_forbidden(code):
            return {
                'success': False,
                'error': 'Код содержит запрещенные конструкции',
                'output': '',
                'result': None,
                'data': None
            }
        
        # Удаляем импорты моделей (они уже доступны в контексте)
        code = self._remove_model_imports(code)
        # Очищаем код от недопустимых символов перед проверкой синтаксиса
        code = self._clean_code(code)
        # Исправляем двойные фигурные скобки в f-строках
        code = self._fix_fstring_braces(code)
        
        # Проверяем синтаксис перед выполнением
        try:
            compile(code, '<string>', 'exec')
        except SyntaxError as syntax_err:
            error_msg = f"Синтаксическая ошибка: {str(syntax_err)}"
            logger.error(f"Ошибка выполнения кода: {error_msg}")
            logger.error(f"Проблемный код (первые 1000 символов): {code[:1000]}")
            
            # Если ошибка связана с недопустимыми символами, пытаемся их удалить более агрессивно
            if "invalid character" in str(syntax_err).lower():
                logger.warning("Обнаружены недопустимые символы. Пытаемся удалить их...")
                # Более агрессивная очистка
                import string
                allowed_chars = set(string.printable + 'абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ')
                cleaned_code = ''.join(c if c in allowed_chars or ord(c) < 0x2000 else ' ' for c in code)
                # Удаляем множественные пробелы
                cleaned_code = re.sub(r' +', ' ', cleaned_code)
                try:
                    compile(cleaned_code, '<string>', 'exec')
                    logger.info("Код очищен от недопустимых символов, используем очищенную версию")
                    code = cleaned_code
                except SyntaxError:
                    logger.warning("Не удалось очистить код от недопустимых символов")
            
            # Пытаемся найти и исправить проблему с незакрытыми скобками
            if "'{' was never closed" in str(syntax_err) or "unterminated string" in str(syntax_err).lower():
                logger.warning("Обнаружена проблема с незакрытыми скобками или строками. Пытаемся исправить...")
                # Пробуем найти незакрытые фигурные скобки в f-строках
                # Это может быть из-за того, что модель неправильно экранировала скобки
                fixed_code = self._try_fix_fstring_braces(code)
                if fixed_code != code:
                    logger.info("Попытка исправления кода...")
                    try:
                        compile(fixed_code, '<string>', 'exec')
                        logger.info("Код исправлен, используем исправленную версию")
                        code = fixed_code
                    except SyntaxError:
                        logger.warning("Не удалось исправить код автоматически")
            
            if "'{' was never closed" in str(syntax_err) or "invalid character" in str(syntax_err).lower():
                return {
                    'success': False,
                    'error': error_msg,
                    'output': '',
                    'result': None,
                    'data': None
                }
        
        # Перехватываем stdout и stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        
        try:
            # Логируем код перед выполнением для отладки
            code_lines = code.split('\n')
            logger.info(f"Выполняем код (длина: {len(code)} символов, строк: {len(code_lines)}):")
            logger.info(f"Полный код:\n{code}")
            logger.info(f"Количество строк: {len(code_lines)}")
            
            # Выполняем код в безопасном контексте
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                # Компилируем код (повторно, если был исправлен)
                compiled_code = compile(code, '<string>', 'exec')
                
                # Выполняем код
                exec(compiled_code, self.safe_globals, self.safe_locals)
            
            # Получаем вывод
            output = stdout_capture.getvalue()
            error_output = stderr_capture.getvalue()
            
            # Пытаемся получить результат
            result = None
            data = None
            
            # Логируем все переменные в safe_locals для отладки
            logger.debug(f"Переменные в safe_locals после выполнения: {list(self.safe_locals.keys())}")
            
            # Проверяем, есть ли переменная result в locals
            if 'result' in self.safe_locals:
                result = self.safe_locals['result']
                logger.info(f"Найдена переменная result: тип={type(result)}, длина={len(result) if isinstance(result, (list, dict, str)) else 'N/A'}")
            elif 'data' in self.safe_locals:
                data = self.safe_locals['data']
                logger.info(f"Найдена переменная data: тип={type(data)}, длина={len(data) if isinstance(data, (list, dict, str)) else 'N/A'}")
            elif 'table_data' in self.safe_locals:
                data = self.safe_locals['table_data']
                logger.info(f"Найдена переменная table_data: тип={type(data)}")
            else:
                # Проверяем все переменные, которые могут содержать данные
                logger.warning(f"Переменная result не найдена. Доступные переменные: {list(self.safe_locals.keys())}")
                # Пробуем найти любую переменную, которая может быть результатом
                for var_name in ['result', 'data', 'table_data', 'results', 'output_data']:
                    if var_name in self.safe_locals:
                        result = self.safe_locals[var_name]
                        logger.info(f"Найдена альтернативная переменная {var_name}: тип={type(result)}")
                        break
            
            # Если есть ошибка в stderr, но код выполнился
            if error_output:
                logger.warning(f"Код выполнился, но есть предупреждения: {error_output}")
            
            # Логируем вывод, если есть
            if output:
                logger.debug(f"Вывод кода (stdout): {output[:500]}")
            
            # Если result пустой список или None, но код выполнился успешно
            if result is None and data is None:
                logger.warning("Код выполнился успешно, но переменные result и data не найдены или пусты")
                # Возможно, данные в stdout
                if output and output.strip():
                    logger.info(f"Возможно, данные в stdout: {output[:200]}")
            elif isinstance(result, list) and len(result) == 0:
                logger.warning(f"Переменная result найдена, но список пуст. Проверяем код...")
                # Проверяем, есть ли в коде циклы, которые должны заполнять result
                if 'for ' in code and 'result.append' in code:
                    logger.warning("В коде есть цикл for и result.append, но result пуст. Возможно:")
                    logger.warning("1. Цикл не выполнился (нет данных в БД)")
                    logger.warning("2. Код был обрезан до выполнения цикла")
                    logger.warning("3. Условие в цикле не выполняется")
                    
                    # Показываем, где находится result.append в коде
                    append_positions = []
                    for i, line in enumerate(code.split('\n'), 1):
                        if 'result.append' in line:
                            append_positions.append((i, line.strip()[:100]))
                    if append_positions:
                        logger.info(f"Найдено {len(append_positions)} вхождений result.append:")
                        for line_num, line_content in append_positions[:5]:  # Показываем первые 5
                            logger.info(f"  Строка {line_num}: {line_content}")
                    
                    # Проверяем, есть ли запросы к БД
                    db_queries = []
                    for query_pattern in ['objects.all()', 'objects.filter', 'objects.get', 'objects.values', '.annotate']:
                        if query_pattern in code:
                            db_queries.append(query_pattern)
                    if db_queries:
                        logger.info(f"В коде есть запросы к БД: {', '.join(db_queries)}")
                    else:
                        logger.warning("В коде НЕТ запросов к БД - возможно, код неполный")
                        
                elif 'result.append' not in code:
                    logger.warning("В коде нет result.append - возможно, код неполный или обрезан")
                    # Показываем последние строки кода
                    code_lines = code.split('\n')
                    last_lines = code_lines[-5:] if len(code_lines) > 5 else code_lines
                    logger.info(f"Последние {len(last_lines)} строк кода:")
                    for i, line in enumerate(last_lines, max(1, len(code_lines) - len(last_lines) + 1)):
                        logger.info(f"  {i}: {line}")
            
            return {
                'success': True,
                'result': result,
                'data': data,
                'output': output,
                'error': error_output if error_output else None
            }
            
        except SyntaxError as e:
            error_msg = f"Синтаксическая ошибка: {str(e)}"
            logger.error(f"Ошибка выполнения кода: {error_msg}")
            return {
                'success': False,
                'error': error_msg,
                'output': stdout_capture.getvalue(),
                'result': None,
                'data': None
            }
        except Exception as e:
            error_msg = f"Ошибка выполнения: {str(e)}"
            error_type = type(e).__name__
            logger.error(f"Ошибка выполнения кода: {error_msg} (тип: {error_type})")
            
            # Логируем код, который вызвал ошибку
            logger.error(f"Код, который вызвал ошибку (первые 2000 символов):\n{code[:2000]}")
            
            # Специальная обработка для "unhashable type: 'dict'"
            if "unhashable type: 'dict'" in str(e) or "unhashable type" in str(e).lower():
                logger.warning("Обнаружена ошибка 'unhashable type: dict'. Возможно, в коде используется словарь как ключ.")
                logger.warning("Это может быть в .values() или других местах Django ORM.")
                # Пытаемся найти проблемную строку
                import traceback
                tb_str = traceback.format_exc()
                logger.error(f"Traceback:\n{tb_str}")
                
                # Пытаемся исправить код - заменяем двойные фигурные скобки в f-строках
                # Проблема может быть в том, что в промпте используются {{, но при извлечении они неправильно обрабатываются
                fixed_code = code
                # Ищем f-строки с двойными скобками и исправляем их
                import re
                # Заменяем {{ на { и }} на } в f-строках
                lines = fixed_code.split('\n')
                fixed_lines = []
                for line in lines:
                    # Если это f-строка с двойными скобками, исправляем
                    if 'f"' in line or "f'" in line:
                        # Заменяем {{ на { и }} на } только внутри f-строки
                        # Это сложно, поэтому просто попробуем выполнить код с исправлением
                        pass
                    fixed_lines.append(line)
                
                # Попробуем другой подход - проверим, нет ли проблем с .values()
                # Иногда ошибка возникает, если в .values() передается словарь вместо строки
                if '.values(' in code:
                    logger.warning("В коде есть .values() - проверяем на использование словарей")
                    # Пробуем найти проблемное место
                    for i, line in enumerate(code.split('\n'), 1):
                        if '.values(' in line and ('dict' in line.lower() or '{' in line):
                            logger.warning(f"Возможная проблема на строке {i}: {line.strip()}")
            
            return {
                'success': False,
                'error': error_msg,
                'error_type': error_type,
                'output': stdout_capture.getvalue(),
                'result': None,
                'data': None
            }
    
    def _check_forbidden(self, code: str) -> bool:
        """Проверка кода на запрещенные конструкции"""
        code_lower = code.lower()
        
        # Проверяем запрещенные имена
        for forbidden in self.FORBIDDEN_NAMES:
            if forbidden in code_lower:
                logger.warning(f"Обнаружена запрещенная конструкция: {forbidden}")
                return True
        
        # Проверяем опасные операции (__import__ разрешен через безопасную обертку)
        dangerous_patterns = [
            'import os', 'import sys', 'import subprocess',
            'eval(', 'exec(', 'compile(',
            'open(', 'file(', '__file__', '__name__'
        ]
        
        for pattern in dangerous_patterns:
            if pattern in code_lower:
                logger.warning(f"Обнаружен опасный паттерн: {pattern}")
                return True
        
        return False
    
    def _try_fix_fstring_braces(self, code: str) -> str:
        """Попытка исправить проблемы с незакрытыми фигурными скобками в f-строках"""
        lines = code.split('\n')
        fixed_lines = []
        in_fstring = False
        brace_count = 0
        
        for line in lines:
            # Проверяем, является ли строка f-строкой
            if 'f"' in line or "f'" in line:
                in_fstring = True
                # Считаем открывающие и закрывающие скобки
                brace_count = line.count('{') - line.count('}')
            elif in_fstring and ('"' in line or "'" in line):
                # Конец f-строки
                in_fstring = False
                brace_count = 0
            
            # Если в f-строке не хватает закрывающих скобок, пытаемся добавить
            if in_fstring and brace_count > 0:
                # Пробуем добавить недостающие закрывающие скобки в конце строки
                if line.strip().endswith('}') or line.strip().endswith('",') or line.strip().endswith("',"):
                    pass  # Скобка уже есть
                elif '{' in line and '}' not in line:
                    # Если есть открывающая скобка, но нет закрывающей
                    line = line.rstrip() + '}' * brace_count
            
            fixed_lines.append(line)
        
        return '\n'.join(fixed_lines)
    
    def _remove_model_imports(self, code: str) -> str:
        """
        Удаляет строки импорта моделей из кода, так как модели уже доступны в контексте.
        
        Args:
            code: Исходный код
            
        Returns:
            Код без импортов моделей
        """
        model_names = ['Sale', 'SalaryPayment', 'ProductionExpense', 'BitrixUser', 
                      'Company', 'Employee', 'ExpenseType']
        
        lines = code.split('\n')
        filtered_lines = []
        removed_count = 0
        
        for line in lines:
            line_stripped = line.strip()
            should_remove = False
            
            # Пропускаем пустые строки и комментарии
            if not line_stripped or line_stripped.startswith('#'):
                # Проверяем, не является ли комментарий частью строки импорта
                if 'from' in line_stripped and 'models' in line_stripped and 'import' in line_stripped:
                    # Это может быть комментарий после импорта, проверяем основную часть
                    comment_part = line_stripped.split('#')[0].strip()
                    if any(f'import {model}' in comment_part for model in model_names):
                        # Проверяем, что это не разрешенный импорт
                        if 'django.db.models' not in comment_part and 'django.utils' not in comment_part:
                            should_remove = True
                else:
                    # Обычный комментарий или пустая строка - оставляем
                    filtered_lines.append(line)
                    continue
            
            # Проверяем различные варианты импорта моделей
            if 'from' in line_stripped and 'models' in line_stripped and 'import' in line_stripped:
                # Проверяем, что это не разрешенный импорт (django.db.models, django.utils)
                if 'django.db.models' not in line_stripped and 'django.utils' not in line_stripped:
                    # Проверяем, импортируется ли какая-либо из моделей
                    for model_name in model_names:
                        # Проверяем точное совпадение или в списке импортов
                        if (f'import {model_name}' in line_stripped or 
                            f'import {model_name},' in line_stripped or
                            f', {model_name}' in line_stripped or
                            f',{model_name}' in line_stripped):
                            should_remove = True
                            removed_count += 1
                            logger.info(f"Удален импорт модели: {line_stripped[:100]}")
                            break
            
            if not should_remove:
                filtered_lines.append(line)
        
        if removed_count > 0:
            logger.warning(f"Удалено {removed_count} строк(и) импорта моделей из кода")
        
        return '\n'.join(filtered_lines)
    
    def _convert_to_string(self, value: Any) -> str:
        """
        Преобразует значение в строку, обрабатывая специальные типы (date, datetime).
        
        Args:
            value: Значение для преобразования
            
        Returns:
            Строковое представление значения
        """
        from datetime import date, datetime
        
        if isinstance(value, (date, datetime)):
            if isinstance(value, datetime):
                return value.isoformat()
            else:
                return value.isoformat()
        elif value is None:
            return ''
        else:
            return str(value)
    
    def format_data_as_table(self, data: Any) -> Dict[str, Any]:
        """
        Форматирование данных для отображения в виде таблицы
        
        Args:
            data: Данные для форматирования (список словарей, список списков и т.д.)
            
        Returns:
            Словарь с форматированными данными:
            {
                'headers': List[str],  # Заголовки столбцов
                'rows': List[List[Any]],  # Строки данных
                'type': str  # Тип данных
            }
        """
        if data is None:
            return {
                'headers': [],
                'rows': [],
                'type': 'empty'
            }
        
        # Если это список словарей
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
            headers = list(data[0].keys())
            rows = [[self._convert_to_string(row.get(header, '')) for header in headers] for row in data]
            return {
                'headers': headers,
                'rows': rows,
                'type': 'dict_list'
            }
        
        # Если это список списков (первый элемент - заголовки)
        if isinstance(data, list) and len(data) > 0:
            if isinstance(data[0], list):
                if len(data) > 1:
                    headers = [self._convert_to_string(item) for item in data[0]]
                    rows = [[self._convert_to_string(item) for item in row] for row in data[1:]]
                    return {
                        'headers': headers,
                        'rows': rows,
                        'type': 'list_list'
                    }
                else:
                    # Только одна строка - это заголовки
                    return {
                        'headers': [self._convert_to_string(item) for item in data[0]],
                        'rows': [],
                        'type': 'list_list'
                    }
            else:
                # Простой список - делаем одну колонку
                return {
                    'headers': ['Значение'],
                    'rows': [[self._convert_to_string(item)] for item in data],
                    'type': 'simple_list'
                }
        
        # Если это словарь
        if isinstance(data, dict):
            # Если словарь содержит 'headers' и 'rows'
            if 'headers' in data and 'rows' in data:
                # Преобразуем строки в rows, если они еще не преобразованы
                rows = data.get('rows', [])
                if rows and isinstance(rows[0], list):
                    rows = [[self._convert_to_string(item) for item in row] for row in rows]
                return {
                    'headers': data.get('headers', []),
                    'rows': rows,
                    'type': 'structured'
                }
            else:
                # Обычный словарь - делаем две колонки (ключ, значение)
                rows = [[self._convert_to_string(k), self._convert_to_string(v)] for k, v in data.items()]
                return {
                    'headers': ['Ключ', 'Значение'],
                    'rows': rows,
                    'type': 'dict'
                }
        
        # Если это строка или число - просто возвращаем как есть
        return {
            'headers': ['Результат'],
            'rows': [[self._convert_to_string(data)]],
            'type': 'simple'
        }

