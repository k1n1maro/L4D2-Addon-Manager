#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Система локализации для L4D2 Addon Manager
"""

import json
from pathlib import Path

class Localization:
    def __init__(self):
        self.current_language = "ru"  # По умолчанию русский
        self.translations = {
            "ru": {
                # Основные элементы интерфейса
                "app_title": "L4D2 Addon Manager",
                "loading_addons": "Загрузка аддонов",
                "initializing": "Инициализация...",
                "scanning_folder": "Сканирование папки...",
                "loading_steam_info": "Загрузка информации из Steam...",
                "ready": "Готово!",
                
                # Вкладки
                "tab_addons": "Аддоны",
                "tab_pirate_addons": "Аддоны Пиратка",
                "tab_settings": "Настройки",
                "tab_help": "Справка",
                "tab_contacts": "Контакты",
                
                # Кнопки
                "btn_support_project": "Поддержать проект",
                "btn_updates": "Обновления",
                "btn_github": "GitHub",
                "btn_enable_all": "Включить все",
                "btn_disable_all": "Выключить все",
                "btn_refresh": "Обновить",
                "btn_settings": "Настройки",
                "btn_ok": "ОК",
                "btn_cancel": "Отмена",
                "btn_yes": "Да",
                "btn_no": "Нет",
                "btn_delete": "Удалить",
                "btn_reinstall": "Переустановить",
                "btn_browse": "Обзор",
                "btn_save": "Сохранить",
                "btn_reset": "Сброс",
                
                # Описания
                "addons_description": "Управление аддонами из Steam Workshop. Включайте/выключайте моды одним кликом.",
                "pirate_addons_description": "Добавляйте моды в gameinfo.txt для принудительной загрузки на серверах.",
                "search_placeholder": "Поиск...",
                "addons_count": "Аддонов: {total} ({enabled} вкл)",
                
                # Настройки
                "settings_game_path": "Путь к игре",
                "settings_language": "Язык интерфейса",
                "settings_animations": "Анимации",
                "settings_auto_updates": "Автообновления",
                "settings_steam_integration": "Интеграция со Steam",
                "settings_backup": "Резервные копии",
                
                # Сообщения
                "msg_select_game_folder": "Выберите папку с игрой Left 4 Dead 2",
                "msg_invalid_game_folder": "Выбранная папка не содержит Left 4 Dead 2",
                "msg_addon_enabled": "Аддон включен",
                "msg_addon_disabled": "Аддон выключен",
                "msg_all_addons_enabled": "Все аддоны включены",
                "msg_all_addons_disabled": "Все аддоны выключены",
                "msg_addon_deleted": "Аддон удален",
                "msg_settings_saved": "Настройки сохранены",
                
                # Диалоги
                "dialog_delete_addon": "Удалить аддон",
                "dialog_delete_addon_text": "Вы уверены, что хотите удалить этот аддон?<br><br><b>{name}</b><br><br>Это действие нельзя отменить.",
                "dialog_first_launch": "Добро пожаловать!",
                "dialog_first_launch_text": "Добро пожаловать в L4D2 Addon Manager!<br><br>Для начала работы укажите папку с игрой Left 4 Dead 2.",
                "dialog_language_selection": "Выбор языка",
                "dialog_language_selection_text": "Выберите предпочитаемый язык интерфейса:",
                
                # Статусы
                "status_gameinfo_found": "✓ gameinfo.txt найден",
                "status_gameinfo_not_found": "✗ gameinfo.txt не найден",
                "status_workshop_found": "✓ workshop найден",
                "status_workshop_not_found": "✗ workshop не найден",
                
                # Ошибки
                "error_loading_addons": "Ошибка загрузки аддонов",
                "error_steam_api": "Ошибка Steam API",
                "error_file_operation": "Ошибка файловой операции",
                "error_network": "Ошибка сети",
                
                # Обновления
                "update_available": "Доступно обновление",
                "update_downloading": "Загрузка обновления...",
                "update_installing": "Установка обновления...",
                "update_completed": "Обновление завершено",
                "update_error": "Ошибка обновления",
                
                # Справка
                "help_title": "Справка по использованию",
                "help_addons": "Как управлять аддонами",
                "help_installation": "Установка и настройка",
                "help_troubleshooting": "Решение проблем",
            },
            
            "en": {
                # Main interface elements
                "app_title": "L4D2 Addon Manager",
                "loading_addons": "Loading addons",
                "initializing": "Initializing...",
                "scanning_folder": "Scanning folder...",
                "loading_steam_info": "Loading Steam information...",
                "ready": "Ready!",
                
                # Tabs
                "tab_addons": "Addons",
                "tab_pirate_addons": "Pirate Addons",
                "tab_settings": "Settings",
                "tab_help": "Help",
                "tab_contacts": "Contacts",
                
                # Buttons
                "btn_support_project": "Support Project",
                "btn_updates": "Updates",
                "btn_github": "GitHub",
                "btn_enable_all": "Enable All",
                "btn_disable_all": "Disable All",
                "btn_refresh": "Refresh",
                "btn_settings": "Settings",
                "btn_ok": "OK",
                "btn_cancel": "Cancel",
                "btn_yes": "Yes",
                "btn_no": "No",
                "btn_delete": "Delete",
                "btn_reinstall": "Reinstall",
                "btn_browse": "Browse",
                "btn_save": "Save",
                "btn_reset": "Reset",
                
                # Descriptions
                "addons_description": "Manage addons from Steam Workshop. Enable/disable mods with one click.",
                "pirate_addons_description": "Add mods to gameinfo.txt for forced loading on servers.",
                "search_placeholder": "Search...",
                "addons_count": "Addons: {total} ({enabled} enabled)",
                
                # Settings
                "settings_game_path": "Game Path",
                "settings_language": "Interface Language",
                "settings_animations": "Animations",
                "settings_auto_updates": "Auto Updates",
                "settings_steam_integration": "Steam Integration",
                "settings_backup": "Backups",
                
                # Messages
                "msg_select_game_folder": "Select Left 4 Dead 2 game folder",
                "msg_invalid_game_folder": "Selected folder does not contain Left 4 Dead 2",
                "msg_addon_enabled": "Addon enabled",
                "msg_addon_disabled": "Addon disabled",
                "msg_all_addons_enabled": "All addons enabled",
                "msg_all_addons_disabled": "All addons disabled",
                "msg_addon_deleted": "Addon deleted",
                "msg_settings_saved": "Settings saved",
                
                # Dialogs
                "dialog_delete_addon": "Delete Addon",
                "dialog_delete_addon_text": "Are you sure you want to delete this addon?<br><br><b>{name}</b><br><br>This action cannot be undone.",
                "dialog_first_launch": "Welcome!",
                "dialog_first_launch_text": "Welcome to L4D2 Addon Manager!<br><br>To get started, please specify the Left 4 Dead 2 game folder.",
                "dialog_language_selection": "Language Selection",
                "dialog_language_selection_text": "Please select your preferred interface language:",
                
                # Status
                "status_gameinfo_found": "✓ gameinfo.txt found",
                "status_gameinfo_not_found": "✗ gameinfo.txt not found",
                "status_workshop_found": "✓ workshop found",
                "status_workshop_not_found": "✗ workshop not found",
                
                # Errors
                "error_loading_addons": "Error loading addons",
                "error_steam_api": "Steam API error",
                "error_file_operation": "File operation error",
                "error_network": "Network error",
                
                # Updates
                "update_available": "Update Available",
                "update_downloading": "Downloading update...",
                "update_installing": "Installing update...",
                "update_completed": "Update completed",
                "update_error": "Update error",
                
                # Help
                "help_title": "Usage Guide",
                "help_addons": "How to manage addons",
                "help_installation": "Installation and setup",
                "help_troubleshooting": "Troubleshooting",
            }
        }
    
    def set_language(self, language_code):
        """Устанавливает язык интерфейса"""
        if language_code in self.translations:
            self.current_language = language_code
            return True
        return False
    
    def get_text(self, key, **kwargs):
        """Получает локализованный текст"""
        try:
            text = self.translations[self.current_language].get(key, key)
            if kwargs:
                return text.format(**kwargs)
            return text
        except:
            return key
    
    def get_available_languages(self):
        """Возвращает список доступных языков"""
        return {
            "ru": "Русский",
            "en": "English"
        }
    
    def save_language_preference(self, config_file):
        """Сохраняет выбранный язык в конфиг"""
        try:
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            else:
                config = {}
            
            config['language'] = self.current_language
            
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            print(f"Error saving language preference: {e}")
            return False
    
    def load_language_preference(self, config_file):
        """Загружает сохраненный язык из конфига"""
        try:
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    language = config.get('language', 'ru')
                    self.set_language(language)
                    return language
        except Exception as e:
            print(f"Error loading language preference: {e}")
        
        return 'ru'  # По умолчанию русский

# Глобальный экземпляр локализации
_localization = Localization()

def get_text(key, **kwargs):
    """Глобальная функция для получения локализованного текста"""
    return _localization.get_text(key, **kwargs)

def set_language(language_code):
    """Глобальная функция для установки языка"""
    return _localization.set_language(language_code)

def get_available_languages():
    """Глобальная функция для получения доступных языков"""
    return _localization.get_available_languages()

def save_language_preference(config_file):
    """Глобальная функция для сохранения языка"""
    return _localization.save_language_preference(config_file)

def load_language_preference(config_file):
    """Глобальная функция для загрузки языка"""
    return _localization.load_language_preference(config_file)