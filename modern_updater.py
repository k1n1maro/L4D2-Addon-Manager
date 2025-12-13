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


class ModernUpdateWorker(QThread):
    """Современный worker для обновлений"""
    
    progress_updated = pyqtSignal(int, str)
    download_completed = pyqtSignal(str)
    install_completed = pyqtSignal()
    error_occurred = pyqtSignal(str)
    
    def __init__(self, download_url, version):
        super().__init__()
        self.download_url = download_url
        self.version = version
        self.is_cancelled = False
        self.current_phase = "download"  # download, install
    
    def cancel(self):
        self.is_cancelled = True
    
    def run(self):
        try:
            # Фаза скачивания
            self.current_phase = "download"
            self.progress_updated.emit(5, "🔄 Подготовка к скачиванию...")
            
            temp_dir = Path(tempfile.mkdtemp())
            filename = f"update_v{self.version}.zip"
            temp_file = temp_dir / filename
            
            self.progress_updated.emit(10, "📥 Скачивание обновления...")
            
            def progress_hook(block_num, block_size, total_size):
                if self.is_cancelled:
                    return
                downloaded = block_num * block_size
                if total_size > 0:
                    progress = 10 + int((downloaded / total_size) * 40)
                    mb_downloaded = downloaded / (1024 * 1024)
                    mb_total = total_size / (1024 * 1024)
                    self.progress_updated.emit(
                        progress, 
                        f"📥 Скачано: {mb_downloaded:.1f} MB из {mb_total:.1f} MB"
                    )
            
            urlretrieve(self.download_url, temp_file, progress_hook)
            
            if self.is_cancelled:
                shutil.rmtree(temp_dir, ignore_errors=True)
                return
            
            self.progress_updated.emit(50, "✅ Скачивание завершено")
            self.download_completed.emit(str(temp_file))
            
            # Фаза установки
            self.current_phase = "install"
            self.install_update(temp_file)
            
        except Exception as e:
            self.error_occurred.emit(f"Ошибка обновления: {e}")
    
    def install_update(self, update_file):
        """Устанавливает обновление"""
        try:
            self.progress_updated.emit(55, "🔧 Подготовка к установке...")
            
            app_dir = Path(__file__).parent
            backup_dir = app_dir.parent / f"{app_dir.name}_backup"
            
            # Создаем резервную копию
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            
            self.progress_updated.emit(60, "💾 Создание резервной копии...")
            shutil.copytree(app_dir, backup_dir)
            
            self.progress_updated.emit(70, "📦 Извлечение обновления...")
            
            # Извлекаем во временную папку
            temp_extract_dir = app_dir.parent / "temp_update"
            if temp_extract_dir.exists():
                shutil.rmtree(temp_extract_dir)
            
            with zipfile.ZipFile(update_file, 'r') as zip_ref:
                zip_ref.extractall(temp_extract_dir)
            
            self.progress_updated.emit(80, "🔄 Установка файлов...")
            
            # Находим папку с обновлением
            update_source = None
            for item in temp_extract_dir.iterdir():
                if item.is_dir() and (item / "l4d2_pyqt_main.py").exists():
                    update_source = item
                    break
            
            if not update_source:
                update_source = temp_extract_dir
            
            # Сохраняем конфигурацию
            config_backup = None
            config_file = app_dir / ".l4d2_mod_manager_config.json"
            if config_file.exists():
                config_backup = config_file.read_text(encoding='utf-8')
            
            # Удаляем старые файлы (кроме конфига)
            for item in app_dir.iterdir():
                if item.name != ".l4d2_mod_manager_config.json":
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)
            
            self.progress_updated.emit(90, "📁 Копирование новых файлов...")
            
            # Копируем новые файлы
            for item in update_source.iterdir():
                dest = app_dir / item.name
                if item.is_file():
                    shutil.copy2(item, dest)
                elif item.is_dir():
                    shutil.copytree(item, dest)
            
            # Восстанавливаем конфигурацию
            if config_backup:
                config_file.write_text(config_backup, encoding='utf-8')
            
            self.progress_updated.emit(95, "🧹 Очистка...")
            
            # Удаляем временные файлы
            shutil.rmtree(temp_extract_dir, ignore_errors=True)
            shutil.rmtree(backup_dir, ignore_errors=True)
            Path(update_file).unlink(missing_ok=True)
            
            self.progress_updated.emit(100, "🎉 Обновление установлено!")
            self.install_completed.emit()
            
        except Exception as e:
            self.error_occurred.emit(f"Ошибка установки: {e}")


class CustomProgressDialog(QDialog):
    """Диалог прогресса в стиле CustomInfoDialog"""
    
    def __init__(self, parent, title, message):
        super().__init__(parent)
        self.parent_widget = parent
        
        # Настройка окна
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        
        # Применяем блюр к родительскому окну
        self.blur_effect = QGraphicsBlurEffect()
        self.blur_effect.setBlurRadius(15)
        self.parent_widget.setGraphicsEffect(self.blur_effect)
        
        self.setup_ui(title, message)
        
        # Анимация появления
        self.setWindowOpacity(0)
        self.opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_anim.setDuration(300)
        self.opacity_anim.setStartValue(0)
        self.opacity_anim.setEndValue(1)
        self.opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    
    def setup_ui(self, title, message):
        """Создает интерфейс в стиле CustomInfoDialog"""
        self.setFixedSize(700, 520)
        
        # Основной layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(20)
        container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Иконка обновления (в стиле CustomInfoDialog)
        icon_label = QLabel()
        icon_path = get_resource_path("upd.png")  # Используем иконку обновления
        if icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                # Стандартный размер 120x120
                scaled_pixmap = pixmap.scaled(120, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                
                # Перекрашиваем в синий цвет (#3498db)
                colored_pixmap = QPixmap(scaled_pixmap.size())
                colored_pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(colored_pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                painter.drawPixmap(0, 0, scaled_pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(colored_pixmap.rect(), QColor(52, 152, 219))  # #3498db
                painter.end()
                
                icon_label.setPixmap(colored_pixmap)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(icon_label)
        
        # Заголовок (в стиле CustomInfoDialog)
        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 20px; font-weight: 600; color: white;")
        container_layout.addWidget(title_label)
        
        # Сообщение (в стиле CustomInfoDialog)
        self.message_label = QLabel(message)
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setWordWrap(True)
        self.message_label.setMaximumWidth(600)
        self.message_label.setStyleSheet("font-size: 13px; color: white; line-height: 1.5;")
        self.message_label.setTextFormat(Qt.TextFormat.RichText)
        container_layout.addWidget(self.message_label, 0, Qt.AlignmentFlag.AlignCenter)
        
        # Прогресс бар (в стиле приложения)
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #3498db;
                border-radius: 8px;
                background: rgba(20, 20, 20, 0.8);
                text-align: center;
                color: white;
                font-weight: 600;
                font-size: 12px;
                min-height: 20px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3498db, stop:1 #2980b9);
                border-radius: 6px;
            }
        """)
        self.progress_bar.setVisible(False)
        container_layout.addWidget(self.progress_bar)
        
        # Статус текст
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("font-size: 12px; color: #bdc3c7;")
        self.status_label.setVisible(False)
        container_layout.addWidget(self.status_label)
        
        container_layout.addSpacing(10)
        
        # Кнопка отмены (в стиле CustomInfoDialog)
        from l4d2_pyqt_main import AnimatedActionButton
        self.cancel_btn = AnimatedActionButton("Отмена", "#3498db")
        self.cancel_btn.setFixedSize(140, 50)
        self.cancel_btn.clicked.connect(self.reject)
        container_layout.addWidget(self.cancel_btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        layout.addWidget(container)
    
    def show_progress(self):
        """Показывает прогресс бар"""
        self.progress_bar.setVisible(True)
        self.status_label.setVisible(True)
        self.cancel_btn.setText("Отмена")
    
    def update_progress(self, value, status_text=""):
        """Обновляет прогресс"""
        self.progress_bar.setValue(value)
        if status_text:
            self.status_label.setText(status_text)
    
    def hide_progress(self):
        """Скрывает прогресс бар"""
        self.progress_bar.setVisible(False)
        self.status_label.setVisible(False)
    
    def show_with_animation(self):
        """Показывает диалог с анимацией"""
        self.show()
        self.opacity_anim.start()
    
    def closeEvent(self, event):
        """Убираем блюр при закрытии"""
        if hasattr(self, 'blur_effect') and self.parent_widget:
            self.parent_widget.setGraphicsEffect(None)
        event.accept()


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
            error_msg = f"Ошибка проверки обновлений: {e}"
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
        """Показывает сообщение об отсутствии обновлений через CustomInfoDialog"""
        from l4d2_pyqt_main import CustomInfoDialog
        CustomInfoDialog.information(
            self.parent_widget,
            "Обновления",
            f'<div style="text-align: center; color: white;">'
            f'У вас установлена последняя версия программы.<br><br>'
            f'<b>Текущая версия:</b> {CURRENT_VERSION}<br><br>'
            f'Проверка обновлений выполнена успешно.'
            f'</div>',
            icon_type="success"
        )
    
    def show_error_message(self):
        """Показывает сообщение об ошибке через CustomInfoDialog"""
        from l4d2_pyqt_main import CustomInfoDialog
        CustomInfoDialog.information(
            self.parent_widget,
            "Ошибка проверки обновлений",
            '<div style="text-align: center; color: white;">'
            'Не удалось проверить наличие обновлений.<br><br>'
            '<b>Возможные причины:</b><br>'
            '• Отсутствует подключение к интернету<br>'
            '• Проблемы с доступом к GitHub<br>'
            '• Временные технические неполадки<br><br>'
            'Попробуйте повторить проверку позже.'
            '</div>',
            icon_type="error"
        )

def show_update_available_dialog(parent, version_info):
    """Показывает диалог о доступном обновлении через CustomInfoDialog"""
    from l4d2_pyqt_main import CustomInfoDialog
    
    # Формируем информацию о версии
    new_version = version_info.get('tag_name', 'Неизвестно')
    release_date = version_info.get('published_at', '')
    if release_date:
        from datetime import datetime
        try:
            date_obj = datetime.fromisoformat(release_date.replace('Z', '+00:00'))
            release_date = date_obj.strftime('%d.%m.%Y')
        except:
            release_date = ''
    
    # Описание изменений
    changes = version_info.get('body', '')
    if changes:
        # Ограничиваем длину описания
        if len(changes) > 300:
            changes = changes[:300] + '...'
        changes = changes.replace('\n', '<br>')
    else:
        changes = 'Информация об изменениях недоступна.'
    
    # Формируем сообщение
    message = f'''<div style="text-align: center; color: white;">
        <b>Доступна новая версия программы!</b><br><br>
        
        <b>Новая версия:</b> {new_version}<br>
        <b>Текущая версия:</b> {CURRENT_VERSION}<br>
        {f'<b>Дата выпуска:</b> {release_date}<br>' if release_date else ''}
        <br>
        
        <b>Что нового:</b><br>
        <div style="text-align: left; margin: 10px 0; padding: 10px; background: rgba(52, 152, 219, 0.1); border-radius: 8px;">
        {changes}
        </div>
        
        Хотите скачать и установить обновление?
    </div>'''
    
    # Создаем диалог с кнопками
    dialog = CustomUpdateConfirmDialog(parent, "Доступно обновление", message, version_info)
    return dialog.exec()


class CustomUpdateConfirmDialog(QDialog):
    """Диалог подтверждения обновления в стиле CustomInfoDialog"""
    
    def __init__(self, parent, title, message, version_info):
        super().__init__(parent)
        self.parent_widget = parent
        self.version_info = version_info
        self.result_value = False
        
        # Настройка окна
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        
        # Применяем блюр к родительскому окну
        self.blur_effect = QGraphicsBlurEffect()
        self.blur_effect.setBlurRadius(15)
        self.parent_widget.setGraphicsEffect(self.blur_effect)
        
        self.setup_ui(title, message)
        
        # Анимация появления
        self.setWindowOpacity(0)
        self.opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_anim.setDuration(300)
        self.opacity_anim.setStartValue(0)
        self.opacity_anim.setEndValue(1)
        self.opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        # Показываем с анимацией
        self.show()
        self.opacity_anim.start()
    
    def setup_ui(self, title, message):
        """Создает интерфейс в стиле CustomInfoDialog"""
        self.setFixedSize(700, 650)  # Больше высота для кнопок
        
        # Основной layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(20)
        container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Иконка обновления (в стиле CustomInfoDialog)
        icon_label = QLabel()
        icon_path = get_resource_path("upd.png")
        if icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                # Стандартный размер 120x120
                scaled_pixmap = pixmap.scaled(120, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                
                # Перекрашиваем в синий цвет (#3498db)
                colored_pixmap = QPixmap(scaled_pixmap.size())
                colored_pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(colored_pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                painter.drawPixmap(0, 0, scaled_pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(colored_pixmap.rect(), QColor(52, 152, 219))  # #3498db
                painter.end()
                
                icon_label.setPixmap(colored_pixmap)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(icon_label)
        
        # Заголовок (в стиле CustomInfoDialog)
        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 20px; font-weight: 600; color: white;")
        container_layout.addWidget(title_label)
        
        # Сообщение (в стиле CustomInfoDialog)
        message_label = QLabel(message)
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setWordWrap(True)
        message_label.setMaximumWidth(600)
        message_label.setStyleSheet("font-size: 13px; color: white; line-height: 1.5;")
        message_label.setTextFormat(Qt.TextFormat.RichText)
        container_layout.addWidget(message_label, 0, Qt.AlignmentFlag.AlignCenter)
        
        container_layout.addSpacing(10)
        
        # Кнопки (в стиле CustomInfoDialog)
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(20)
        buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        from l4d2_pyqt_main import AnimatedActionButton
        
        # Кнопка "Скачать и установить"
        self.update_btn = AnimatedActionButton("Скачать и установить", "#3498db")
        self.update_btn.setFixedSize(200, 50)
        self.update_btn.clicked.connect(self.accept_update)
        buttons_layout.addWidget(self.update_btn)
        
        # Кнопка "Позже"
        self.later_btn = AnimatedActionButton("Позже", "#7f8c8d")
        self.later_btn.setFixedSize(140, 50)
        self.later_btn.clicked.connect(self.reject_update)
        buttons_layout.addWidget(self.later_btn)
        
        container_layout.addLayout(buttons_layout)
        layout.addWidget(container)
    
    def accept_update(self):
        """Пользователь согласился на обновление"""
        self.result_value = True
        self.close()
    
    def reject_update(self):
        """Пользователь отказался от обновления"""
        self.result_value = False
        self.close()
    
    def exec(self):
        """Переопределяем exec для возврата результата"""
        super().exec()
        return self.result_value
    
    def closeEvent(self, event):
        """Убираем блюр при закрытии"""
        if hasattr(self, 'blur_effect') and self.parent_widget:
            self.parent_widget.setGraphicsEffect(None)
        event.accept()


def start_update_process(parent, version_info):
    """Запускает процесс обновления с CustomProgressDialog"""
    
    # Получаем ссылку на скачивание
    download_url = None
    for asset in version_info.get('assets', []):
        if asset['name'].endswith('.zip'):
            download_url = asset['browser_download_url']
            break
    
    if not download_url:
        from l4d2_pyqt_main import CustomInfoDialog
        CustomInfoDialog.information(
            parent,
            "Ошибка обновления",
            '<div style="text-align: center; color: white;">'
            'Не удалось найти файл обновления.<br><br>'
            'Попробуйте скачать обновление вручную с GitHub.'
            '</div>',
            icon_type="error"
        )
        return
    
    # Создаем диалог прогресса
    progress_dialog = CustomProgressDialog(
        parent,
        "Обновление программы",
        "Подготовка к загрузке обновления..."
    )
    
    # Создаем worker для загрузки
    worker = ModernUpdateWorker(download_url, version_info.get('tag_name', ''))
    
    # Подключаем сигналы
    worker.progress_updated.connect(lambda value, text: progress_dialog.update_progress(value, text))
    worker.download_completed.connect(lambda path: on_download_completed(progress_dialog, path))
    worker.install_completed.connect(lambda: on_install_completed(progress_dialog, parent))
    worker.error_occurred.connect(lambda error: on_update_error(progress_dialog, parent, error))
    
    # Подключаем отмену
    progress_dialog.rejected.connect(worker.cancel)
    
    # Показываем прогресс и запускаем загрузку
    progress_dialog.show_progress()
    progress_dialog.show_with_animation()
    worker.start()


def on_download_completed(progress_dialog, file_path):
    """Обработка завершения загрузки"""
    progress_dialog.update_progress(100, "Загрузка завершена. Начинается установка...")


def on_install_completed(progress_dialog, parent):
    """Обработка завершения установки"""
    progress_dialog.close()
    
    from l4d2_pyqt_main import CustomInfoDialog
    CustomInfoDialog.information(
        parent,
        "Обновление завершено",
        '<div style="text-align: center; color: white;">'
        'Обновление успешно установлено!<br><br>'
        'Для применения изменений необходимо перезапустить программу.<br><br>'
        '<b>Перезапустить сейчас?</b>'
        '</div>',
        icon_type="success"
    )


def on_update_error(progress_dialog, parent, error_message):
    """Обработка ошибки обновления"""
    progress_dialog.close()
    
    from l4d2_pyqt_main import CustomInfoDialog
    CustomInfoDialog.information(
        parent,
        "Ошибка обновления",
        f'<div style="text-align: center; color: white;">'
        f'Произошла ошибка при обновлении:<br><br>'
        f'<b>{error_message}</b><br><br>'
        f'Попробуйте повторить попытку позже или скачайте обновление вручную с GitHub.'
        f'</div>',
        icon_type="error"
    )