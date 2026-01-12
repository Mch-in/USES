"""
Утилита для управления процессом llama-server
Автоматический запуск и остановка llama-server
"""
import os
import subprocess
import psutil
import logging
import time
from pathlib import Path
from django.conf import settings

logger = logging.getLogger(__name__)


class LlamaServerManager:
    """Менеджер для управления процессом llama-server"""
    
    def __init__(self):
        self.llama_server_path = getattr(settings, 'LLAMA_SERVER_PATH', '')
        self.model_path = getattr(settings, 'GPT_MODEL_PATH', '')
        self.api_base = getattr(settings, 'LLAMA_SERVER_API_BASE', 'http://localhost:8080')
        self.process = None
        self.pid_file = None
        
        # Параметры запуска из настроек или значения по умолчанию
        self.flash_attention = getattr(settings, 'LLAMA_FLASH_ATTENTION', '1')
        self.ncmoe = getattr(settings, 'LLAMA_NCMOE', '25')
        self.ngl = getattr(settings, 'LLAMA_NGL', '40')
        self.ub = getattr(settings, 'LLAMA_UB', '2048')
        self.batch = getattr(settings, 'LLAMA_BATCH', '2048')
        self.context = getattr(settings, 'LLAMA_CONTEXT', '32768')
        self.jinja = getattr(settings, 'LLAMA_JINJA', True)
        
        # Определяем PID файл
        if self.api_base:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(self.api_base)
                port = parsed.port or 8080
                from pathlib import Path as P
                self.pid_file = P(settings.BASE_DIR) / f'llama_server_{port}.pid'
            except:
                from pathlib import Path as P
                self.pid_file = P(settings.BASE_DIR) / 'llama_server.pid'
    
    def is_running(self):
        """Проверка, запущен ли llama-server"""
        # Проверяем PID файл
        if self.pid_file and self.pid_file.exists():
            try:
                with open(self.pid_file, 'r') as f:
                    pid = int(f.read().strip())
                
                # Проверяем, существует ли процесс
                if psutil.pid_exists(pid):
                    process = psutil.Process(pid)
                    # Проверяем, что это действительно llama-server
                    if 'llama' in process.name().lower() or 'llama' in ' '.join(process.cmdline()).lower():
                        return True
                else:
                    # PID файл есть, но процесс не существует - удаляем файл
                    self.pid_file.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"Ошибка при проверке PID файла: {e}")
        
        # Проверяем, есть ли процесс llama-server по имени/команде
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = ' '.join(proc.info['cmdline'] or [])
                    if 'llama-server' in cmdline.lower() or 'llama-server.exe' in cmdline.lower():
                        # Проверяем, что это наш процесс (содержит путь к модели)
                        if self.model_path and self.model_path.lower() in cmdline.lower():
                            return True
                        # Или если это единственный llama-server процесс
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            logger.warning(f"Ошибка при поиске процесса llama-server: {e}")
        
        return False
    
    def start(self):
        """Запуск llama-server"""
        if self.is_running():
            logger.info("llama-server уже запущен")
            return True
        
        if not self.llama_server_path or not os.path.exists(self.llama_server_path):
            logger.error(f"Путь к llama-server не указан или не существует: {self.llama_server_path}")
            return False
        
        if not self.model_path or not os.path.exists(self.model_path):
            logger.error(f"Путь к модели не указан или не существует: {self.model_path}")
            return False
        
        try:
            # Формируем команду запуска
            cmd = [
                self.llama_server_path,
                '-m', self.model_path,
                '-fa', str(self.flash_attention),
                '-ncmoe', str(self.ncmoe),
                '-ngl', str(self.ngl),
                '-ub', str(self.ub),
                '-b', str(self.batch),
                '-c', str(self.context),
            ]
            
            if self.jinja:
                cmd.append('--jinja')
            
            logger.info(f"Запуск llama-server: {' '.join(cmd)}")
            
            # Запускаем процесс в фоне
            if os.name == 'nt':  # Windows
                # На Windows используем CREATE_NO_WINDOW для скрытия консоли
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    startupinfo=startupinfo,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:  # Linux/Mac
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True
                )
            
            # Сохраняем PID
            if self.pid_file:
                with open(self.pid_file, 'w') as f:
                    f.write(str(process.pid))
            
            self.process = process
            
            # Ждем немного, чтобы процесс запустился
            time.sleep(2)
            
            # Проверяем, что процесс еще работает
            if process.poll() is not None:
                # Процесс завершился сразу - ошибка
                stdout, stderr = process.communicate()
                logger.error(f"llama-server завершился с ошибкой. Стандартный вывод: {stdout.decode()}, Ошибки: {stderr.decode()}")
                return False
            
            logger.info(f"llama-server запущен успешно (PID: {process.pid})")
            return True
            
        except Exception as e:
            logger.exception(f"Ошибка при запуске llama-server: {e}")
            return False
    
    def stop(self):
        """Остановка llama-server"""
        if self.pid_file and self.pid_file.exists():
            try:
                with open(self.pid_file, 'r') as f:
                    pid = int(f.read().strip())
                
                if psutil.pid_exists(pid):
                    process = psutil.Process(pid)
                    process.terminate()
                    # Ждем завершения процесса
                    try:
                        process.wait(timeout=5)
                    except psutil.TimeoutExpired:
                        # Если процесс не завершился, принудительно убиваем
                        process.kill()
                    
                    logger.info(f"llama-server остановлен (PID: {pid})")
                else:
                    logger.warning(f"Процесс с PID {pid} не найден")
                
                # Удаляем PID файл
                self.pid_file.unlink(missing_ok=True)
                return True
            except Exception as e:
                logger.exception(f"Ошибка при остановке llama-server: {e}")
                return False
        
        return False
    
    def ensure_running(self):
        """Убедиться, что llama-server запущен"""
        if not self.is_running():
            logger.info("llama-server не запущен, запускаю...")
            if self.start():
                # Ждем, пока сервер полностью запустится
                time.sleep(3)
                return True
            return False
        return True


# Глобальный экземпляр менеджера
_manager = None

def get_manager():
    """Получение глобального экземпляра менеджера"""
    global _manager
    if _manager is None:
        _manager = LlamaServerManager()
    return _manager
