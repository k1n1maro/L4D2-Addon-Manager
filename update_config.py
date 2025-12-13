#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Конфигурация системы обновлений
"""

# Настройки GitHub репозитория
GITHUB_USERNAME = "k1n1maro"  # Ваш GitHub username
GITHUB_REPO_NAME = "L4D2-Addon-Manager"  # Название репозитория
GITHUB_REPO = f"{GITHUB_USERNAME}/{GITHUB_REPO_NAME}"

# URL для API GitHub
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# Текущая версия приложения (обновляйте при каждом релизе)
CURRENT_VERSION = "1.1.0"

# Интервал автоматической проверки обновлений (в миллисекундах)
UPDATE_CHECK_INTERVAL = 24 * 60 * 60 * 1000  # 24 часа

# Настройки обновлений
UPDATE_SETTINGS = {
    "auto_check": True,  # Автоматическая проверка при запуске
    "check_interval": UPDATE_CHECK_INTERVAL,
    "silent_check": True,  # Тихая проверка (без уведомлений если обновлений нет)
    "backup_enabled": True,  # Создавать резервную копию перед обновлением
    "restart_after_update": True,  # Перезапускать приложение после обновления
}

# Файлы, которые нужно исключить из обновления (сохранить пользовательские данные)
EXCLUDE_FROM_UPDATE = [
    ".l4d2_mod_manager_config.json",  # Конфигурация пользователя
    "user_data.json",  # Пользовательские данные
    "logs/",  # Папка с логами
    "temp/",  # Временные файлы
]

# Обязательные файлы в релизе
REQUIRED_FILES = [
    "l4d2_pyqt_main.py",  # Основной файл приложения
    "updater.py",  # Система обновлений
]

def get_version_info():
    """Возвращает информацию о текущей версии"""
    return {
        "version": CURRENT_VERSION,
        "repo": GITHUB_REPO,
        "api_url": GITHUB_API_URL,
    }

def validate_config():
    """Проверяет корректность конфигурации"""
    errors = []
    
    if GITHUB_USERNAME == "your-github-username":
        errors.append("Не указан GitHub username в GITHUB_USERNAME")
    
    if not GITHUB_REPO_NAME or GITHUB_REPO_NAME == "":
        errors.append("Не указано название репозитория в GITHUB_REPO_NAME")
    
    if not CURRENT_VERSION or CURRENT_VERSION == "":
        errors.append("Не указана текущая версия в CURRENT_VERSION")
    
    return errors

if __name__ == "__main__":
    # Проверка конфигурации
    errors = validate_config()
    if errors:
        print("❌ Ошибки конфигурации:")
        for error in errors:
            print(f"  • {error}")
        print("\n📝 Отредактируйте файл update_config.py")
    else:
        print("✅ Конфигурация корректна")
        print(f"📦 Репозиторий: {GITHUB_REPO}")
        print(f"🏷️ Текущая версия: {CURRENT_VERSION}")
        print(f"🔄 Интервал проверки: {UPDATE_CHECK_INTERVAL // (60 * 60 * 1000)} часов")