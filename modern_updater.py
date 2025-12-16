#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Современная система обновлений в стиле RU-MINETOOLS
"""

import sys
import json
import shutil
import zipfile
import tempfile
import subprocess
import os
from pathlib import Path
from urllib.request import urlopen, urlretrieve
from urllib.error import URLError, HTTPError
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *

# Импортируем систему локализации
try:
    from localization import get_text
    LOCALIZATION_AVAILABLE = True
except ImportError:
    LOCALIZATION_AVAILABLE = False
    def get_text(key, **kwargs):
        return key


def get_resource_path(filename):
    """Получает правильный путь к ресурсу для скомпилированной и обычной версии"""
    if getattr(sys, 'frozen', False):
        # Скомпилированная версия (PyInstaller)
        base_path = Path(sys._MEIPASS)
    else:
        # Обычная версия
        base_path = Path(__file__).parent
    
    resource_path = base_path / filename
    if resource_path.exists():
        return resource_path
    
    # Если не найден, попробуем в папке assets (для FINAL_RELEASE)
    assets_path = base_path / "assets" / filename
    if assets_path.exists():
        return assets_path
    
    # Если все еще не найден, возвращаем оригинальный путь
    return base_path / filename

# Конфигурация обновлений
try:
    from update_config import (
        GITHUB_REPO, GITHUB_API_URL, CURRENT_VERSION, 
        UPDATE_CHECK_INTERVAL, UPDATE_SETTINGS
    )
except ImportError:
    GITHUB_REPO = "your-username/l4d2-addon-manager"
    GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    CURRENT_VERSION = "1.0.0"
    UPDATE_CHECK_INTERVAL = 24 * 60 * 60 * 1000
    UPDATE_SETTINGS = {"auto_check": True, "silent_check": True}







class StandardUpdateChecker(QObject):
    """Чекер обновлений в стиле CustomInfoDialog"""
    
    update_available = pyqtSignal(dict)
    no_updates = pyqtSignal()
    check_error = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_widget = parent
    
    def check_for_updates(self, silent=False):
        """Проверяет обновления"""
        try:
            response = urlopen(GITHUB_API_URL, timeout=10)
            data = json.loads(response.read().decode('utf-8'))
            
            latest_version = data.get('tag_name', '').replace('v', '')
            
            if self.is_newer_version(latest_version, CURRENT_VERSION):
                self.update_available.emit(data)
            else:
                self.no_updates.emit()
                if not silent:
                    self.show_no_updates_message()
        
        except Exception as e:
            error_msg = get_text("update_check_error", error=str(e))
            self.check_error.emit(error_msg)
            if not silent:
                self.show_error_message()
    
    def is_newer_version(self, latest, current):
        """Сравнивает версии"""
        try:
            latest_parts = [int(x) for x in latest.split('.')]
            current_parts = [int(x) for x in current.split('.')]
            
            max_len = max(len(latest_parts), len(current_parts))
            latest_parts.extend([0] * (max_len - len(latest_parts)))
            current_parts.extend([0] * (max_len - len(current_parts)))
            
            return latest_parts > current_parts
        except:
            return False
    
    def show_no_updates_message(self):
        """Показывает сообщение об отсутствии обновлений через стандартный диалог"""
        msg = QMessageBox(self.parent_widget)
        msg.setWindowTitle(get_text("update_no_updates_title"))
        msg.setText(get_text("update_no_updates_message", version=CURRENT_VERSION))
        msg.setIcon(QMessageBox.Icon.Information)
        msg.exec()
    
    def show_error_message(self):
        """Показывает сообщение об ошибке через стандартный диалог"""
        msg = QMessageBox(self.parent_widget)
        msg.setWindowTitle(get_text("update_check_error_title"))
        msg.setText(get_text("update_check_error_message"))
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.exec()

def show_update_available_dialog(parent, version_info):
    """Показывает диалог о доступном обновлении через стандартный диалог"""
    # Убираем циклический импорт - используем стандартный QMessageBox
    
    new_version = version_info.get('tag_name', 'Unknown')
    
    msg = QMessageBox(parent)
    msg.setWindowTitle("Доступно обновление")
    msg.setText(f"Доступна новая версия: {new_version}")
    msg.setInformativeText("Хотите скачать и установить обновление?")
    msg.setIcon(QMessageBox.Icon.Information)
    msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    msg.setDefaultButton(QMessageBox.StandardButton.Yes)
    
    result = msg.exec()
    return result == QMessageBox.StandardButton.Yes



def start_update_process(parent, version_info):
    """Запускает автоматическое обновление"""
    
    # Получаем ссылку на скачивание (ищем EXE файл)
    download_url = None
    for asset in version_info.get('assets', []):
        if asset['name'].endswith('.exe') and 'L4D2_Addon_Manager' in asset['name']:
            download_url = asset['browser_download_url']
            break
    
    if not download_url:
        msg = QMessageBox(parent)
        msg.setWindowTitle("Ошибка обновления")
        msg.setText("Не найден файл для скачивания")
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.exec()
        return
    
    # Создаем простой диалог прогресса
    progress_dialog = QProgressDialog("Скачивание обновления...", "Отмена", 0, 100, parent)
    progress_dialog.setWindowTitle("Обновление")
    progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
    progress_dialog.show()
    
    try:
        # Создаем временную папку
        import tempfile
        temp_dir = Path(tempfile.mkdtemp())
        new_version = version_info.get('tag_name', '').replace('v', '')
        temp_file = temp_dir / f"L4D2_Addon_Manager_v{new_version}.exe"
        
        # Скачиваем файл
        progress_dialog.setLabelText("Скачивание обновления...")
        progress_dialog.setValue(10)
        QApplication.processEvents()
        
        from urllib.request import urlretrieve
        def progress_hook(block_num, block_size, total_size):
            if progress_dialog.wasCanceled():
                return
            if total_size > 0:
                downloaded = block_num * block_size
                progress = 10 + int((downloaded / total_size) * 80)
                progress_dialog.setValue(min(progress, 90))
                QApplication.processEvents()
        
        urlretrieve(download_url, temp_file, progress_hook)
        
        if progress_dialog.wasCanceled():
            shutil.rmtree(temp_dir, ignore_errors=True)
            return
        
        progress_dialog.setValue(95)
        progress_dialog.setLabelText("Подготовка к установке...")
        QApplication.processEvents()
        
        # Создаем скрипт обновления
        update_script = temp_dir / "update.bat"
        current_exe = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve()
        
        script_content = f'''@echo off
echo Ожидание завершения программы...
timeout /t 2 /nobreak >nul
echo Обновление программы...
copy /Y "{temp_file}" "{current_exe}"
if errorlevel 1 (
    echo Ошибка обновления!
    pause
    exit /b 1
)
echo Запуск обновленной программы...
start "" "{current_exe}"
echo Очистка временных файлов...
rmdir /s /q "{temp_dir}"
exit
'''
        
        update_script.write_text(script_content, encoding='cp1251')
        
        progress_dialog.setValue(100)
        progress_dialog.close()
        
        # Показываем финальное сообщение
        msg = QMessageBox(parent)
        msg.setWindowTitle("Обновление готово")
        msg.setText("Обновление скачано и готово к установке.")
        msg.setInformativeText("Программа будет закрыта и обновлена автоматически.")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        msg.setDefaultButton(QMessageBox.StandardButton.Ok)
        
        if msg.exec() == QMessageBox.StandardButton.Ok:
            # Запускаем скрипт обновления и закрываем программу
            import subprocess
            subprocess.Popen([str(update_script)], shell=True)
            QApplication.quit()
        else:
            # Пользователь отменил - удаляем временные файлы
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    except Exception as e:
        progress_dialog.close()
        msg = QMessageBox(parent)
        msg.setWindowTitle("Ошибка обновления")
        msg.setText(f"Произошла ошибка при обновлении:\n\n{str(e)}")
        msg.setInformativeText("Попробуйте скачать обновление вручную с GitHub.")
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.exec()


