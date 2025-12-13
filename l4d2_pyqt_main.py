# -*- coding: utf-8 -*-
"""
L4D2 Mod Manager - PyQt6 Professional Edition
С анимациями, blur эффектами и современным дизайном
"""

import sys
import json
import shutil
import re
import os
import random
from pathlib import Path
from html import escape
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from urllib.request import urlopen
from urllib.error import URLError

# Импортируем современную систему обновлений
try:
    from modern_updater import StandardUpdateChecker, show_update_available_dialog, start_update_process
    UPDATER_AVAILABLE = True
except ImportError:
    UPDATER_AVAILABLE = False
    print("Система обновлений недоступна")

# Импортируем систему локализации
try:
    from localization import get_text, set_language, get_available_languages, save_language_preference, load_language_preference
    from language_dialog import show_language_selection_dialog
    LOCALIZATION_AVAILABLE = True
except ImportError:
    LOCALIZATION_AVAILABLE = False
    print("Система локализации недоступна")
    # Заглушки для локализации
    def get_text(key, **kwargs):
        return key
    def set_language(lang):
        return True
    def get_available_languages():
        return {"ru": "Русский"}
    def save_language_preference(config_file):
        return True
    def load_language_preference(config_file):
        return "ru"
    def show_language_selection_dialog(parent=None):
        return "ru"

CONFIG_FILE = Path.home() / ".l4d2_mod_manager_config.json"
STEAM_API_URL = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"


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


class AddonScanWorker(QThread):
    """Worker thread для сканирования аддонов в фоне"""
    progress_updated = pyqtSignal(int, str)  # progress, status
    scan_completed = pyqtSignal(list)  # список аддонов
    scan_error = pyqtSignal(str)  # сообщение об ошибке
    
    def __init__(self, workshop_path):
        super().__init__()
        self.workshop_path = workshop_path
        
    def run(self):
        """Выполняется в отдельном потоке"""
        try:
            self.progress_updated.emit(10, get_text("scanning_folder"))
            print(f"🔍 AddonScanWorker: Scanning {self.workshop_path}")
            print(f"🔍 Workshop path exists: {self.workshop_path.exists()}")
            
            if not self.workshop_path.exists():
                print(f"❌ Workshop path does not exist!")
                self.scan_error.emit(f"Folder does not exist: {self.workshop_path}")
                return
            
            # Собираем информацию об аддонах
            addons_dict = {}  # {ID: {'vpk': путь, 'folder': есть_папка}}
            
            # Ищем .vpk файлы напрямую в workshop
            vpk_files = list(self.workshop_path.glob("*.vpk"))
            print(f"🔍 Found VPK files: {len(vpk_files)}")
            for vpk_file in vpk_files:
                addon_id = vpk_file.stem
                print(f"   VPK: {vpk_file.name} -> ID: {addon_id}")
                if addon_id.isdigit():
                    addons_dict[addon_id] = {'vpk': vpk_file, 'folder': False}
            
            self.progress_updated.emit(20, get_text("found_vpk_files", count=len(addons_dict)))
            
            # Ищем папки с ID
            addon_folders = [f for f in self.workshop_path.iterdir() if f.is_dir() and f.name.isdigit()]
            print(f"🔍 Found addon folders: {len(addon_folders)}")
            for folder in addon_folders:
                addon_id = folder.name
                print(f"   Folder: {folder.name}")
                if addon_id in addons_dict:
                    # Есть и файл и папка - аддон включен!
                    addons_dict[addon_id]['folder'] = True
                else:
                    # Есть только папка без vpk файла - добавляем как выключенный
                    addons_dict[addon_id] = {'vpk': None, 'folder': True}
            
            self.progress_updated.emit(30, get_text("found_addons", count=len(addons_dict)))
            print(f"🔍 Total addons found: {len(addons_dict)}")
            
            # Создаем список аддонов
            addons = []
            for addon_id, data in addons_dict.items():
                # Аддон включен только если есть И vpk файл И папка
                is_enabled = data['vpk'] is not None and data['folder']
                
                addon_data = {
                    'id': addon_id,
                    'name': get_text("addon_default_name", id=addon_id),
                    'description': get_text("loading_addon"),
                    'enabled': is_enabled,
                    'path': data['vpk'] if data['vpk'] else self.workshop_path / addon_id
                }
                addons.append(addon_data)
            
            self.progress_updated.emit(40, get_text("scan_completed"))
            self.scan_completed.emit(addons)
            
        except Exception as e:
            self.scan_error.emit(str(e))


class SteamInfoWorker(QThread):
    """Worker thread для загрузки информации из Steam API в фоне"""
    progress_updated = pyqtSignal(int, str)  # progress, status
    info_loaded = pyqtSignal(list)  # обновленный список аддонов
    
    def __init__(self, addons):
        super().__init__()
        self.addons = addons
        
    def run(self):
        """Выполняется в отдельном потоке"""
        try:
            if not self.addons:
                self.info_loaded.emit(self.addons)
                return
            
            self.progress_updated.emit(50, get_text("loading_steam_info"))
            
            # Формируем запрос для всех аддонов
            addon_ids = [addon['id'] for addon in self.addons]
            total = len(addon_ids)
            
            # Ограничиваем количество аддонов в одном запросе (Steam API может не справиться с большими запросами)
            max_batch_size = 50
            if len(addon_ids) > max_batch_size:
                addon_ids = addon_ids[:max_batch_size]
                self.progress_updated.emit(55, get_text("processing_first_addons", count=max_batch_size))
            
            # Формируем POST данные
            post_data = {'itemcount': len(addon_ids)}
            for i, addon_id in enumerate(addon_ids):
                post_data[f'publishedfileids[{i}]'] = addon_id
            
            # Кодируем данные
            import urllib.parse
            data = urllib.parse.urlencode(post_data).encode('utf-8')
            
            self.progress_updated.emit(60, get_text("sending_steam_request"))
            
            # Делаем запрос с увеличенным таймаутом и обработкой ошибок
            try:
                response = urlopen(STEAM_API_URL, data=data, timeout=15)
                result = json.loads(response.read().decode('utf-8'))
                self.progress_updated.emit(70, get_text("processing_steam_response"))
            except Exception as api_error:
                print(f"Ошибка Steam API запроса: {api_error}")
                self.progress_updated.emit(90, get_text("steam_api_unavailable"))
                
                # Устанавливаем базовые названия для всех аддонов
                for addon in self.addons:
                    if not addon.get('name') or addon.get('name') == 'Loading...':
                        addon['name'] = f"Addon {addon['id']}"
                        addon['description'] = "Steam Workshop addon (details unavailable)"
                        addon['preview_url'] = ''
                
                # Возвращаем аддоны с базовыми названиями
                self.info_loaded.emit(self.addons)
                return
            
            if result.get('response', {}).get('publishedfiledetails'):
                details = result['response']['publishedfiledetails']
                
                for idx, detail in enumerate(details):
                    addon_id = detail.get('publishedfileid')
                    result_code = detail.get('result', 0)
                    
                    if result_code == 1:  # Success
                        title = detail.get('title', get_text("addon_default_name", id=addon_id))
                        description = detail.get('description', '')
                        preview_url = detail.get('preview_url', '')
                        
                        # Очищаем BBCode из описания
                        description = self.clean_bbcode(description)
                        
                        # Обновляем данные аддона
                        for addon in self.addons:
                            if addon['id'] == addon_id:
                                addon['name'] = title
                                addon['description'] = description[:150] + '...' if len(description) > 150 else description
                                addon['preview_url'] = preview_url
                                break
                    else:
                        # Аддон недоступен
                        for addon in self.addons:
                            if addon['id'] == addon_id:
                                addon['name'] = get_text("addon_unavailable", id=addon_id)
                                addon['description'] = get_text("addon_removed_description")
                                break
                    
                    # Обновляем прогресс
                    progress = 50 + int((idx + 1) / total * 40)
                    self.progress_updated.emit(progress, get_text("loaded_progress", current=idx + 1, total=total))
            
            self.progress_updated.emit(95, get_text("updating_interface"))
            self.info_loaded.emit(self.addons)
            
        except Exception as e:
            print(f"Ошибка загрузки из Steam API: {e}")
            
            # Устанавливаем базовые названия для всех аддонов
            for addon in self.addons:
                if not addon.get('name') or addon.get('name') == 'Loading...':
                    addon['name'] = f"Addon {addon['id']}"
                    addon['description'] = "Steam Workshop addon (details unavailable)"
                    addon['preview_url'] = ''
            
            # Возвращаем аддоны как есть, даже если произошла ошибка
            self.info_loaded.emit(self.addons)
    
    def clean_bbcode(self, text):
        """Удаляет BBCode теги из текста"""
        # Удаляем все BBCode теги
        text = re.sub(r'\[.*?\]', '', text)
        # Удаляем множественные пробелы и переносы строк
        text = re.sub(r'\s+', ' ', text)
        return text.strip()


class LoadingDialog(QDialog):
    """Диалог загрузки с прогресс-баром в стиле кастомных диалогов"""
    def __init__(self, parent=None, keep_blur_on_close=False):
        super().__init__(parent)
        self.parent_widget = parent
        self.keep_blur_on_close = keep_blur_on_close
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        
        # Проверяем, есть ли уже blur эффект на родительском окне
        self.existing_blur = False
        if parent:
            existing_effect = parent.graphicsEffect()
            if existing_effect and isinstance(existing_effect, QGraphicsBlurEffect):
                # Используем существующий blur
                self.existing_blur = True
                self.blur_effect = existing_effect
                self.blur_anim = None
            else:
                # Создаем новый blur с анимацией
                self.blur_effect = QGraphicsBlurEffect()
                self.blur_effect.setBlurRadius(0)
                parent.setGraphicsEffect(self.blur_effect)
                
                # Анимация блюра
                self.blur_anim = QPropertyAnimation(self.blur_effect, b"blurRadius")
                self.blur_anim.setDuration(300)
                self.blur_anim.setStartValue(0)
                self.blur_anim.setEndValue(15)
                self.blur_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        else:
            self.blur_anim = None
        
        self.setup_ui()
        
        # Анимация появления диалога
        self.setWindowOpacity(0)
        self.opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_anim.setDuration(300)
        self.opacity_anim.setStartValue(0)
        self.opacity_anim.setEndValue(1)
        self.opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    
    def setup_ui(self):
        # Увеличенный размер диалога чтобы текст помещался
        self.setFixedSize(700, 400)
        
        # Блокируем события мыши для родительского окна во время загрузки
        if self.parent_widget:
            self.parent_widget.setEnabled(False)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Контейнер без фона (прозрачный)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(40, 40, 40, 40)  # Добавляем отступы
        container_layout.setSpacing(25)  # Увеличиваем расстояние между элементами
        container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Заголовок - ЕДИНЫЙ СТАНДАРТ
        title = QLabel(get_text("loading_addons"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 20px; font-weight: 600; color: white;")
        container_layout.addWidget(title)
        
        # Прогресс бар
        self.progress = QProgressBar()
        self.progress.setFixedSize(600, 30)
        self.progress.setTextVisible(True)
        self.progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress.setStyleSheet("""
            QProgressBar {
                border: 2px solid #3498db;
                border-radius: 15px;
                background: rgba(30, 30, 30, 0.5);
                text-align: center;
                color: white;
                font-size: 12px;
            }
            QProgressBar::chunk {
                background: #3498db;
                border-radius: 11px;
                margin: 2px;
            }
        """)
        container_layout.addWidget(self.progress, 0, Qt.AlignmentFlag.AlignCenter)
        
        # Текст статуса - с правильными отступами и размерами
        self.status_label = QLabel(get_text("initializing"))
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)  # Включаем перенос строк
        self.status_label.setFixedSize(580, 100)  # Фиксированный размер
        self.status_label.setStyleSheet("""
            QLabel {
                font-size: 13px; 
                color: #b0b0b0; 
                padding: 15px;
                margin: 10px;
                background: rgba(0, 0, 0, 0.1);
                border-radius: 10px;
            }
        """)
        container_layout.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignCenter)
        
        layout.addWidget(container)
    
    def update_progress(self, value, status=""):
        """Обновляет прогресс"""
        self.progress.setValue(value)
        if status:
            self.status_label.setText(status)
        
        # Ограничиваем обработку событий только для этого диалога
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
    
    def closeEvent(self, event):
        """При закрытии убираем blur и восстанавливаем события мыши"""
        try:
            # Восстанавливаем события мыши для родительского окна
            if self.parent_widget:
                self.parent_widget.setEnabled(True)
                # Принудительно очищаем все события мыши
                QApplication.processEvents()
            
            if self.parent_widget and not self.keep_blur_on_close and not self.existing_blur:
                self.parent_widget.setGraphicsEffect(None)
                print("🔄 Blur effect removed from parent widget in closeEvent")
        except Exception as e:
            print(f"❌ Ошибка при убирании blur эффекта: {e}")
        super().closeEvent(event)
    
    def showEvent(self, event):
        super().showEvent(event)
        # Центрируем диалог
        if self.parent_widget:
            parent_rect = self.parent_widget.geometry()
            self.move(
                parent_rect.x() + (parent_rect.width() - self.width()) // 2,
                parent_rect.y() + (parent_rect.height() - self.height()) // 2
            )
        # Запускаем анимации (только если blur новый)
        if self.blur_anim:
            self.blur_anim.start()
        self.opacity_anim.start()


class BlurDialog(QDialog):
    """Welcome диалог в стиле кастомных диалогов"""
    def __init__(self, parent=None, keep_blur_on_close=False):
        super().__init__(parent)
        self.parent_widget = parent
        self.keep_blur_on_close = keep_blur_on_close
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        
        # Размытие фона с анимацией
        if parent:
            self.blur_effect = QGraphicsBlurEffect()
            self.blur_effect.setBlurRadius(0)
            parent.setGraphicsEffect(self.blur_effect)
            
            # Анимация блюра
            self.blur_anim = QPropertyAnimation(self.blur_effect, b"blurRadius")
            self.blur_anim.setDuration(300)
            self.blur_anim.setStartValue(0)
            self.blur_anim.setEndValue(15)
            self.blur_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        else:
            self.blur_anim = None
        
        self.setup_ui()
        
        # Анимация появления диалога
        self.setWindowOpacity(0)
        self.opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_anim.setDuration(300)
        self.opacity_anim.setStartValue(0)
        self.opacity_anim.setEndValue(1)
        self.opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    
    def closeEvent(self, event):
        """При закрытии убираем blur (если не указано keep_blur_on_close)"""
        if self.parent_widget and not self.keep_blur_on_close:
            self.parent_widget.setGraphicsEffect(None)
        super().closeEvent(event)
    
    def accept(self):
        """При accept убираем blur (если не указано keep_blur_on_close)"""
        if self.parent_widget and not self.keep_blur_on_close:
            self.parent_widget.setGraphicsEffect(None)
        super().accept()
    
    def reject(self):
        """При reject убираем blur (если не указано keep_blur_on_close)"""
        if self.parent_widget and not self.keep_blur_on_close:
            self.parent_widget.setGraphicsEffect(None)
        super().reject()
    
    def open_steam_profile(self):
        """Открывает Steam профиль автора"""
        import webbrowser
        webbrowser.open("https://steamcommunity.com/id/kinimaro/")
    
    def open_telegram(self):
        """Открывает Telegram профиль автора"""
        import webbrowser
        webbrowser.open("https://t.me/angel_its_me")
    
    def setup_ui(self):
        # Увеличенный размер диалога чтобы все помещалось
        self.setFixedSize(700, 750)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Контейнер без фона (прозрачный)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(20)
        container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Логотип - БОЛЬШОЙ 250x250, БЕЗ перекраски
        icon_label = QLabel()
        logo_path = get_resource_path("logo.png")
        if logo_path.exists():
            pixmap = QPixmap(str(logo_path))
            if not pixmap.isNull():
                # Увеличенный размер: 250x250
                scaled_pixmap = pixmap.scaled(250, 250, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                # Используем оригинальный цвет, БЕЗ перекраски
                icon_label.setPixmap(scaled_pixmap)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(icon_label)
        
        # Заголовок - ЕДИНЫЙ СТАНДАРТ
        title_label = QLabel(get_text("app_title"))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 20px; font-weight: 600; color: white;")
        container_layout.addWidget(title_label)
        
        # Подзаголовок
        subtitle = QLabel("by k1n1maro")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("font-size: 12px; color: #7f8c8d;")
        container_layout.addWidget(subtitle)
        
        # Описание программы - ЕДИНЫЙ СТАНДАРТ
        desc = QLabel(get_text("welcome_message"))
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 13px; color: white; line-height: 1.6;")
        container_layout.addWidget(desc)
        
        # Отступ перед кнопкой
        container_layout.addSpacing(20)
        
        # Кнопка "Начать"
        btn = AnimatedActionButton(get_text("welcome_btn_start"), None)
        btn.setFixedSize(140, 50)
        btn.clicked.connect(self.accept_dialog)
        btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3498db, stop:1 #2980b9);
                border: none;
                border-radius: 25px;
                color: white;
                padding: 15px 40px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #5dade2, stop:1 #3498db);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #2980b9, stop:1 #21618c);
            }
        """)
        container_layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        layout.addWidget(container)
    
    def accept_dialog(self):
        """Закрывает диалог с анимацией"""
        # Анимация исчезновения
        self.opacity_anim.setDirection(QPropertyAnimation.Direction.Backward)
        self.opacity_anim.start()
        
        # Анимация убирания блюра (только если не нужно сохранять blur)
        if self.blur_anim and not self.keep_blur_on_close:
            self.blur_anim.setDirection(QPropertyAnimation.Direction.Backward)
            self.blur_anim.start()
        
        # Закрываем после анимации
        QTimer.singleShot(300, self.accept)
    
    def showEvent(self, event):
        super().showEvent(event)
        # Центрируем диалог
        if self.parent_widget:
            parent_rect = self.parent_widget.geometry()
            self.move(
                parent_rect.x() + (parent_rect.width() - self.width()) // 2,
                parent_rect.y() + (parent_rect.height() - self.height()) // 2
            )
        # Запускаем анимации
        if self.blur_anim:
            self.blur_anim.start()
        self.opacity_anim.start()



class SetupDialog(QDialog):
    """Диалог настройки пути к игре"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_widget = parent
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Размытие фона
        if parent:
            self.blur_effect = QGraphicsBlurEffect()
            self.blur_effect.setBlurRadius(30)
            self.blur_effect.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
            parent.setGraphicsEffect(self.blur_effect)
        
        self.setup_ui()
    
    def closeEvent(self, event):
        """При закрытии убираем blur"""
        if self.parent_widget:
            self.parent_widget.setGraphicsEffect(None)
        super().closeEvent(event)
    
    def accept(self):
        """При accept убираем blur"""
        if self.parent_widget:
            self.parent_widget.setGraphicsEffect(None)
        super().accept()
    
    def reject(self):
        """При reject убираем blur"""
        if self.parent_widget:
            self.parent_widget.setGraphicsEffect(None)
        super().reject()
    
    def showEvent(self, event):
        """Центрируем диалог при показе"""
        super().showEvent(event)
        if self.parent_widget:
            parent_rect = self.parent_widget.geometry()
            self.move(
                parent_rect.x() + (parent_rect.width() - self.width()) // 2,
                parent_rect.y() + (parent_rect.height() - self.height()) // 2
            )
    
    def setup_ui(self):
        # Фиксированный размер как у других кастомных диалогов
        self.setFixedSize(700, 520)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)  # Равные отступы со всех сторон
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Контейнер без фона (прозрачный)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(20)
        container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Иконка folder.png залитая синим цветом - ЕДИНЫЙ СТАНДАРТ 120x120
        icon_label = QLabel()
        icon_path = get_resource_path("folder.png")
        if icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                # ЕДИНЫЙ СТАНДАРТ: 120x120
                scaled_pixmap = pixmap.scaled(120, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                
                # Перекрашиваем в синий цвет #3498db
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
        # Небольшой отступ слева для идеального центрирования
        icon_label.setContentsMargins(10, 0, 0, 0)
        container_layout.addWidget(icon_label)
        
        # Заголовок - ЕДИНЫЙ СТАНДАРТ
        title = QLabel(get_text("setup_title"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 20px; font-weight: 600; color: white;")
        container_layout.addWidget(title)
        
        # Описание - ЕДИНЫЙ СТАНДАРТ
        desc = QLabel(get_text("setup_description"))
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 13px; color: white;")
        container_layout.addWidget(desc)
        
        container_layout.addSpacing(10)
        
        # Кнопка выбора (без смайлика)
        btn = AnimatedActionButton(get_text("btn_browse_folder"), None)
        btn.setFixedSize(180, 50)
        btn.clicked.connect(self.browse_folder)
        container_layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        layout.addWidget(container)
    
    def browse_folder(self):
        """Выбор папки с игрой"""
        folder = QFileDialog.getExistingDirectory(
            self,
            get_text("select_l4d2_folder"),
            str(Path.home())
        )
        if folder:
            test_path = Path(folder)
            # Проверяем что выбрана правильная папка
            if (test_path / "left4dead2" / "gameinfo.txt").exists():
                print(f"✅ Valid game folder selected: {test_path}")
                self.parent_widget.game_folder = test_path
                if hasattr(self.parent_widget, 'path_input'):
                    self.parent_widget.path_input.setText(folder)
                
                print("🔄 Updating paths...")
                self.parent_widget.update_paths()
                print(f"   Updated workshop_path: {self.parent_widget.workshop_path}")
                
                self.parent_widget.save_config()
                
                # Автоматически сканируем аддоны после выбора папки (только один раз)
                if hasattr(self.parent_widget, 'scan_addons'):
                    print("⏰ Scheduling scan_addons in 300ms...")
                    QTimer.singleShot(300, self.parent_widget.scan_addons)
                
                # Также сканируем пиратские аддоны
                if hasattr(self.parent_widget, 'scan_pirate_addons'):
                    print("⏰ Scheduling scan_pirate_addons in 400ms...")
                    QTimer.singleShot(400, self.parent_widget.scan_pirate_addons)
                
                self.accept()
            else:
                # Делаем SetupDialog полупрозрачным чтобы избежать наложения
                self.setWindowOpacity(0.0)
                
                # Показываем диалог ошибки через небольшую задержку
                QTimer.singleShot(50, lambda: self.show_error_and_reopen())
    
    def show_error_and_reopen(self):
        """Показывает ошибку и возвращает SetupDialog"""
        # Показываем кастомный диалог ошибки
        CustomInfoDialog.information(
            self.parent_widget,
            get_text("invalid_folder_title"),
            get_text("invalid_folder_message"),
            use_existing_blur=True,  # Используем существующий blur
            icon_type="error"
        )
        
        # После закрытия диалога ошибки возвращаем видимость SetupDialog
        self.setWindowOpacity(1.0)


class SettingsCard(QFrame):
    """Карточка настроек с hover анимацией"""
    
    def __init__(self, title, subtitle, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsCard")
        
        card_layout = QVBoxLayout(self)
        card_layout.setContentsMargins(20, 15, 20, 15)
        card_layout.setSpacing(10)
        
        # Заголовок
        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        card_layout.addWidget(title_label)
        
        # Подзаголовок
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("cardSubtitle")
        card_layout.addWidget(subtitle_label)
        
        # Opacity эффект для анимации появления
        opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(opacity_effect)
        self.opacity_effect = opacity_effect
        
        # Сохраняем оригинальную геометрию для возврата
        self.original_geometry = None
        
        # Scale анимация для hover
        self.scale_anim = QPropertyAnimation(self, b"geometry")
        self.scale_anim.setDuration(200)
        self.scale_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    
    def resizeEvent(self, event):
        """Обновляем оригинальную геометрию при изменении размера"""
        super().resizeEvent(event)
        # Обновляем оригинальную геометрию только если анимация не идет
        if not self.scale_anim.state() == QPropertyAnimation.State.Running:
            self.original_geometry = self.geometry()
    
    def showEvent(self, event):
        """Сохраняем оригинальную геометрию при первом показе"""
        super().showEvent(event)
        self.original_geometry = self.geometry()
    
    def enterEvent(self, event):
        """Hover - минимальное увеличение чтобы текст не уезжал"""
        super().enterEvent(event)
        
        if self.original_geometry is None:
            self.original_geometry = self.geometry()
        
        # Целевой размер
        target = self.original_geometry.adjusted(-2, -2, 2, 2)
        current = self.geometry()
        
        # Если уже близко к цели - не запускаем анимацию
        if abs(current.width() - target.width()) < 1:
            return
        
        # Останавливаем и перезапускаем с текущей позиции
        self.scale_anim.stop()
        self.scale_anim.setStartValue(current)
        self.scale_anim.setEndValue(target)
        self.scale_anim.start()
    
    def leaveEvent(self, event):
        """Уход - возврат к оригинальному размеру"""
        super().leaveEvent(event)
        if self.original_geometry is None:
            return
        
        target = self.original_geometry
        current = self.geometry()
        
        # Если уже близко к цели - не запускаем анимацию
        if abs(current.width() - target.width()) < 1:
            return
        
        # Останавливаем и перезапускаем с текущей позиции
        self.scale_anim.stop()
        self.scale_anim.setStartValue(current)
        self.scale_anim.setEndValue(target)
        self.scale_anim.start()


class AnimatedToggle(QCheckBox):
    """Красивый анимированный переключатель в стиле iOS"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(60, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Инициализация позиции ручки
        self._handle_position = 0
        self._is_first_show = True  # Флаг для первого показа
        self._widget_shown = False  # Флаг что виджет был показан
        
        # Анимация перемещения ручки
        self.animation = QPropertyAnimation(self, b"handle_position")
        self.animation.setDuration(200)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        
        self.stateChanged.connect(self.on_state_changed)
    
    def on_state_changed(self, state):
        """Анимация при изменении состояния"""
        # Если виджет ещё не был показан, просто обновляем позицию без анимации
        if not self._widget_shown:
            if state == Qt.CheckState.Checked.value:
                self._handle_position = 30
            else:
                self._handle_position = 0
            self.update()
            return
        
        # Иначе запускаем анимацию
        if state == Qt.CheckState.Checked.value:
            self.animation.setStartValue(self._handle_position)
            self.animation.setEndValue(30)
        else:
            self.animation.setStartValue(self._handle_position)
            self.animation.setEndValue(0)
        self.animation.start()
    
    @pyqtProperty(int)
    def handle_position(self):
        return self._handle_position
    
    @handle_position.setter
    def handle_position(self, pos):
        self._handle_position = pos
        self.update()
    
    def paintEvent(self, event):
        """Рисуем переключатель"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        
        # Фон переключателя
        if self.isChecked():
            # Синий цвет когда включен (как на welcome экране)
            bg_color = QColor(52, 152, 219)  # #3498db
        else:
            # Серый когда выключен
            bg_color = QColor(100, 100, 100)
        
        painter.setBrush(QBrush(bg_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, 60, 30, 15, 15)
        
        # Текст ON/OFF
        painter.setPen(QColor(255, 255, 255, 180))  # Полупрозрачный белый
        font = painter.font()
        font.setPixelSize(10)
        font.setBold(True)
        painter.setFont(font)
        
        if self.isChecked():
            # Текст "ON" слева - используем весь прямоугольник для выравнивания
            painter.drawText(5, 0, 25, 30, Qt.AlignmentFlag.AlignCenter, "ON")
        else:
            # Текст "OFF" справа - используем весь прямоугольник для выравнивания
            painter.drawText(30, 0, 25, 30, Qt.AlignmentFlag.AlignCenter, "OFF")
        
        # Белая ручка
        handle_color = QColor(255, 255, 255)
        painter.setBrush(QBrush(handle_color))
        
        # Тень для ручки
        painter.setPen(QPen(QColor(0, 0, 0, 30), 2))
        painter.drawEllipse(int(self._handle_position) + 3, 3, 24, 24)
    
    def hitButton(self, pos):
        """Вся область переключателя кликабельна"""
        return self.rect().contains(pos)
    
    def showEvent(self, event):
        """Устанавливаем правильную начальную позицию при показе"""
        super().showEvent(event)
        # Устанавливаем позицию ручки без анимации только при первом показе
        if self._is_first_show:
            if self.isChecked():
                self._handle_position = 30
            else:
                self._handle_position = 0
            self._is_first_show = False
            self.update()
        
        # Отмечаем что виджет был показан
        self._widget_shown = True
    
    def enterEvent(self, event):
        """Эффект при наведении"""
        super().enterEvent(event)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
    
    def mousePressEvent(self, event):
        """Обработка нажатия мыши"""
        if event.button() == Qt.MouseButton.LeftButton:
            # Просто принимаем событие, не вызываем super()
            event.accept()
        else:
            event.ignore()
    
    def mouseReleaseEvent(self, event):
        """Обработка отпускания мыши - переключаем состояние"""
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            # Переключаем состояние
            self.setChecked(not self.isChecked())
            event.accept()
        else:
            event.ignore()


class AnimatedSortComboBox(QPushButton):
    """Кнопка сортировки с выпадающим меню"""
    
    currentIndexChanged = pyqtSignal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sortCombo")
        self.setFixedSize(45, 45)
        self.setToolTip(get_text("sort_tooltip"))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.current_index = 0
        self._scale = 1.0
        self.blur_effect = None
        self._menu_open = False  # Флаг состояния меню
        
        # Анимация масштабирования иконки (меньше увеличение)
        self.scale_anim = QPropertyAnimation(self, b"scale")
        self.scale_anim.setDuration(200)
        self.scale_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        # Загружаем и перекрашиваем иконку sort.png
        self.sort_pixmap = None
        sort_icon_path = get_resource_path("sort.png")
        if sort_icon_path.exists():
            pixmap = QPixmap(str(sort_icon_path))
            # Перекрашиваем в белый цвет
            painter = QPainter(pixmap)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(pixmap.rect(), QColor(255, 255, 255, 160))
            painter.end()
            
            # Масштабируем до 16x16 (меньше для лучшего вида при увеличении)
            self.sort_pixmap = pixmap.scaled(16, 16, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        
        # Создаем меню
        self.menu = QMenu(self)
        self.menu.setObjectName("sortMenu")
        self.menu.setWindowFlags(self.menu.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Анимация появления меню (fade in)
        self.menu_opacity = QGraphicsOpacityEffect(self.menu)
        self.menu.setGraphicsEffect(self.menu_opacity)
        
        self.menu_fade = QPropertyAnimation(self.menu_opacity, b"opacity")
        self.menu_fade.setDuration(500)  # Увеличил до 500ms для большей плавности
        self.menu_fade.setStartValue(0)
        self.menu_fade.setEndValue(1)
        self.menu_fade.setEasingCurve(QEasingCurve.Type.OutCubic)  # Более плавная кривая
        
        # Анимация slide up (выезжает снизу вверх)
        self.menu_slide = QPropertyAnimation(self.menu, b"pos")
        self.menu_slide.setDuration(500)  # Увеличил до 500ms для большей плавности
        self.menu_slide.setEasingCurve(QEasingCurve.Type.OutCubic)  # Более плавная кривая
        
        # Анимация scale (масштабирование из иконки)
        self.menu_scale = QPropertyAnimation(self.menu, b"geometry")
        self.menu_scale.setDuration(500)  # Увеличил до 500ms для большей плавности
        self.menu_scale.setEasingCurve(QEasingCurve.Type.OutCubic)  # Более плавная кривая без отскока
        
        self.actions = []
        options = [get_text("sort_alphabetical"), get_text("sort_enabled_first"), get_text("sort_disabled_first")]
        for i, text in enumerate(options):
            action = self.menu.addAction(text)
            action.setCheckable(True)
            action.triggered.connect(lambda checked, idx=i: self.on_action_triggered(idx))
            self.actions.append(action)
        
        # Устанавливаем первый вариант как выбранный
        self.actions[0].setChecked(True)
        
        # Блокер будет None пока не нужен
        self.blocker = None
        
        # Подключаем clicked сигнал
        self.clicked.connect(self.show_menu)
    
    @pyqtProperty(float)
    def scale(self):
        return self._scale
    
    @scale.setter
    def scale(self, value):
        self._scale = value
        self.update()
    
    def enterEvent(self, event):
        """Анимация при наведении - увеличение иконки"""
        super().enterEvent(event)
        self.scale_anim.setStartValue(self._scale)
        self.scale_anim.setEndValue(1.1)  # Уменьшил с 1.15 до 1.1
        self.scale_anim.start()
    
    def leaveEvent(self, event):
        """Возврат к исходному размеру"""
        super().leaveEvent(event)
        self.scale_anim.setStartValue(self._scale)
        self.scale_anim.setEndValue(1.0)
        self.scale_anim.start()
    
    def apply_blur(self):
        """Применяет blur эффект ко всему центральному виджету с плавной анимацией"""
        main_window = self.window()
        if main_window:
            central_widget = main_window.centralWidget()
            if central_widget and not central_widget.graphicsEffect():
                self.blur_effect = QGraphicsBlurEffect()
                self.blur_effect.setBlurRadius(0)  # Начинаем с 0
                self.blur_effect.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
                central_widget.setGraphicsEffect(self.blur_effect)
                
                # Анимация плавного увеличения blur
                self.blur_anim = QPropertyAnimation(self.blur_effect, b"blurRadius")
                self.blur_anim.setDuration(500)  # Синхронизируем с анимацией меню
                self.blur_anim.setStartValue(0)
                self.blur_anim.setEndValue(20)
                self.blur_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                self.blur_anim.start()
    
    def remove_blur(self):
        """Убирает blur эффект с центрального виджета с плавной анимацией"""
        main_window = self.window()
        if main_window:
            central_widget = main_window.centralWidget()
            if central_widget and self.blur_effect:
                # Анимация плавного уменьшения blur
                blur_out_anim = QPropertyAnimation(self.blur_effect, b"blurRadius")
                blur_out_anim.setDuration(300)  # Быстрее при закрытии
                blur_out_anim.setStartValue(20)
                blur_out_anim.setEndValue(0)
                blur_out_anim.setEasingCurve(QEasingCurve.Type.InCubic)
                # Убираем эффект после завершения анимации
                blur_out_anim.finished.connect(lambda: central_widget.setGraphicsEffect(None))
                blur_out_anim.start()
                
                # Сохраняем ссылку чтобы анимация не удалилась
                self.blur_out_anim = blur_out_anim
            self.blur_effect = None
    
    def show_menu(self):
        """Показывает меню с анимацией scale (масштабирование из иконки) и blur эффектом"""
        # КРИТИЧЕСКИ ВАЖНО: проверяем флаг в самом начале
        if self._menu_open:
            return  # Полностью игнорируем клики пока меню открыто
        
        # Проверяем, не видимо ли уже меню
        if self.menu.isVisible():
            return  # Меню уже открыто, игнорируем
        
        # Устанавливаем флаг что меню открыто
        self._menu_open = True
        
        # Создаем и показываем блокер поверх кнопки
        if not self.blocker:
            self.blocker = QLabel(self)
            self.blocker.setGeometry(0, 0, self.width(), self.height())
            self.blocker.setStyleSheet("background: transparent;")
            self.blocker.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            # Устанавливаем обработчик событий мыши на блокер
            self.blocker.mousePressEvent = lambda e: e.accept()
            self.blocker.mouseReleaseEvent = lambda e: e.accept()
        
        self.blocker.raise_()  # Поднимаем на передний план
        self.blocker.show()
        
        self.update()  # Перерисовываем кнопку без обводки
        
        # Применяем blur ко всему экрану
        self.apply_blur()
        
        # Позиционируем меню НАД кнопкой
        self.menu.adjustSize()
        menu_height = self.menu.sizeHint().height()
        menu_width = self.menu.sizeHint().width()
        
        # Получаем позицию кнопки
        button_pos = self.mapToGlobal(self.rect().topLeft())
        button_center = self.mapToGlobal(self.rect().center())
        
        # Финальная позиция меню (над кнопкой)
        final_pos = QPoint(button_pos.x(), button_pos.y() - menu_height - 5)
        
        # Проверяем границы окна
        main_window = self.window()
        if main_window:
            window_rect = main_window.geometry()
            
            # Если меню выходит за верхнюю границу, показываем СНИЗУ
            if final_pos.y() < window_rect.top():
                final_pos.setY(button_pos.y() + self.height() + 5)
            
            # Проверяем правую границу
            if final_pos.x() + menu_width > window_rect.right():
                final_pos.setX(window_rect.right() - menu_width - 10)
            
            # Проверяем левую границу
            if final_pos.x() < window_rect.left():
                final_pos.setX(window_rect.left() + 10)
        
        # Финальная геометрия меню
        final_geometry = QRect(final_pos.x(), final_pos.y(), menu_width, menu_height)
        
        # Начальная геометрия - маленькая точка в центре иконки (scale from 0)
        start_geometry = QRect(
            button_center.x() - 1,  # Центр иконки по X
            button_center.y() - 1,  # Центр иконки по Y
            2,  # Минимальная ширина
            2   # Минимальная высота
        )
        
        # Настраиваем анимацию scale (масштабирование из центра иконки)
        self.menu_scale.setStartValue(start_geometry)
        self.menu_scale.setEndValue(final_geometry)
        
        # Запускаем обе анимации одновременно (fade + scale)
        self.menu_fade.start()
        self.menu_scale.start()
        
        # Подключаем обработчик закрытия меню (используем aboutToHide вместо finished)
        try:
            self.menu.aboutToHide.disconnect()  # Отключаем предыдущие подключения
        except:
            pass
        self.menu.aboutToHide.connect(self.on_menu_closed)
        
        # Показываем меню (НЕБЛОКИРУЮЩИЙ вызов)
        self.menu.popup(final_pos)
    
    def on_menu_closed(self):
        """Обработчик закрытия меню"""
        # Убираем blur после закрытия меню
        self.remove_blur()
        
        # ВАЖНО: добавляем небольшую задержку перед сбросом флага
        # чтобы предотвратить повторное открытие меню от того же клика
        QTimer.singleShot(100, self._reset_menu_state)
    
    def _reset_menu_state(self):
        """Сбрасываем состояние меню с задержкой"""
        self._menu_open = False
        
        # СКРЫВАЕМ БЛОКЕР
        if self.blocker:
            self.blocker.hide()
        
        self.update()  # Перерисовываем кнопку с обводкой
    
    def on_action_triggered(self, index):
        """Обработка выбора варианта"""
        # Снимаем галочки со всех
        for action in self.actions:
            action.setChecked(False)
        
        # Ставим галочку на выбранный
        self.actions[index].setChecked(True)
        
        # Сохраняем индекс
        self.current_index = index
        
        # Эмитим сигнал
        self.currentIndexChanged.emit(index)
    
    def currentIndex(self):
        """Возвращает текущий индекс"""
        return self.current_index
    
    def paintEvent(self, event):
        """Рисуем кнопку с масштабируемой иконкой"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        # Рисуем фон
        if self.underMouse():
            if self.isDown():
                painter.setBrush(QBrush(QColor(31, 31, 31)))
            else:
                painter.setBrush(QBrush(QColor(26, 26, 26)))
        else:
            painter.setBrush(QBrush(QColor(26, 26, 26)))
        
        # Обводка 2px как у меню (скрываем когда меню открыто)
        if self._menu_open:
            # Когда меню открыто - обычная серая обводка без подсветки
            painter.setPen(QPen(QColor(42, 42, 42), 2))
        else:
            # Когда меню закрыто - показываем hover эффект
            painter.setPen(QPen(QColor(42, 42, 42), 2))
            if self.underMouse():
                painter.setPen(QPen(QColor(52, 152, 219), 2))
        
        painter.drawRoundedRect(1, 1, self.width() - 2, self.height() - 2, 10, 10)
        
        # Рисуем иконку с масштабированием
        if self.sort_pixmap:
            painter.save()
            # Перемещаемся в центр кнопки
            painter.translate(self.width() / 2, self.height() / 2)
            # Масштабируем
            painter.scale(self._scale, self._scale)
            # Рисуем иконку относительно центра (16/2 = 8)
            painter.drawPixmap(-8, -8, self.sort_pixmap)
            painter.restore()


class AnimatedViewToggleButton(QPushButton):
    """Кнопка переключения режима отображения (1/2 столбца)"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("viewToggle")
        self.setFixedSize(45, 45)
        self.setToolTip(get_text("tooltip_view_toggle"))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.is_two_columns = False  # По умолчанию 1 столбец
        self._scale = 1.0
        
        # Анимация масштабирования
        self.scale_anim = QPropertyAnimation(self, b"scale")
        self.scale_anim.setDuration(200)
        self.scale_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    
    @pyqtProperty(float)
    def scale(self):
        return self._scale
    
    @scale.setter
    def scale(self, value):
        self._scale = value
        self.update()
    
    def enterEvent(self, event):
        """Анимация при наведении"""
        super().enterEvent(event)
        self.scale_anim.setStartValue(self._scale)
        self.scale_anim.setEndValue(1.1)
        self.scale_anim.start()
    
    def leaveEvent(self, event):
        """Возврат к исходному размеру"""
        super().leaveEvent(event)
        self.scale_anim.setStartValue(self._scale)
        self.scale_anim.setEndValue(1.0)
        self.scale_anim.start()
    
    def paintEvent(self, event):
        """Рисуем кнопку с иконкой столбцов"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Рисуем фон
        if self.underMouse():
            if self.isDown():
                painter.setBrush(QBrush(QColor(31, 31, 31)))
            else:
                painter.setBrush(QBrush(QColor(26, 26, 26)))
        else:
            painter.setBrush(QBrush(QColor(26, 26, 26)))
        
        # Обводка
        painter.setPen(QPen(QColor(42, 42, 42), 2))
        if self.underMouse():
            painter.setPen(QPen(QColor(52, 152, 219), 2))
        
        painter.drawRoundedRect(1, 1, self.width() - 2, self.height() - 2, 10, 10)
        
        # Рисуем иконку столбцов
        painter.save()
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(self._scale, self._scale)
        
        # Цвет иконки
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(255, 255, 255, 160)))
        
        if self.is_two_columns:
            # Рисуем 2 столбца (2 прямоугольника)
            painter.drawRoundedRect(-10, -8, 8, 16, 2, 2)  # Левый столбец
            painter.drawRoundedRect(2, -8, 8, 16, 2, 2)    # Правый столбец
        else:
            # Рисуем 1 столбец (1 прямоугольник)
            painter.drawRoundedRect(-6, -8, 12, 16, 2, 2)
        
        painter.restore()


class AnimatedClearButton(QPushButton):
    """Кнопка очистки с анимацией вращения"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("clearSearchBtn")
        self.setFixedSize(40, 40)
        self.setToolTip(get_text("clear_search_tooltip"))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Инициализируем rotation ДО создания анимации
        self._rotation = 0
        
        # Анимация вращения
        self.rotation_anim = QPropertyAnimation(self, b"rotation")
        self.rotation_anim.setDuration(200)
        self.rotation_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    
    @pyqtProperty(int)
    def rotation(self):
        return self._rotation
    
    @rotation.setter
    def rotation(self, angle):
        self._rotation = angle
        # Применяем трансформацию к иконке
        transform = QTransform()
        transform.rotate(angle)
        if not self.icon().isNull():
            # Обновляем отображение
            self.update()
    
    def enterEvent(self, event):
        """Анимация при наведении - вращение на 90 градусов"""
        super().enterEvent(event)
        self.rotation_anim.setStartValue(self._rotation)
        self.rotation_anim.setEndValue(90)
        self.rotation_anim.start()
    
    def leaveEvent(self, event):
        """Возврат к исходному положению"""
        super().leaveEvent(event)
        self.rotation_anim.setStartValue(self._rotation)
        self.rotation_anim.setEndValue(0)
        self.rotation_anim.start()
    
    def paintEvent(self, event):
        """Рисуем кнопку с повернутой иконкой (без фона)"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        # Рисуем только иконку с вращением (без фона)
        if not self.icon().isNull():
            painter.save()
            painter.translate(20, 20)  # Центр кнопки
            painter.rotate(self._rotation)
            painter.translate(-12, -12)  # Половина размера иконки (24/2)
            
            pixmap = self.icon().pixmap(QSize(24, 24))
            painter.drawPixmap(0, 0, pixmap)
            painter.restore()


class AnimatedRefreshButton(QPushButton):
    """Кнопка обновления с анимацией вращения на 360 градусов"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("refreshBtn")
        self.setFixedSize(45, 45)
        self.setToolTip(get_text("btn_refresh"))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Инициализируем rotation ДО создания анимации
        self._rotation = 0
        
        # Анимация вращения на 360 градусов при клике
        self.rotation_anim = QPropertyAnimation(self, b"rotation")
        self.rotation_anim.setDuration(800)  # Увеличил с 600 до 800ms для плавности
        self.rotation_anim.setEasingCurve(QEasingCurve.Type.InOutQuart)  # Более плавная кривая с плавным стартом и финишем
        
        # Анимация вращения при hover (один раз)
        self.hover_anim = QPropertyAnimation(self, b"rotation")
        self.hover_anim.setDuration(800)  # Увеличил с 600 до 800ms для плавности
        self.hover_anim.setEasingCurve(QEasingCurve.Type.InOutQuart)  # Более плавная кривая с плавным стартом и финишем
        
        # Загружаем и перекрашиваем иконку ref.png
        self.ref_pixmap = None
        ref_icon_path = get_resource_path("ref.png")
        if ref_icon_path.exists():
            pixmap = QPixmap(str(ref_icon_path))
            # Перекрашиваем в белый цвет (более прозрачный для тонкости)
            painter = QPainter(pixmap)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(pixmap.rect(), QColor(255, 255, 255, 160))  # Уменьшил прозрачность с 200 до 160
            painter.end()
            
            # Масштабируем до 16x16 (как у sort.png)
            self.ref_pixmap = pixmap.scaled(16, 16, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    
    @pyqtProperty(int)
    def rotation(self):
        return self._rotation
    
    @rotation.setter
    def rotation(self, angle):
        self._rotation = angle
        self.update()
    
    def enterEvent(self, event):
        """При наведении - проигрываем анимацию"""
        super().enterEvent(event)
        # Проигрываем анимацию только если быстрое вращение не запущено
        if self.rotation_anim.state() != QPropertyAnimation.State.Running:
            self.hover_anim.stop()
            self.hover_anim.setStartValue(self._rotation % 360)
            self.hover_anim.setEndValue(self._rotation + 360)
            self.hover_anim.start()
        self.update()
    
    def leaveEvent(self, event):
        """При уходе мыши - ничего не делаем"""
        super().leaveEvent(event)
        self.update()
    
    def mousePressEvent(self, event):
        """При клике запускаем быструю анимацию вращения"""
        if event.button() == Qt.MouseButton.LeftButton:
            # Останавливаем hover анимацию
            self.hover_anim.stop()
            # Запускаем быстрое вращение на 360 градусов
            self.rotation_anim.stop()
            self.rotation_anim.setStartValue(self._rotation % 360)
            self.rotation_anim.setEndValue(self._rotation + 360)
            self.rotation_anim.start()
        super().mousePressEvent(event)
    
    def paintEvent(self, event):
        """Рисуем кнопку с вращающейся иконкой"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        # Рисуем фон кнопки
        if self.underMouse():
            if self.isDown():
                painter.setBrush(QBrush(QColor(26, 26, 26)))
            else:
                painter.setBrush(QBrush(QColor(26, 26, 26)))
        else:
            painter.setBrush(QBrush(QColor(26, 26, 26)))
        
        # Обводка
        painter.setPen(QPen(QColor(42, 42, 42), 2))
        if self.underMouse():
            painter.setPen(QPen(QColor(52, 152, 219), 2))
        
        painter.drawRoundedRect(1, 1, self.width() - 2, self.height() - 2, 22, 22)
        
        # Рисуем иконку с вращением
        if self.ref_pixmap:
            painter.save()
            painter.translate(22.5, 22.5)  # Центр кнопки
            painter.rotate(self._rotation)
            painter.translate(-8, -8)  # Половина размера иконки (16/2)
            
            painter.drawPixmap(0, 0, self.ref_pixmap)
            painter.restore()


class AnimatedTabButton(QPushButton):
    """Кнопка таба с анимацией подпрыгивания иконки и текста"""
    
    def __init__(self, text, icon_name, parent=None):
        super().__init__(parent)
        self.button_text = text
        self.setObjectName("tabBtn")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Инициализируем y_offset для анимации подпрыгивания
        self._y_offset = 0
        
        # Загружаем и перекрашиваем иконку
        self.icon_pixmap = None
        icon_path = get_resource_path(icon_name)
        if icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            # Перекрашиваем в белый цвет
            painter = QPainter(pixmap)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(pixmap.rect(), QColor(255, 255, 255, 200))
            painter.end()
            
            # Масштабируем до 18x18 для табов
            self.icon_pixmap = pixmap.scaled(18, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        
        # Вычисляем ширину кнопки на основе текста
        font = QFont()
        font.setPixelSize(11)
        fm = QFontMetrics(font)
        text_width = fm.horizontalAdvance(text)
        # Ширина = отступ слева (10) + иконка (18) + отступ (7) + текст + отступ справа (15)
        button_width = 10 + 18 + 7 + text_width + 15
        self.setFixedWidth(button_width)
        
        # Анимация подпрыгивания
        self.bounce_anim = QPropertyAnimation(self, b"y_offset")
        self.bounce_anim.setDuration(300)
        self.bounce_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    
    @pyqtProperty(int)
    def y_offset(self):
        return self._y_offset
    
    @y_offset.setter
    def y_offset(self, value):
        self._y_offset = value
        self.update()
    
    def enterEvent(self, event):
        """При наведении - подпрыгивает"""
        super().enterEvent(event)
        if not self.isChecked():  # Анимация только если не активна
            self.bounce_anim.stop()
            self.bounce_anim.setStartValue(0)
            self.bounce_anim.setKeyValueAt(0.5, -5)  # Подпрыгивает на 5px вверх
            self.bounce_anim.setEndValue(0)
            self.bounce_anim.start()
    
    def leaveEvent(self, event):
        """При уходе - сброс"""
        super().leaveEvent(event)
        self._y_offset = 0
        self.update()
    
    def paintEvent(self, event):
        """Рисуем кнопку с иконкой, текстом и синей полоской снизу"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        # Цвет текста и иконки
        if self.isChecked():
            color = QColor(52, 152, 219)  # Синий для активной вкладки
        elif self.underMouse():
            color = QColor(180, 180, 180)  # Светло-серый при hover
        else:
            color = QColor(140, 140, 140)  # Серый для неактивной
        
        # Рисуем иконку с учетом y_offset
        if self.icon_pixmap:
            # Перекрашиваем иконку в нужный цвет
            colored_pixmap = QPixmap(self.icon_pixmap.size())
            colored_pixmap.fill(Qt.GlobalColor.transparent)
            
            icon_painter = QPainter(colored_pixmap)
            icon_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            icon_painter.drawPixmap(0, 0, self.icon_pixmap)
            icon_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            icon_painter.fillRect(colored_pixmap.rect(), color)
            icon_painter.end()
            
            # Позиция иконки (слева от текста)
            icon_x = 10
            icon_y = (self.height() - 18) / 2 + self._y_offset - 2  # -2 чтобы поднять выше для полоски
            painter.drawPixmap(int(icon_x), int(icon_y), colored_pixmap)
        
        # Рисуем текст с учетом y_offset и измеряем его ширину
        painter.setPen(color)
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)
        
        text_rect = QRect(35, int(self._y_offset) - 2, self.width() - 35, self.height())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.button_text)
        
        # Рисуем синюю полоску снизу если вкладка активна
        if self.isChecked():
            # Измеряем ширину текста
            text_width = painter.fontMetrics().horizontalAdvance(self.button_text)
            # Общая ширина контента: иконка (18px) + отступ (7px) + текст
            content_width = 18 + 7 + text_width
            
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(52, 152, 219)))  # Синий цвет
            # Полоска высотой 3px внизу кнопки, начинается с позиции иконки (10px) и длиной как контент
            painter.drawRect(10, self.height() - 3, int(content_width), 3)


class AnimatedTrashButton(QPushButton):
    """Кнопка удаления с иконкой мусорки и анимацией"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("trashBtn")
        self.setFixedSize(30, 30)  # Круглая кнопка 30x30 (высота toggle)
        self.setToolTip(get_text("tooltip_delete_mod"))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Инициализируем scale для анимации
        self._scale = 1.0
        
        # Анимация увеличения при hover
        self.scale_anim = QPropertyAnimation(self, b"scale")
        self.scale_anim.setDuration(200)
        self.scale_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        # Загружаем и перекрашиваем иконку trash.png в красный
        self.trash_pixmap = None
        trash_icon_path = get_resource_path("trash.png")
        if trash_icon_path.exists():
            pixmap = QPixmap(str(trash_icon_path))
            # Перекрашиваем в красный цвет
            painter = QPainter(pixmap)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(pixmap.rect(), QColor(231, 76, 60, 200))  # Красный цвет #e74c3c
            painter.end()
            
            # Масштабируем до 14x14 (оптимальный размер для кнопки 30x30)
            self.trash_pixmap = pixmap.scaled(14, 14, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    
    @pyqtProperty(float)
    def scale(self):
        return self._scale
    
    @scale.setter
    def scale(self, value):
        self._scale = value
        self.update()
    
    def enterEvent(self, event):
        """При наведении - увеличиваем"""
        super().enterEvent(event)
        self.scale_anim.stop()
        self.scale_anim.setStartValue(self._scale)
        self.scale_anim.setEndValue(1.2)
        self.scale_anim.start()
    
    def leaveEvent(self, event):
        """При уходе - возвращаем размер"""
        super().leaveEvent(event)
        self.scale_anim.stop()
        self.scale_anim.setStartValue(self._scale)
        self.scale_anim.setEndValue(1.0)
        self.scale_anim.start()
    
    def paintEvent(self, event):
        """Рисуем кнопку с иконкой мусорки"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        # Рисуем фон кнопки
        rect = self.rect()
        
        if self.isDown():
            painter.setBrush(QBrush(QColor(26, 26, 26)))
        elif self.underMouse():
            painter.setBrush(QBrush(QColor(35, 35, 35)))
        else:
            painter.setBrush(QBrush(QColor(26, 26, 26)))
        
        painter.setPen(QPen(QColor(42, 42, 42), 2))
        if self.underMouse():
            painter.setPen(QPen(QColor(231, 76, 60), 2))  # Красная обводка при hover
        
        # Рисуем ИДЕАЛЬНО КРУГЛУЮ кнопку (используем drawEllipse)
        painter.drawEllipse(1, 1, self.width() - 2, self.height() - 2)
        
        # Рисуем иконку с масштабированием В ЦЕНТРЕ
        if self.trash_pixmap:
            painter.save()
            # Перемещаемся в центр кнопки
            painter.translate(self.width() / 2, self.height() / 2)
            # Масштабируем
            painter.scale(self._scale, self._scale)
            # Рисуем иконку относительно центра (14/2 = 7)
            painter.drawPixmap(-7, -7, self.trash_pixmap)
            painter.restore()


class AnimatedActionButton(QPushButton):
    """Анимированная кнопка действия с иконкой и текстом"""
    
    def __init__(self, text, icon_name=None, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Инициализируем offset для анимации подпрыгивания
        self._y_offset = 0
        self.icon_pixmap = None
        
        # Загружаем и перекрашиваем иконку
        if icon_name:
            icon_path = get_resource_path(icon_name)
            if icon_path.exists():
                pixmap = QPixmap(str(icon_path))
                # Перекрашиваем в белый цвет
                painter = QPainter(pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(pixmap.rect(), QColor(255, 255, 255, 220))
                painter.end()
                
                # Определяем размер иконки в зависимости от типа
                if icon_name == "alloff.png":  # Крестик - меньше
                    icon_size = 12
                elif icon_name in ["add.png", "link.png"]:  # Плюсик и ссылка - больше
                    icon_size = 16
                else:  # Остальные (allon.png) - стандартный размер
                    icon_size = 14
                
                # Масштабируем до нужного размера (игнорируем пропорции для одинакового размера)
                self.icon_pixmap = pixmap.scaled(icon_size, icon_size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.icon_size = icon_size  # Сохраняем размер для использования в paintEvent
        
        # Анимация подпрыгивания
        self.bounce_anim = QPropertyAnimation(self, b"y_offset")
        self.bounce_anim.setDuration(300)
        self.bounce_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    
    @pyqtProperty(int)
    def y_offset(self):
        return self._y_offset
    
    @y_offset.setter
    def y_offset(self, value):
        self._y_offset = value
        self.update()
    
    def enterEvent(self, event):
        """При наведении - иконка подпрыгивает"""
        super().enterEvent(event)
        self.bounce_anim.stop()
        self.bounce_anim.setStartValue(0)
        self.bounce_anim.setKeyValueAt(0.5, -5)  # Подпрыгивает на 5px вверх
        self.bounce_anim.setEndValue(0)
        self.bounce_anim.start()
    
    def leaveEvent(self, event):
        """При уходе - сброс"""
        super().leaveEvent(event)
        self._y_offset = 0
        self.update()
    
    def mousePressEvent(self, event):
        """При клике"""
        super().mousePressEvent(event)
        self.update()
    
    def mouseReleaseEvent(self, event):
        """При отпускании"""
        super().mouseReleaseEvent(event)
        self.update()
    
    def paintEvent(self, event):
        """Рисуем кнопку без масштабирования"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        # Рисуем фон кнопки
        rect = self.rect()
        
        # Цвет фона - синий (#3498db)
        if self.isDown():
            painter.setBrush(QBrush(QColor(41, 128, 185)))  # Темнее при нажатии
        elif self.underMouse():
            painter.setBrush(QBrush(QColor(93, 173, 226)))  # Светлее при hover
        else:
            painter.setBrush(QBrush(QColor(52, 152, 219)))  # Основной синий
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 22, 22)
        
        # Рисуем иконку и текст по центру
        if self.icon_pixmap:
            # Подготавливаем шрифт для измерения текста
            painter.setPen(QColor(255, 255, 255))
            font = painter.font()
            font.setPixelSize(10)
            font.setBold(True)
            painter.setFont(font)
            
            # Измеряем ширину текста
            text_width = painter.fontMetrics().horizontalAdvance(self.text())
            icon_width = self.icon_size if hasattr(self, 'icon_size') else 14
            spacing = 6  # Отступ между иконкой и текстом
            
            # Общая ширина (иконка + отступ + текст)
            total_width = icon_width + spacing + text_width
            
            # Начальная позиция для центрирования
            start_x = (self.width() - total_width) / 2
            
            # Рисуем иконку с учетом y_offset (подпрыгивание)
            icon_y = (self.height() - icon_width) / 2 + self._y_offset
            painter.drawPixmap(int(start_x), int(icon_y), self.icon_pixmap)
            
            # Рисуем текст с учетом y_offset (подпрыгивает вместе с иконкой)
            text_x = start_x + icon_width + spacing
            text_rect = QRect(int(text_x), int(self._y_offset), int(text_width + 10), self.height())
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text())
        else:
            # Только текст по центру
            painter.setPen(QColor(255, 255, 255))
            font = painter.font()
            font.setPixelSize(10)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())


class FallingHeart(QWidget):
    """Падающее сердечко для анимации доната"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(20, 20)
        
        # Начинаем с полной прозрачности для плавного появления
        self.setWindowOpacity(0.0)
        
        # Загружаем новую иконку сердечка и создаем версию с обводкой
        self.heart_pixmap = None
        self.heart_outline_pixmap = None
        heart_path = get_resource_path("heart.png")
        if heart_path.exists():
            pixmap = QPixmap(str(heart_path))
            if not pixmap.isNull():
                # Масштабируем оригинальную иконку
                original_scaled = pixmap.scaled(18, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                
                # Создаем синюю версию
                blue_pixmap = QPixmap(original_scaled.size())
                blue_pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(blue_pixmap)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                painter.drawPixmap(0, 0, original_scaled)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(blue_pixmap.rect(), QColor(52, 152, 219))  # Синий цвет #3498db
                painter.end()
                
                # Создаем черную обводку
                outline_pixmap = QPixmap(original_scaled.size())
                outline_pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(outline_pixmap)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                painter.drawPixmap(0, 0, original_scaled)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(outline_pixmap.rect(), QColor(0, 0, 0))  # Черная обводка
                painter.end()
                
                self.heart_pixmap = blue_pixmap
                self.heart_outline_pixmap = outline_pixmap
        
        # Если не удалось загрузить, используем текстовое сердечко
        if not self.heart_pixmap:
            self.heart_text = "💙"
        else:
            self.heart_text = None
    
    def paintEvent(self, event):
        """Рисуем сердечко с черной обводкой"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        if self.heart_pixmap and self.heart_outline_pixmap:
            # Центрируем сердечко
            x = (self.width() - self.heart_pixmap.width()) // 2
            y = (self.height() - self.heart_pixmap.height()) // 2
            
            # Сначала рисуем черную обводку в нескольких позициях для эффекта outline
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx != 0 or dy != 0:  # Не рисуем в центре
                        painter.drawPixmap(x + dx, y + dy, self.heart_outline_pixmap)
            
            # Затем рисуем синее сердечко поверх
            painter.drawPixmap(x, y, self.heart_pixmap)
        else:
            # Fallback: рисуем текстовое сердечко с обводкой
            painter.setPen(QPen(QColor(0, 0, 0), 2))  # Черная обводка
            font = painter.font()
            font.setPointSize(16)
            painter.setFont(font)
            
            # Рисуем обводку
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx != 0 or dy != 0:
                        painter.drawText(self.rect().adjusted(dx, dy, dx, dy), Qt.AlignmentFlag.AlignCenter, self.heart_text)
            
            # Рисуем синий текст поверх
            painter.setPen(QColor(52, 152, 219))  # #3498db
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.heart_text)


class AnimatedDonateButton(QPushButton):
    """Кнопка доната с анимацией падающих сердечек при наведении"""
    
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("donateButton")
        self.setFixedHeight(40)
        
        # Список активных сердечек
        self.falling_hearts = []
        
        # Список занятых позиций для избежания наложения
        self.occupied_positions = []
        
        # Список всех когда-либо созданных сердечек для принудительной очистки
        self.all_created_hearts = []
        
        # Таймер для создания новых сердечек
        self.heart_timer = QTimer()
        self.heart_timer.timeout.connect(self.create_falling_heart)
        
        # Загружаем и устанавливаем иконку sup.png (белую)
        sup_icon_path = get_resource_path("sup.png")
        if sup_icon_path.exists():
            pixmap = QPixmap(str(sup_icon_path))
            if not pixmap.isNull():
                # Масштабируем до 20x20 для кнопки
                scaled_pixmap = pixmap.scaled(20, 20, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                
                # Перекрашиваем в белый цвет
                white_pixmap = QPixmap(scaled_pixmap.size())
                white_pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(white_pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                painter.drawPixmap(0, 0, scaled_pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(white_pixmap.rect(), QColor(255, 255, 255))
                painter.end()
                
                icon = QIcon(white_pixmap)
                self.setIcon(icon)
                self.setIconSize(QSize(20, 20))
    
    def enterEvent(self, event):
        """При наведении - запускаем анимацию падающих сердечек"""
        super().enterEvent(event)
        # Запускаем создание сердечек каждые 300ms (реже чем было)
        self.heart_timer.start(300)
    
    def leaveEvent(self, event):
        """При уходе мыши - останавливаем создание новых сердечек и плавно убираем существующие"""
        super().leaveEvent(event)
        self.heart_timer.stop()
        # Плавно убираем все существующие сердечки
        self.fade_out_all_hearts()
    
    def create_falling_heart(self):
        """Создает новое падающее сердечко без наложения"""
        if not self.parent():
            return
        
        # Ограничиваем количество сердечек для предотвращения утечек памяти
        if len(self.falling_hearts) >= 6:
            print("⚠️ Maximum hearts limit reached, skipping creation")
            return
        
        # Создаем сердечко
        heart = FallingHeart(self.parent())
        
        # Позиционируем над кнопкой, избегая наложения
        button_rect = self.geometry()
        max_attempts = 10
        start_x = None
        start_y = button_rect.y() - 10
        
        # Пытаемся найти свободную позицию
        for attempt in range(max_attempts):
            test_x = button_rect.x() + random.randint(0, max(0, button_rect.width() - 25))
            
            # Проверяем что позиция не занята (минимальное расстояние 25px)
            position_free = True
            for occupied_x in self.occupied_positions:
                if abs(test_x - occupied_x) < 25:
                    position_free = False
                    break
            
            if position_free:
                start_x = test_x
                break
        
        # Если не нашли свободную позицию, используем случайную
        if start_x is None:
            start_x = button_rect.x() + random.randint(0, max(0, button_rect.width() - 25))
        
        # Добавляем позицию в занятые
        self.occupied_positions.append(start_x)
        
        heart.move(start_x, start_y)
        heart.show()
        
        # Анимация плавного появления
        fade_in_anim = QPropertyAnimation(heart, b"windowOpacity")
        fade_in_anim.setDuration(300)  # Плавное появление за 0.3 секунды
        fade_in_anim.setStartValue(0.0)
        fade_in_anim.setEndValue(1.0)
        fade_in_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        
        # Анимация падения
        fall_anim = QPropertyAnimation(heart, b"pos")
        fall_anim.setDuration(2000)  # 2 секунды падения
        fall_anim.setStartValue(QPoint(start_x, start_y))
        fall_anim.setEndValue(QPoint(start_x + random.randint(-30, 30), start_y + 200))  # Падает вниз с небольшим отклонением
        fall_anim.setEasingCurve(QEasingCurve.Type.InQuad)
        
        # Анимация плавного исчезновения (начинается через 1.5 сек)
        fade_out_anim = QPropertyAnimation(heart, b"windowOpacity")
        fade_out_anim.setDuration(500)  # Плавное исчезновение за 0.5 секунды
        fade_out_anim.setStartValue(1.0)
        fade_out_anim.setEndValue(0.0)
        fade_out_anim.setEasingCurve(QEasingCurve.Type.InQuad)
        
        # Группируем анимации падения и исчезновения (параллельно)
        fall_fade_group = QParallelAnimationGroup()
        fall_fade_group.addAnimation(fall_anim)
        fall_fade_group.addAnimation(fade_out_anim)
        
        # Последовательная группа: сначала появление, потом падение+исчезновение
        anim_sequence = QSequentialAnimationGroup()
        anim_sequence.addAnimation(fade_in_anim)
        anim_sequence.addAnimation(fall_fade_group)
        
        # Безопасное удаление сердечка после анимации
        anim_sequence.finished.connect(lambda: self.cleanup_heart(heart, start_x))
        
        # Сохраняем ссылку на анимацию в сердечке для возможности остановки
        heart.animation_sequence = anim_sequence
        
        # Добавляем в списки и запускаем
        self.falling_hearts.append(heart)
        self.all_created_hearts.append(heart)  # Глобальный список для принудительной очистки
        anim_sequence.start()
    
    def __del__(self):
        """Деструктор - очищаем все сердечки при удалении кнопки"""
        try:
            self.heart_timer.stop()
            self.force_cleanup_all_hearts()
            self.falling_hearts.clear()
            self.occupied_positions.clear()
        except Exception as e:
            print(f"❌ Error in AnimatedDonateButton destructor: {e}")
    
    def fade_out_all_hearts(self):
        """НЕМЕДЛЕННО убирает все существующие сердечки при уходе мыши"""
        print(f"🔄 IMMEDIATELY removing {len(self.falling_hearts)} hearts...")
        
        # Создаем копию списка для безопасной итерации
        hearts_to_remove = self.falling_hearts[:]
        
        # НЕМЕДЛЕННО очищаем списки
        self.falling_hearts.clear()
        self.occupied_positions.clear()
        
        for heart in hearts_to_remove:
            try:
                # Останавливаем ВСЕ анимации сердечка
                if hasattr(heart, 'animation_sequence') and heart.animation_sequence:
                    heart.animation_sequence.stop()
                    heart.animation_sequence.deleteLater()
                    heart.animation_sequence = None
                    print(f"🛑 Stopped and deleted animation for heart")
                
                # НЕМЕДЛЕННО скрываем и удаляем сердечко БЕЗ анимации
                heart.hide()
                heart.deleteLater()
                print(f"💀 Heart immediately deleted")
                
            except Exception as e:
                print(f"❌ Error removing heart: {e}")
        
        print("✅ All hearts IMMEDIATELY removed")
        
        # ДОПОЛНИТЕЛЬНАЯ ЗАЩИТА: принудительно удаляем ВСЕ созданные сердечки
        self.force_cleanup_all_hearts()
    
    def force_cleanup_all_hearts(self):
        """ПРИНУДИТЕЛЬНО удаляет ВСЕ когда-либо созданные сердечки"""
        print(f"🚨 FORCE cleanup of {len(self.all_created_hearts)} total hearts...")
        
        for heart in self.all_created_hearts[:]:
            try:
                if heart and not heart.isHidden():
                    heart.hide()
                heart.deleteLater()
            except Exception as e:
                print(f"❌ Error in force cleanup: {e}")
        
        self.all_created_hearts.clear()
        print("🚨 FORCE cleanup completed")
    
    def safe_delete_heart(self, heart):
        """Безопасно удаляет сердечко"""
        try:
            if heart and not heart.isHidden():
                heart.hide()
            heart.deleteLater()
        except Exception as e:
            print(f"❌ Error in safe_delete_heart: {e}")
    
    def cleanup_heart(self, heart, position_x):
        """Безопасно удаляет сердечко и освобождает ресурсы"""
        try:
            # Удаляем из списка активных сердечек
            if heart in self.falling_hearts:
                self.falling_hearts.remove(heart)
            
            # Удаляем из глобального списка
            if heart in self.all_created_hearts:
                self.all_created_hearts.remove(heart)
            
            # Освобождаем позицию
            if position_x in self.occupied_positions:
                self.occupied_positions.remove(position_x)
            
            # Останавливаем анимацию если она еще идет
            if hasattr(heart, 'animation_sequence'):
                heart.animation_sequence.stop()
                heart.animation_sequence = None
            
            # Безопасно удаляем виджет
            if heart and not heart.isHidden():
                heart.hide()
            heart.deleteLater()
            
        except Exception as e:
            print(f"❌ Error in cleanup_heart: {e}")


class AnimatedCard(QFrame):
    """Карточка аддона с hover анимацией"""
    toggled = pyqtSignal(dict)
    
    def __init__(self, addon_data, index, parent=None):
        super().__init__(parent)
        self.addon = addon_data
        self.index = index
        self.parent_window = parent
        self.setup_ui()
        self.setup_hover_animation()
    
    def setup_ui(self):
        self.setObjectName("modCard")
        self.setMinimumHeight(100)  # Вернули минимальную высоту
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)  # Вернули отступы
        layout.setSpacing(15)  # Вернули spacing
        
        # Иконка аддона
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(80, 80)  # Вернули размер 80x80
        self.icon_label.setScaledContents(True)
        self.icon_label.setObjectName("addonIcon")
        
        # Устанавливаем placeholder или загружаем иконку
        if self.addon.get('preview_url'):
            self.load_icon(self.addon['preview_url'])
        else:
            # Placeholder - минималистичная иконка
            self.icon_label.setText("◯")
            self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.icon_label.setStyleSheet("font-size: 40px; color: #3498db; border-radius: 10px;")
        
        layout.addWidget(self.icon_label)
        
        # Индикатор статуса (минималистичный)
        indicator = QLabel("●")
        indicator.setObjectName("statusIndicator")
        # Убираем фон у индикатора
        indicator.setAutoFillBackground(False)
        indicator.setStyleSheet(f"color: {'#3498db' if self.addon.get('enabled') else '#95a5a6'}; font-size: 16px; background: transparent; border: none;")
        
        # Текстовая часть
        text_layout = QVBoxLayout()
        text_layout.setSpacing(0)
        text_layout.setContentsMargins(0, 0, 0, 0)
        
        # Заголовок с индикатором
        title_layout = QHBoxLayout()
        title_layout.setSpacing(8)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.addWidget(indicator)
        
        title = QLabel(self.addon['name'])
        title.setObjectName("cardTitle")
        # Убираем фон у заголовка
        title.setAutoFillBackground(False)
        title.setStyleSheet("background: transparent; border: none;")
        title_layout.addWidget(title, 1)
        
        text_layout.addLayout(title_layout)
        
        # Определяем цвет текста в зависимости от темы
        # Ищем MainWindow через цепочку родителей
        text_color = "#d0d0d0"  # Светло-серый для темной темы
        
        # Описание если есть
        description = self.addon.get('description', '')
        if description and description != 'Загрузка...':
            # Добавляем небольшой spacing перед описанием
            text_layout.addSpacing(2)
            
            desc_label = QLabel()
            desc_label.setWordWrap(True)
            desc_label.setMaximumHeight(45)
            
            # ВАЖНО: убираем фон у label и добавляем отрицательный margin сверху
            desc_label.setAutoFillBackground(False)
            desc_label.setStyleSheet("background: transparent; border: none; padding: 0px;")
            desc_label.setContentsMargins(0, 0, 0, 0)
            
            # Экранируем HTML в описании
            safe_description = escape(description)
            
            # Используем HTML для гарантированного цвета
            desc_label.setTextFormat(Qt.TextFormat.RichText)
            html_text = f'<div style="color: {text_color}; font-size: 10px; font-weight: 400; line-height: 1.0; margin: 0; padding: 0;">{safe_description}</div>'
            desc_label.setText(html_text)
            
            text_layout.addWidget(desc_label)
        else:
            id_label = QLabel()
            
            # ВАЖНО: убираем фон
            id_label.setAutoFillBackground(False)
            id_label.setStyleSheet("background: transparent; border: none;")
            
            # Используем HTML
            id_label.setTextFormat(Qt.TextFormat.RichText)
            html_text = f'<span style="color: {text_color}; font-size: 12px;">ID: {self.addon["id"]}</span>'
            id_label.setText(html_text)
            
            text_layout.addWidget(id_label)
        
        layout.addLayout(text_layout, 1)
        layout.setAlignment(text_layout, Qt.AlignmentFlag.AlignTop)
        
        # Анимированный переключатель
        self.toggle_switch = AnimatedToggle()
        self.toggle_switch.setChecked(self.addon.get('enabled', False))
        self.toggle_switch.stateChanged.connect(lambda state: self.on_toggle_changed())
        layout.addWidget(self.toggle_switch)
    
    def on_toggle_changed(self):
        """Обработчик изменения состояния тумблера"""
        # Обновляем данные аддона
        self.addon['enabled'] = self.toggle_switch.isChecked()
        # Эмитим сигнал с обновленными данными
        self.toggled.emit(self.addon)
    
    def update_state(self):
        """Обновляет состояние карточки из данных аддона"""
        # Блокируем сигналы чтобы не вызвать toggle_addon
        self.toggle_switch.blockSignals(True)
        self.toggle_switch.setChecked(self.addon.get('enabled', False))
        
        # Вручную обновляем позицию ручки (так как сигналы заблокированы)
        if self.addon.get('enabled', False):
            self.toggle_switch._handle_position = 30
        else:
            self.toggle_switch._handle_position = 0
        self.toggle_switch.update()
        
        self.toggle_switch.blockSignals(False)
        
        # Обновляем индикатор статуса
        for child in self.findChildren(QLabel):
            if child.objectName() == "statusIndicator":
                color = '#3498db' if self.addon.get('enabled') else '#95a5a6'
                child.setStyleSheet(f"color: {color}; font-size: 16px; background: transparent; border: none;")
                break
    
    def load_icon(self, url):
        """Загружает иконку из URL"""
        try:
            from urllib.request import urlopen
            data = urlopen(url, timeout=3).read()
            pixmap = QPixmap()
            pixmap.loadFromData(data)
            
            if not pixmap.isNull():
                # Масштабируем и применяем скругление
                scaled = pixmap.scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                self.icon_label.setPixmap(scaled)
                self.icon_label.setStyleSheet("border-radius: 10px;")
        except Exception as e:
            # Если не удалось загрузить, оставляем placeholder
            print(f"Ошибка загрузки иконки: {e}")
    
    def setup_hover_animation(self):
        """Настройка hover анимации - легкое увеличение"""
        # Сохраняем оригинальную геометрию
        self.original_geometry = None
        
        # Анимация геометрии для scale эффекта
        self.scale_anim = QPropertyAnimation(self, b"geometry")
        self.scale_anim.setDuration(150)
        self.scale_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    
    def enterEvent(self, event):
        """При наведении - легкое увеличение"""
        super().enterEvent(event)
        
        # Проверяем флаг отключения анимаций
        if hasattr(self.parent_window, 'animations_disabled') and self.parent_window.animations_disabled:
            return
        
        if self.original_geometry is None:
            self.original_geometry = self.geometry()
        
        # Увеличиваем на 3px со всех сторон для более заметного эффекта
        target = self.original_geometry.adjusted(-3, -3, 3, 3)
        
        self.scale_anim.stop()
        self.scale_anim.setStartValue(self.geometry())
        self.scale_anim.setEndValue(target)
        self.scale_anim.start()
    
    def leaveEvent(self, event):
        """При уходе мыши - возвращаем к оригиналу"""
        super().leaveEvent(event)
        
        # Проверяем флаг отключения анимаций
        if hasattr(self.parent_window, 'animations_disabled') and self.parent_window.animations_disabled:
            return
        
        if self.original_geometry is None:
            return
        
        self.scale_anim.stop()
        self.scale_anim.setStartValue(self.geometry())
        self.scale_anim.setEndValue(self.original_geometry)
        self.scale_anim.start()
    
    def force_reset_state(self):
        """Принудительно сбрасывает состояние карточки"""
        try:
            # Останавливаем анимацию
            if hasattr(self, 'scale_anim'):
                self.scale_anim.stop()
            
            # Принудительно возвращаем к оригинальной геометрии
            if self.original_geometry is not None:
                self.setGeometry(self.original_geometry)
            
            # Сбрасываем original_geometry
            self.original_geometry = None
            
            # Убираем графические эффекты
            if self.graphicsEffect():
                self.setGraphicsEffect(None)
            
            # Принудительно вызываем leaveEvent
            fake_leave_event = QEvent(QEvent.Type.Leave)
            self.leaveEvent(fake_leave_event)
            
            # Обновляем виджет
            self.update()
            
        except Exception as e:
            print(f"❌ Error resetting card state: {e}")


class SimpleCopyTooltip(QWidget):
    """Простое компактное уведомление 'Скопировано' над текстом"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        # Компактный layout
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        
        # Простой текст
        label = QLabel(get_text("copied_status"))
        label.setStyleSheet("""
            QLabel {
                background: rgba(70, 70, 70, 230);
                color: white;
                padding: 5px 15px;
                border-radius: 5px;
                font-size: 12px;
                font-weight: 500;
            }
        """)
        layout.addWidget(label)
        
        self.adjustSize()
        
        # Анимация появления
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(0)
        
        self.fade_in = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_in.setDuration(200)
        self.fade_in.setStartValue(0)
        self.fade_in.setEndValue(1)
        self.fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        self.fade_out = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_out.setDuration(200)
        self.fade_out.setStartValue(1)
        self.fade_out.setEndValue(0)
        self.fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self.fade_out.finished.connect(self.close)
    
    def show_at_cursor(self):
        """Показывает tooltip в позиции курсора"""
        cursor_pos = QCursor.pos()
        # Показываем чуть выше курсора
        self.move(cursor_pos.x() - self.width() // 2, cursor_pos.y() - self.height() - 10)
        self.show()
        self.fade_in.start()
        
        # Автоматически скрываем через 1 секунду
        QTimer.singleShot(1000, self.fade_out.start)


class ToastNotification(QWidget):
    """Всплывающее уведомление (toast)"""
    
    def __init__(self, message, parent=None, duration=5000, on_close_callback=None):
        super().__init__(parent)
        self.parent_widget = parent
        self.on_close_callback = on_close_callback
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Убираем WA_ShowWithoutActivating чтобы получать клики
        # self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        self.duration = duration
        self.blur_effect = None
        self.setup_ui(message)
        
        # Позиционируем в правом нижнем углу родителя
        if parent:
            self.position_toast(parent)
            # Устанавливаем фильтр событий на родителя для перехвата кликов
            parent.installEventFilter(self)
    
    def setup_ui(self, message):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Контейнер с темным фоном и синей окантовкой
        container = QFrame()
        container.setObjectName("toastContainer")
        container.setStyleSheet("""
            #toastContainer {
                background: #1a1a1a;
                border: 2px solid #3498db;
                border-radius: 12px;
                padding: 15px 20px;
            }
        """)
        text_color = "#d0d0d0"
        
        container_layout = QHBoxLayout(container)
        container_layout.setSpacing(12)
        
        # Иконка
        icon = QLabel("ℹ️")
        icon.setStyleSheet("font-size: 24px; background: transparent; border: none;")
        container_layout.addWidget(icon)
        
        # Текст сообщения
        text = QLabel(message)
        text.setWordWrap(True)
        text.setStyleSheet(f"""
            color: {text_color};
            font-size: 13px;
            font-weight: 500;
            background: transparent;
            border: none;
        """)
        text.setMaximumWidth(500)
        container_layout.addWidget(text, 1)
        
        layout.addWidget(container)
        
        # Анимация появления
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        
        self.fade_in = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_in.setDuration(300)
        self.fade_in.setStartValue(0)
        self.fade_in.setEndValue(1)
        self.fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        self.fade_out = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_out.setDuration(300)
        self.fade_out.setStartValue(1)
        self.fade_out.setEndValue(0)
        self.fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self.fade_out.finished.connect(self.close)
    
    def position_toast(self, parent):
        """Позиционирует toast в правом нижнем углу"""
        parent_rect = parent.geometry()
        self.adjustSize()
        
        x = parent_rect.x() + parent_rect.width() - self.width() - 20
        y = parent_rect.y() + parent_rect.height() - self.height() - 20
        
        self.move(x, y)
    
    def show_toast(self):
        """Показывает toast с анимацией, blur эффектом и звуком"""
        # Блокируем интерфейс родителя и меняем курсор
        if self.parent_widget:
            self.parent_widget.setEnabled(False)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            
            # Применяем blur к родителю (если еще не применен)
            if not self.parent_widget.graphicsEffect():
                self.blur_effect = QGraphicsBlurEffect()
                self.blur_effect.setBlurRadius(30)
                self.blur_effect.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
                self.parent_widget.setGraphicsEffect(self.blur_effect)
            else:
                # Используем существующий blur эффект
                self.blur_effect = self.parent_widget.graphicsEffect()
        
        # Воспроизводим звук Solo.mp3
        sound_path = Path(__file__).parent / "Solo.mp3"
        if sound_path.exists():
            try:
                self.media_player = QMediaPlayer()
                self.audio_output = QAudioOutput()
                self.audio_output.setVolume(0.5)
                self.media_player.setAudioOutput(self.audio_output)
                self.media_player.setSource(QUrl.fromLocalFile(str(sound_path)))
                self.media_player.play()
            except Exception as e:
                print(f"Ошибка воспроизведения звука: {e}")
        
        self.show()
        self.fade_in.start()
        
        # Автоматически скрываем через duration
        QTimer.singleShot(self.duration, self.hide_toast)
    
    def hide_toast(self):
        """Скрывает toast с анимацией и убирает blur"""
        self.fade_out.start()
        
        # Убираем фильтр событий
        if self.parent_widget:
            self.parent_widget.removeEventFilter(self)
            
            # Убираем blur эффект, разблокируем интерфейс и восстанавливаем курсор
            self.parent_widget.setGraphicsEffect(None)
            self.parent_widget.setEnabled(True)
            QApplication.restoreOverrideCursor()
        
        # Вызываем callback после закрытия
        if self.on_close_callback:
            # Вызываем callback после завершения анимации закрытия
            QTimer.singleShot(300, self.on_close_callback)
    
    def eventFilter(self, obj, event):
        """Перехватываем клики на родительском окне"""
        if event.type() == QEvent.Type.MouseButtonPress:
            # Закрываем toast при любом клике
            self.close_instantly()
            return True  # Блокируем событие
        return super().eventFilter(obj, event)
    
    def mousePressEvent(self, event):
        """Закрываем toast мгновенно при клике на само уведомление"""
        self.close_instantly()
        super().mousePressEvent(event)
    
    def close_instantly(self):
        """Мгновенное закрытие toast"""
        # Останавливаем все анимации
        self.fade_in.stop()
        self.fade_out.stop()
        
        # Убираем фильтр событий
        if self.parent_widget:
            self.parent_widget.removeEventFilter(self)
            
            # Убираем blur эффект, разблокируем интерфейс и восстанавливаем курсор
            self.parent_widget.setGraphicsEffect(None)
            self.parent_widget.setEnabled(True)
            QApplication.restoreOverrideCursor()
        
        # Вызываем callback сразу
        if self.on_close_callback:
            self.on_close_callback()
        
        # Закрываем мгновенно
        self.close()


class CustomConfirmDialog(QDialog):
    """Кастомный диалог подтверждения с блюром и анимацией"""
    
    def __init__(self, parent, title, message, use_existing_blur=False):
        super().__init__(parent)
        self.result_value = False
        self.parent_widget = parent
        self.use_existing_blur = use_existing_blur
        
        # Настройка окна
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        
        # Применяем блюр к родительскому окну (если не используем существующий)
        if not use_existing_blur:
            self.blur_effect = QGraphicsBlurEffect()
            self.blur_effect.setBlurRadius(0)
            self.parent_widget.setGraphicsEffect(self.blur_effect)
            
            # Анимация блюра
            self.blur_anim = QPropertyAnimation(self.blur_effect, b"blurRadius")
            self.blur_anim.setDuration(300)
            self.blur_anim.setStartValue(0)
            self.blur_anim.setEndValue(15)
            self.blur_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        else:
            # Используем существующий блюр
            self.blur_effect = parent.graphicsEffect()
            self.blur_anim = None
        
        # Создаем UI
        self.setup_ui(title, message)
        
        # Анимация появления диалога
        self.setWindowOpacity(0)
        self.opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_anim.setDuration(300)
        self.opacity_anim.setStartValue(0)
        self.opacity_anim.setEndValue(1)
        self.opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
    def setup_ui(self, title, message):
        # Фиксируем размер диалога - ЕДИНЫЙ СТАНДАРТ
        self.setFixedSize(650, 480)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Контейнер без фона (прозрачный)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(25)  # ЕДИНЫЙ СТАНДАРТ отступов
        container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Иконка вопроса - ЕДИНЫЙ СТАНДАРТ 120x120
        icon_label = QLabel()
        icon_path = get_resource_path("ques.png")
        if icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                # ЕДИНЫЙ СТАНДАРТ: 120x120
                scaled_pixmap = pixmap.scaled(120, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                
                # Создаем синюю версию иконки (#3498db)
                blue_pixmap = QPixmap(scaled_pixmap.size())
                blue_pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(blue_pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                painter.drawPixmap(0, 0, scaled_pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(blue_pixmap.rect(), QColor(52, 152, 219))  # #3498db
                painter.end()
                
                icon_label.setPixmap(blue_pixmap)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(icon_label)
        
        # Заголовок - ЕДИНЫЙ СТАНДАРТ
        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 20px; font-weight: 600; color: white;")
        container_layout.addWidget(title_label)
        
        # Сообщение - ЕДИНЫЙ СТАНДАРТ
        message_label = QLabel(message)
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setWordWrap(True)
        message_label.setStyleSheet("font-size: 14px; color: white;")
        container_layout.addWidget(message_label)
        
        # Отступ перед кнопками
        container_layout.addSpacing(20)
        
        # Кнопки
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(20)
        buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Кнопка "Да"
        yes_btn = AnimatedActionButton(get_text("btn_yes"), "#3498db")
        yes_btn.setFixedSize(140, 50)
        yes_btn.clicked.connect(self.accept_dialog)
        buttons_layout.addWidget(yes_btn)
        
        # Кнопка "Нет"
        no_btn = AnimatedActionButton(get_text("btn_no"), "#3498db")
        no_btn.setFixedSize(140, 50)
        no_btn.clicked.connect(self.reject_dialog)
        buttons_layout.addWidget(no_btn)
        
        container_layout.addLayout(buttons_layout)
        
        layout.addWidget(container)
        
    def accept_dialog(self):
        self.result_value = True
        self.close_with_animation()
        
    def reject_dialog(self):
        self.result_value = False
        self.close_with_animation()
        
    def close_with_animation(self):
        # Анимация исчезновения
        self.opacity_anim.setDirection(QPropertyAnimation.Direction.Backward)
        self.opacity_anim.start()
        
        # Анимация убирания блюра (только если мы его создали)
        if not self.use_existing_blur and self.blur_anim:
            self.blur_anim.setDirection(QPropertyAnimation.Direction.Backward)
            self.blur_anim.start()
        
        # Закрываем после анимации
        QTimer.singleShot(300, self.finish_close)
        
    def finish_close(self):
        # Убираем блюр только если мы его создали
        if not self.use_existing_blur:
            self.parent_widget.setGraphicsEffect(None)
        self.accept() if self.result_value else self.reject()
    
    def close_keeping_blur(self):
        """Закрывает диалог без убирания блюра"""
        self.opacity_anim.setDirection(QPropertyAnimation.Direction.Backward)
        self.opacity_anim.start()
        QTimer.singleShot(300, lambda: self.accept() if self.result_value else self.reject())
        
    def showEvent(self, event):
        super().showEvent(event)
        # Центрируем диалог
        if self.parent_widget:
            parent_rect = self.parent_widget.geometry()
            self.move(
                parent_rect.x() + (parent_rect.width() - self.width()) // 2,
                parent_rect.y() + (parent_rect.height() - self.height()) // 2
            )
        # Запускаем анимации (только если создали блюр)
        if not self.use_existing_blur and self.blur_anim:
            self.blur_anim.start()
        self.opacity_anim.start()
        
    @staticmethod
    def question(parent, title, message, use_existing_blur=False):
        """Статический метод для показа диалога (аналог QMessageBox.question)"""
        dialog = CustomConfirmDialog(parent, title, message, use_existing_blur=use_existing_blur)
        result = dialog.exec()
        return result == QDialog.DialogCode.Accepted


class TelegramCommunityDialog(QDialog):
    """Диалог приглашения в Telegram сообщество в стиле CustomConfirmDialog"""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.result_value = False
        self.parent_widget = parent
        
        # Настройка окна
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        
        # Применяем блюр к родительскому окну
        self.blur_effect = QGraphicsBlurEffect()
        self.blur_effect.setBlurRadius(0)
        self.parent_widget.setGraphicsEffect(self.blur_effect)
        
        # Анимация блюра
        self.blur_anim = QPropertyAnimation(self.blur_effect, b"blurRadius")
        self.blur_anim.setDuration(300)
        self.blur_anim.setStartValue(0)
        self.blur_anim.setEndValue(15)
        self.blur_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        # Создаем UI
        self.setup_ui()
        
        # Анимация появления диалога
        self.setWindowOpacity(0)
        self.opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_anim.setDuration(300)
        self.opacity_anim.setStartValue(0)
        self.opacity_anim.setEndValue(1)
        self.opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        # Показываем с анимацией
        self.show()
        self.opacity_anim.start()
        if self.blur_anim:
            self.blur_anim.start()
    
    def setup_ui(self):
        # Фиксируем размер диалога - ЕДИНЫЙ СТАНДАРТ
        self.setFixedSize(650, 520)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Контейнер без фона (прозрачный)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(20)
        container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Иконка Telegram (tg.png залитая синим цветом) - ЕДИНЫЙ СТАНДАРТ 120x120
        icon_label = QLabel()
        icon_path = get_resource_path("tg.png")
        if icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                # ЕДИНЫЙ СТАНДАРТ: 120x120
                scaled_pixmap = pixmap.scaled(120, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                
                # Перекрашиваем в синий цвет #3498db
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
        
        # Заголовок - ЕДИНЫЙ СТАНДАРТ
        title_label = QLabel(get_text("telegram_community_title"))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 20px; font-weight: 600; color: white;")
        container_layout.addWidget(title_label)
        
        # Сообщение - ЕДИНЫЙ СТАНДАРТ
        message_label = QLabel(get_text("telegram_community_message"))
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setWordWrap(True)
        message_label.setMaximumWidth(580)
        message_label.setStyleSheet("font-size: 13px; color: white; line-height: 1.5;")
        message_label.setTextFormat(Qt.TextFormat.RichText)
        container_layout.addWidget(message_label, 0, Qt.AlignmentFlag.AlignCenter)
        
        container_layout.addSpacing(10)
        
        # Кнопки - ЕДИНЫЙ СТАНДАРТ
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(20)
        buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Кнопка "Присоединиться"
        self.join_btn = AnimatedActionButton(get_text("telegram_btn_join"), "#3498db")
        self.join_btn.setFixedSize(160, 50)
        self.join_btn.clicked.connect(self.accept_join)
        buttons_layout.addWidget(self.join_btn)
        
        # Кнопка "Позже"
        self.later_btn = AnimatedActionButton(get_text("telegram_btn_later"), "#7f8c8d")
        self.later_btn.setFixedSize(120, 50)
        self.later_btn.clicked.connect(self.reject_join)
        buttons_layout.addWidget(self.later_btn)
        
        container_layout.addLayout(buttons_layout)
        layout.addWidget(container)
    
    def accept_join(self):
        """Пользователь согласился присоединиться"""
        self.result_value = True
        self.close()
    
    def reject_join(self):
        """Пользователь отказался присоединиться"""
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
    
    def showEvent(self, event):
        """Центрируем диалог при показе"""
        super().showEvent(event)
        if self.parent_widget:
            parent_rect = self.parent_widget.geometry()
            self.move(
                parent_rect.x() + (parent_rect.width() - self.width()) // 2,
                parent_rect.y() + (parent_rect.height() - self.height()) // 2
            )


class CustomDeleteDialog(QDialog):
    """Кастомный диалог удаления с красной иконкой мусорки"""
    
    def __init__(self, parent, title, message, use_existing_blur=False):
        super().__init__(parent)
        self.result_value = False
        self.parent_widget = parent
        self.use_existing_blur = use_existing_blur
        
        # Настройка окна
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        
        # Применяем блюр к родительскому окну (если не используем существующий)
        if not use_existing_blur:
            self.blur_effect = QGraphicsBlurEffect()
            self.blur_effect.setBlurRadius(0)
            self.parent_widget.setGraphicsEffect(self.blur_effect)
            
            # Анимация блюра
            self.blur_anim = QPropertyAnimation(self.blur_effect, b"blurRadius")
            self.blur_anim.setDuration(300)
            self.blur_anim.setStartValue(0)
            self.blur_anim.setEndValue(15)
            self.blur_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        else:
            # Используем существующий блюр
            self.blur_effect = parent.graphicsEffect()
            self.blur_anim = None
        
        # Создаем UI
        self.setup_ui(title, message)
        
        # Анимация появления диалога
        self.setWindowOpacity(0)
        self.opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_anim.setDuration(300)
        self.opacity_anim.setStartValue(0)
        self.opacity_anim.setEndValue(1)
        self.opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
    def setup_ui(self, title, message):
        # Фиксируем размер диалога - ЕДИНЫЙ СТАНДАРТ
        self.setFixedSize(650, 480)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Контейнер без фона (прозрачный)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(25)  # ЕДИНЫЙ СТАНДАРТ отступов
        container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Иконка мусорки - ЕДИНЫЙ СТАНДАРТ 120x120 (синяя)
        icon_label = QLabel()
        icon_path = get_resource_path("trash.png")
        if icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                # ЕДИНЫЙ СТАНДАРТ: 120x120
                scaled_pixmap = pixmap.scaled(120, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                
                # Создаем синюю версию иконки (#3498db)
                blue_pixmap = QPixmap(scaled_pixmap.size())
                blue_pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(blue_pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                painter.drawPixmap(0, 0, scaled_pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(blue_pixmap.rect(), QColor(52, 152, 219))  # #3498db - синий
                painter.end()
                
                icon_label.setPixmap(blue_pixmap)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(icon_label)
        
        # Заголовок - ЕДИНЫЙ СТАНДАРТ
        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 20px; font-weight: 600; color: white;")
        container_layout.addWidget(title_label)
        
        # Сообщение - ЕДИНЫЙ СТАНДАРТ
        message_label = QLabel(message)
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setWordWrap(True)
        message_label.setStyleSheet("font-size: 14px; color: white;")
        container_layout.addWidget(message_label)
        
        # Отступ перед кнопками
        container_layout.addSpacing(20)
        
        # Кнопки
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(20)
        buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Кнопка "Удалить" (синяя, без иконки)
        delete_btn = AnimatedActionButton(get_text("btn_delete"), None)
        delete_btn.setFixedSize(140, 50)
        delete_btn.clicked.connect(self.accept_dialog)
        # Переопределяем стиль для синей кнопки
        delete_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3498db, stop:1 #2980b9);
                border: none;
                border-radius: 25px;
                color: white;
                padding: 15px 40px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #5dade2, stop:1 #3498db);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #2980b9, stop:1 #21618c);
            }
        """)
        buttons_layout.addWidget(delete_btn)
        
        # Кнопка "Отмена" (серая)
        cancel_btn = AnimatedActionButton(get_text("btn_cancel"), None)
        cancel_btn.setFixedSize(140, 50)
        cancel_btn.clicked.connect(self.reject_dialog)
        # Переопределяем стиль для серой кнопки
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #95a5a6, stop:1 #7f8c8d);
                border: none;
                border-radius: 25px;
                color: white;
                padding: 15px 40px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #a6b4b5, stop:1 #95a5a6);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #7f8c8d, stop:1 #6c7a7b);
            }
        """)
        buttons_layout.addWidget(cancel_btn)
        
        container_layout.addLayout(buttons_layout)
        
        layout.addWidget(container)
        
    def accept_dialog(self):
        self.result_value = True
        # При нажатии "Удалить" сохраняем blur для следующего диалога
        self.close_keeping_blur()
        
    def reject_dialog(self):
        self.result_value = False
        self.close_with_animation()
        
    def close_with_animation(self):
        # Анимация исчезновения
        self.opacity_anim.setDirection(QPropertyAnimation.Direction.Backward)
        self.opacity_anim.start()
        
        # Анимация убирания блюра (только если мы его создали)
        if not self.use_existing_blur and self.blur_anim:
            self.blur_anim.setDirection(QPropertyAnimation.Direction.Backward)
            self.blur_anim.start()
        
        # Закрываем после анимации
        QTimer.singleShot(300, self.finish_close)
    
    def close_keeping_blur(self):
        """Закрывает диалог без убирания блюра (для перехода к следующему диалогу)"""
        # Анимация исчезновения
        self.opacity_anim.setDirection(QPropertyAnimation.Direction.Backward)
        self.opacity_anim.start()
        # НЕ убираем блюр - он останется для следующего диалога
        QTimer.singleShot(300, lambda: self.accept() if self.result_value else self.reject())
        
    def finish_close(self):
        # Убираем блюр только если мы его создали
        if not self.use_existing_blur:
            self.parent_widget.setGraphicsEffect(None)
        self.accept() if self.result_value else self.reject()
    
    def showEvent(self, event):
        super().showEvent(event)
        # Центрируем диалог
        if self.parent_widget:
            parent_rect = self.parent_widget.geometry()
            self.move(
                parent_rect.x() + (parent_rect.width() - self.width()) // 2,
                parent_rect.y() + (parent_rect.height() - self.height()) // 2
            )
        # Запускаем анимации (только если создали блюр)
        if not self.use_existing_blur and self.blur_anim:
            self.blur_anim.start()
        self.opacity_anim.start()
        
    @staticmethod
    def confirm_delete(parent, title, message):
        """Статический метод для показа диалога удаления"""
        dialog = CustomDeleteDialog(parent, title, message)
        result = dialog.exec()
        return result == QDialog.DialogCode.Accepted
    
    @staticmethod
    def question(parent, title, message):
        """Статический метод для показа диалога удаления (алиас для совместимости)"""
        return CustomDeleteDialog.confirm_delete(parent, title, message)


class CustomProgressDialog(QDialog):
    """Кастомный прогресс-диалог с блюром"""
    
    def __init__(self, parent, title, cancel_text, minimum, maximum, use_existing_blur=False):
        super().__init__(parent)
        self.parent_widget = parent
        self.was_canceled = False
        self.current_value = 0
        self.maximum_value = maximum
        self.use_existing_blur = use_existing_blur
        self._keep_blur_on_close = False  # Флаг для сохранения blur при закрытии
        
        # Настройка окна
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        
        # Применяем блюр к родительскому окну (если не используем существующий)
        if not use_existing_blur:
            self.blur_effect = QGraphicsBlurEffect()
            self.blur_effect.setBlurRadius(0)
            self.parent_widget.setGraphicsEffect(self.blur_effect)
            
            # Анимация блюра
            self.blur_anim = QPropertyAnimation(self.blur_effect, b"blurRadius")
            self.blur_anim.setDuration(300)
            self.blur_anim.setStartValue(0)
            self.blur_anim.setEndValue(15)
            self.blur_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        else:
            # Используем существующий блюр
            self.blur_effect = parent.graphicsEffect()
            self.blur_anim = None
        
        self.setup_ui(title, cancel_text)
        
        # Анимация появления
        self.setWindowOpacity(0)
        self.opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_anim.setDuration(300)
        self.opacity_anim.setStartValue(0)
        self.opacity_anim.setEndValue(1)
        self.opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
    def setup_ui(self, title, cancel_text):
        # Фиксируем размер диалога (увеличена ширина и высота для длинных текстов)
        self.setFixedSize(700, 280)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(25)
        container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Заголовок
        self.title_label = QLabel(title)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setWordWrap(True)
        self.title_label.setFixedSize(650, 90)  # Фиксированная высота для 3 строк
        self.title_label.setStyleSheet("font-size: 18px; font-weight: 600; color: white;")
        container_layout.addWidget(self.title_label)
        
        # Прогресс-бар (увеличена ширина)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedSize(600, 30)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #3498db;
                border-radius: 15px;
                background: rgba(30, 30, 30, 0.5);
                text-align: center;
                color: white;
                font-size: 12px;
            }
            QProgressBar::chunk {
                background: #3498db;
                border-radius: 11px;
                margin: 2px;
            }
        """)
        container_layout.addWidget(self.progress_bar, 0, Qt.AlignmentFlag.AlignCenter)
        
        # Кнопка отмены
        if cancel_text:
            cancel_btn = AnimatedActionButton(cancel_text, "#95a5a6")
            cancel_btn.setFixedSize(140, 45)
            cancel_btn.clicked.connect(self.cancel)
            container_layout.addWidget(cancel_btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        layout.addWidget(container)
        
    def setValue(self, value):
        self.current_value = value
        self.progress_bar.setValue(value)
        
    def setLabelText(self, text):
        self.title_label.setText(text)
        
    def wasCanceled(self):
        return self.was_canceled
        
    def cancel(self):
        self.was_canceled = True
        self.close_with_animation()
        
    def close_with_animation(self):
        self.opacity_anim.setDirection(QPropertyAnimation.Direction.Backward)
        self.opacity_anim.start()
        # Анимация убирания блюра (только если мы его создали)
        if not self.use_existing_blur and self.blur_anim:
            self.blur_anim.setDirection(QPropertyAnimation.Direction.Backward)
            self.blur_anim.start()
        QTimer.singleShot(300, self.finish_close)
        
    def close_keeping_blur(self):
        """Закрывает диалог без убирания блюра"""
        self._keep_blur_on_close = True
        self.opacity_anim.setDirection(QPropertyAnimation.Direction.Backward)
        self.opacity_anim.start()
        QTimer.singleShot(300, lambda: self.close())
        
    def finish_close(self):
        # Убираем блюр только если мы его создали
        if not self.use_existing_blur:
            self.parent_widget.setGraphicsEffect(None)
        self.close()
    
    def closeEvent(self, event):
        """При закрытии убираем blur только если не установлен флаг _keep_blur_on_close"""
        if not self._keep_blur_on_close and not self.use_existing_blur and self.parent_widget:
            self.parent_widget.setGraphicsEffect(None)
        super().closeEvent(event)
        
    def showEvent(self, event):
        super().showEvent(event)
        if self.parent_widget:
            parent_rect = self.parent_widget.geometry()
            self.move(
                parent_rect.x() + (parent_rect.width() - self.width()) // 2,
                parent_rect.y() + (parent_rect.height() - self.height()) // 2
            )
        # Запускаем анимации (только если создали блюр)
        if not self.use_existing_blur and self.blur_anim:
            self.blur_anim.start()
        self.opacity_anim.start()


class CustomInfoDialog(QDialog):
    """Кастомный информационный диалог с блюром"""
    
    def __init__(self, parent, title, message, use_existing_blur=False, icon_type="info", countdown_seconds=0):
        super().__init__(parent)
        self.parent_widget = parent
        self.use_existing_blur = use_existing_blur
        self.icon_type = icon_type  # "info", "success", "error"
        self.countdown_seconds = countdown_seconds  # Количество секунд до разблокировки кнопки
        self.remaining_seconds = countdown_seconds  # Оставшееся время
        
        # Настройка окна
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        
        # Применяем блюр к родительскому окну
        if use_existing_blur:
            # Проверяем есть ли уже blur эффект
            existing_blur = parent.graphicsEffect()
            if existing_blur and isinstance(existing_blur, QGraphicsBlurEffect):
                # Используем существующий блюр
                self.blur_effect = existing_blur
                self.blur_anim = None
            else:
                # Если blur нет, создаем новый
                self.blur_effect = QGraphicsBlurEffect()
                self.blur_effect.setBlurRadius(15)  # Сразу устанавливаем нужное значение
                self.parent_widget.setGraphicsEffect(self.blur_effect)
                self.blur_anim = None
        else:
            # Создаем новый blur с анимацией
            self.blur_effect = QGraphicsBlurEffect()
            self.blur_effect.setBlurRadius(0)
            self.parent_widget.setGraphicsEffect(self.blur_effect)
            
            # Анимация блюра
            self.blur_anim = QPropertyAnimation(self.blur_effect, b"blurRadius")
            self.blur_anim.setDuration(300)
            self.blur_anim.setStartValue(0)
            self.blur_anim.setEndValue(15)
            self.blur_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        self.setup_ui(title, message)
        
        # Анимация появления
        self.setWindowOpacity(0)
        self.opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_anim.setDuration(300)
        self.opacity_anim.setStartValue(0)
        self.opacity_anim.setEndValue(1)
        self.opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
    def setup_ui(self, title, message):
        # Адаптивный размер: три категории сообщений
        message_length = len(message)
        if message_length < 80:
            # Очень короткое сообщение (как "Ошибка") - компактное окно как CustomInputDialog
            dialog_height = 520
            spacing = 20
        elif message_length < 250:
            # Среднее сообщение (как "Автоматическое скачивание недоступно") - среднее окно
            dialog_height = 520
            spacing = 20
        else:
            # Длинное сообщение (как "Что делать?") - большое окно
            dialog_height = 750
            spacing = 15
        
        self.setFixedSize(700, dialog_height)
        
        # Основной layout - всегда центрируем по вертикали
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)  # Равные отступы со всех сторон
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(spacing)
        container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Иконка в зависимости от типа - ЕДИНЫЙ СТАНДАРТ 120x120
        icon_label = QLabel()
        
        # Определяем иконку и цвет в зависимости от типа
        # ВСЕ ИКОНКИ СИНИЕ (#3498db) для единого стиля
        if self.icon_type == "success":
            icon_filename = "allon.png"  # Используем иконку галочки
            icon_color = QColor(52, 152, 219)  # #3498db - синий
        elif self.icon_type == "error":
            icon_filename = "alloff.png"  # Используем иконку крестика
            icon_color = QColor(52, 152, 219)  # #3498db - синий
        else:  # info
            icon_filename = "info.png"  # Используем иконку info
            icon_color = QColor(52, 152, 219)  # #3498db - синий
        
        icon_path = get_resource_path(icon_filename)
        if icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                # ЕДИНЫЙ СТАНДАРТ: 120x120
                scaled_pixmap = pixmap.scaled(120, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                
                # Перекрашиваем в нужный цвет
                colored_pixmap = QPixmap(scaled_pixmap.size())
                colored_pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(colored_pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                painter.drawPixmap(0, 0, scaled_pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(colored_pixmap.rect(), icon_color)
                painter.end()
                
                icon_label.setPixmap(colored_pixmap)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(icon_label)
        
        # Заголовок - ЕДИНЫЙ СТАНДАРТ
        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 20px; font-weight: 600; color: white;")
        container_layout.addWidget(title_label)
        
        # Сообщение - меньший шрифт для длинных текстов
        self.message_label = QLabel(message)
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setWordWrap(True)
        self.message_label.setMaximumWidth(600)  # Ограничиваем ширину для лучшей читаемости
        self.message_label.setStyleSheet("font-size: 13px; color: white; line-height: 1.5;")
        
        # Проверяем, содержит ли сообщение HTML теги
        if '<' in message and '>' in message:
            self.message_label.setTextFormat(Qt.TextFormat.RichText)
            self.message_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse | 
                Qt.TextInteractionFlag.LinksAccessibleByMouse
            )
            self.message_label.setOpenExternalLinks(False)
            self.message_label.linkActivated.connect(self.handle_link_click)
        
        container_layout.addWidget(self.message_label, 0, Qt.AlignmentFlag.AlignCenter)
        
        container_layout.addSpacing(10)
        
        # Кнопка OK
        self.ok_btn = AnimatedActionButton("OK", "#3498db")
        self.ok_btn.setFixedSize(140, 50)
        self.ok_btn.clicked.connect(self.accept_dialog)
        container_layout.addWidget(self.ok_btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        # Если есть таймер обратного отсчета - блокируем кнопку и запускаем таймер
        if self.countdown_seconds > 0:
            self.ok_btn.setEnabled(False)
            self.ok_btn.setText(f"OK ({self.remaining_seconds})")
            self.countdown_timer = QTimer(self)
            self.countdown_timer.timeout.connect(self.update_countdown)
            self.countdown_timer.start(1000)  # Обновляем каждую секунду
        
        layout.addWidget(container)
        
    def handle_link_click(self, url):
        """Обрабатывает клики по ссылкам в диалоге"""
        if url.startswith('card:'):
            # Для номера карты - копируем в буфер обмена
            card_number = url.replace('card:', '')
            clipboard = QApplication.clipboard()
            clipboard.setText(card_number)
            
            # Показываем простое компактное уведомление над курсором
            tooltip = SimpleCopyTooltip(self)
            tooltip.show_at_cursor()
        else:
            # Для обычных ссылок - открываем в браузере
            import webbrowser
            webbrowser.open(url)
    
    def update_countdown(self):
        """Обновляет обратный отсчет на кнопке"""
        self.remaining_seconds -= 1
        
        if self.remaining_seconds > 0:
            # Обновляем текст кнопки с оставшимся временем
            self.ok_btn.setText(f"OK ({self.remaining_seconds})")
        else:
            # Таймер истек - разблокируем кнопку
            self.countdown_timer.stop()
            self.ok_btn.setEnabled(True)
            self.ok_btn.setText("OK")
    
    def accept_dialog(self):
        # Если таймер еще идет - не закрываем
        if self.countdown_seconds > 0 and self.remaining_seconds > 0:
            return
        self.close_with_animation()
    
    def keyPressEvent(self, event):
        """Блокируем закрытие по Escape во время таймера"""
        if event.key() == Qt.Key.Key_Escape:
            if self.countdown_seconds > 0 and self.remaining_seconds > 0:
                return  # Игнорируем Escape во время таймера
        super().keyPressEvent(event)
    
    def reject(self):
        """Блокируем закрытие диалога во время таймера"""
        if self.countdown_seconds > 0 and self.remaining_seconds > 0:
            return  # Не закрываем во время таймера
        super().reject()
        
    def close_with_animation(self):
        self.opacity_anim.setDirection(QPropertyAnimation.Direction.Backward)
        self.opacity_anim.start()
        if not self.use_existing_blur and self.blur_anim:
            self.blur_anim.setDirection(QPropertyAnimation.Direction.Backward)
            self.blur_anim.start()
        QTimer.singleShot(300, self.finish_close)
        
    def finish_close(self):
        # Всегда убираем блюр при закрытии диалога
        if self.parent_widget:
            self.parent_widget.setGraphicsEffect(None)
        self.accept()
        
    def showEvent(self, event):
        super().showEvent(event)
        if self.parent_widget:
            parent_rect = self.parent_widget.geometry()
            self.move(
                parent_rect.x() + (parent_rect.width() - self.width()) // 2,
                parent_rect.y() + (parent_rect.height() - self.height()) // 2
            )
        if not self.use_existing_blur and self.blur_anim:
            self.blur_anim.start()
        self.opacity_anim.start()
        
    @staticmethod
    def information(parent, title, message, use_existing_blur=False, icon_type="info", countdown_seconds=0):
        """Статический метод для показа информационного диалога
        
        icon_type: "info" (синий ?), "success" (зеленая ✓), "error" (красный ✗)
        countdown_seconds: количество секунд до разблокировки кнопки OK (0 = без таймера)
        """
        dialog = CustomInfoDialog(parent, title, message, use_existing_blur, icon_type, countdown_seconds)
        dialog.exec()


class CustomInputDialog(QDialog):
    """Кастомный диалог ввода текста с блюром"""
    
    def __init__(self, parent, title, message, default_text="", show_steamcmd_btn=False, use_existing_blur=False):
        super().__init__(parent)
        self.parent_widget = parent
        self.input_text = default_text
        self.show_steamcmd_btn = show_steamcmd_btn
        self.steamcmd_clicked = False
        self._keep_blur = False  # Флаг для сохранения блюра при закрытии
        self.addon_links = []  # Список добавленных ссылок
        
        # Настройка окна
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        
        # Применяем блюр к родительскому окну (если не используем существующий)
        if not use_existing_blur:
            self.blur_effect = QGraphicsBlurEffect()
            self.blur_effect.setBlurRadius(0)
            self.parent_widget.setGraphicsEffect(self.blur_effect)
            
            # Анимация блюра
            self.blur_anim = QPropertyAnimation(self.blur_effect, b"blurRadius")
            self.blur_anim.setDuration(300)
            self.blur_anim.setStartValue(0)
            self.blur_anim.setEndValue(15)
            self.blur_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        else:
            self.blur_effect = None
            self.blur_anim = None
        
        self.setup_ui(title, message, default_text)
        
        # Анимация появления
        self.setWindowOpacity(0)
        self.opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_anim.setDuration(300)
        self.opacity_anim.setStartValue(0)
        self.opacity_anim.setEndValue(1)
        self.opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
    def setup_ui(self, title, message, default_text):
        # Фиксируем размер диалога - ЕДИНЫЙ СТАНДАРТ
        self.setFixedSize(650, 520)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(20)  # ЕДИНЫЙ СТАНДАРТ отступов
        container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Иконка link.png (синяя) - ЕДИНЫЙ СТАНДАРТ 120x120
        icon_label = QLabel()
        icon_path = get_resource_path("link.png")
        if icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                # ЕДИНЫЙ СТАНДАРТ: 120x120
                scaled_pixmap = pixmap.scaled(120, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                
                # Перекрашиваем в синий цвет #3498db
                blue_pixmap = QPixmap(scaled_pixmap.size())
                blue_pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(blue_pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                painter.drawPixmap(0, 0, scaled_pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(blue_pixmap.rect(), QColor(52, 152, 219))  # #3498db
                painter.end()
                
                icon_label.setPixmap(blue_pixmap)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(icon_label)
        
        # Заголовок - ЕДИНЫЙ СТАНДАРТ
        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 20px; font-weight: 600; color: white;")
        container_layout.addWidget(title_label)
        
        # Сообщение - ЕДИНЫЙ СТАНДАРТ
        message_label = QLabel(message)
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setWordWrap(True)
        message_label.setStyleSheet("font-size: 13px; color: #b0b0b0;")
        message_label.setMaximumWidth(580)
        container_layout.addWidget(message_label)
        
        # Поле ввода
        self.input_field = QLineEdit()
        self.input_field.setText(default_text)
        self.input_field.setPlaceholderText(get_text("input_placeholder"))
        self.input_field.setFixedWidth(550)
        self.input_field.setFixedHeight(45)
        self.input_field.setStyleSheet("""
            QLineEdit {
                background-color: rgba(255, 255, 255, 0.1);
                border: 2px solid #3498db;
                border-radius: 8px;
                padding: 0px 15px;
                color: white;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 2px solid #5dade2;
                background-color: rgba(255, 255, 255, 0.15);
            }
        """)
        # Enter добавляет в список
        self.input_field.returnPressed.connect(self.add_link_to_list)
        container_layout.addWidget(self.input_field, 0, Qt.AlignmentFlag.AlignCenter)
        
        # Счетчик добавленных ссылок (скрыт по умолчанию)
        self.links_count_label = QLabel(get_text("links_added_counter", count=0))
        self.links_count_label.setStyleSheet("color: #808080; font-size: 11px;")
        self.links_count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(self.links_count_label)
        self.links_count_label.hide()  # Скрываем пока список пуст
        
        # Кнопки OK, Добавить и Отмена
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(15)
        buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        ok_btn = AnimatedActionButton("OK", "#3498db")
        ok_btn.setFixedSize(140, 50)
        ok_btn.clicked.connect(self.accept_dialog)
        buttons_layout.addWidget(ok_btn)
        
        # Кнопка "Добавить" между OK и Отмена
        add_btn = AnimatedActionButton(get_text("btn_add"), "#27ae60")
        add_btn.setFixedSize(140, 50)
        add_btn.clicked.connect(self.add_link_to_list)
        buttons_layout.addWidget(add_btn)
        
        cancel_btn = AnimatedActionButton(get_text("btn_cancel"), "#95a5a6")
        cancel_btn.setFixedSize(140, 50)
        cancel_btn.clicked.connect(self.reject_dialog)
        buttons_layout.addWidget(cancel_btn)
        
        container_layout.addLayout(buttons_layout)
        
        # Кнопка SteamCMD под кнопками OK и Отмена (если нужна)
        if self.show_steamcmd_btn:
            steamcmd_btn_layout = QHBoxLayout()
            steamcmd_btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            # Создаем простую кнопку без анимации, такого же размера как OK и Отмена
            steamcmd_settings_btn = AnimatedActionButton("SteamCMD", "#3498db")
            steamcmd_settings_btn.setFixedSize(140, 50)  # Такой же размер как OK и Отмена
            steamcmd_settings_btn.clicked.connect(self.open_steamcmd_settings)
            
            steamcmd_btn_layout.addWidget(steamcmd_settings_btn)
            
            container_layout.addLayout(steamcmd_btn_layout)
        
        layout.addWidget(container, 0, Qt.AlignmentFlag.AlignCenter)
    
    def add_link_to_list(self):
        """Добавляет ссылку в список"""
        link = self.input_field.text().strip()
        if not link:
            return
        
        # Проверяем что ссылка не дубликат
        if link in self.addon_links:
            return
        
        # Добавляем в список
        self.addon_links.append(link)
        
        # Обновляем счетчик и показываем его
        self.update_links_count()
        self.links_count_label.show()
        
        # Очищаем поле ввода
        self.input_field.clear()
        self.input_field.setFocus()
    
    def update_links_count(self):
        """Обновляет счетчик ссылок"""
        count = len(self.addon_links)
        self.links_count_label.setText(get_text("links_added_counter", count=count))
        
    def open_steamcmd_settings(self):
        """Открывает настройки SteamCMD"""
        self.steamcmd_clicked = True
        # Закрываем диалог с сохранением блюра
        self.close_keeping_blur()
        
    def close_keeping_blur(self):
        """Закрывает диалог без убирания блюра"""
        # Устанавливаем флаг что блюр нужно сохранить
        self._keep_blur = True
        self.opacity_anim.setDirection(QPropertyAnimation.Direction.Backward)
        self.opacity_anim.start()
        # НЕ убираем блюр - он останется для следующего диалога
        QTimer.singleShot(300, self.reject)
    
    def accept_dialog(self):
        # Если есть список ссылок, возвращаем его
        # Если нет, возвращаем текущее значение поля
        if self.addon_links:
            # Добавляем текущее значение поля если оно не пустое
            current = self.input_field.text().strip()
            if current and current not in self.addon_links:
                self.addon_links.append(current)
            self.input_text = self.addon_links  # Возвращаем список
        else:
            self.input_text = self.input_field.text()  # Возвращаем строку
        self.close_with_animation(True)
        
    def reject_dialog(self):
        self.close_with_animation(False)
        
    def close_with_animation(self, accepted):
        self.opacity_anim.setDirection(QPropertyAnimation.Direction.Backward)
        self.opacity_anim.start()
        if self.blur_anim:
            self.blur_anim.setDirection(QPropertyAnimation.Direction.Backward)
            self.blur_anim.start()
        if accepted:
            QTimer.singleShot(300, self.accept)
        else:
            QTimer.singleShot(300, self.reject)
        
    def closeEvent(self, event):
        # Убираем блюр при закрытии только если:
        # 1. Мы его создавали (self.blur_effect не None)
        # 2. И не нажата кнопка SteamCMD (иначе блюр нужен для следующего диалога)
        # 3. И не установлен флаг _keep_blur
        should_remove_blur = (
            self.blur_effect is not None and 
            not self.steamcmd_clicked and 
            not getattr(self, '_keep_blur', False)
        )
        if should_remove_blur:
            self.parent_widget.setGraphicsEffect(None)
        super().closeEvent(event)
        
    def showEvent(self, event):
        super().showEvent(event)
        if self.parent_widget:
            parent_rect = self.parent_widget.geometry()
            self.move(
                parent_rect.x() + (parent_rect.width() - self.width()) // 2,
                parent_rect.y() + (parent_rect.height() - self.height()) // 2
            )
        if self.blur_anim:
            self.blur_anim.start()
        self.opacity_anim.start()
        # Устанавливаем фокус на поле ввода
        self.input_field.setFocus()
        
    @staticmethod
    def getText(parent, title, message, default_text="", show_steamcmd_btn=False):
        """Статический метод для получения текста от пользователя"""
        dialog = CustomInputDialog(parent, title, message, default_text, show_steamcmd_btn)
        result = dialog.exec()
        return dialog.input_text, result == QDialog.DialogCode.Accepted, dialog.steamcmd_clicked





class CustomSteamCMDManageDialog(QDialog):
    """Кастомный диалог управления SteamCMD в стиле CustomConfirmDialog"""
    
    def __init__(self, parent, steamcmd_path, use_existing_blur=False):
        super().__init__(parent)
        self.parent_widget = parent
        self.steamcmd_path = steamcmd_path
        self.result_code = 0  # 0 = закрыть, 1 = переустановить, 2 = удалить
        
        # Настройка окна
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        
        # Применяем блюр к родительскому окну (если не используем существующий)
        if not use_existing_blur:
            self.blur_effect = QGraphicsBlurEffect()
            self.blur_effect.setBlurRadius(0)
            self.parent_widget.setGraphicsEffect(self.blur_effect)
            
            # Анимация блюра
            self.blur_anim = QPropertyAnimation(self.blur_effect, b"blurRadius")
            self.blur_anim.setDuration(300)
            self.blur_anim.setStartValue(0)
            self.blur_anim.setEndValue(15)
            self.blur_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        else:
            self.blur_effect = None
            self.blur_anim = None
        
        self.setup_ui()
        
        # Анимация появления
        self.setWindowOpacity(0)
        self.opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_anim.setDuration(300)
        self.opacity_anim.setStartValue(0)
        self.opacity_anim.setEndValue(1)
        self.opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
    def setup_ui(self):
        # Фиксируем размер диалога - ЕДИНЫЙ СТАНДАРТ
        self.setFixedSize(650, 520)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(20)  # ЕДИНЫЙ СТАНДАРТ отступов
        container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Иконка settings.png (синяя) - ЕДИНЫЙ СТАНДАРТ 120x120
        icon_label = QLabel()
        icon_path = get_resource_path("settings.png")
        if icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                # ЕДИНЫЙ СТАНДАРТ: 120x120
                scaled_pixmap = pixmap.scaled(120, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                
                # Перекрашиваем в синий цвет #3498db
                blue_pixmap = QPixmap(scaled_pixmap.size())
                blue_pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(blue_pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                painter.drawPixmap(0, 0, scaled_pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(blue_pixmap.rect(), QColor(52, 152, 219))  # #3498db
                painter.end()
                
                icon_label.setPixmap(blue_pixmap)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(icon_label)
        
        # Заголовок - ЕДИНЫЙ СТАНДАРТ
        title_label = QLabel(get_text("steamcmd_management"))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 20px; font-weight: 600; color: white;")
        container_layout.addWidget(title_label)
        
        # Информация о пути
        path_label = QLabel(get_text("installation_path", path=self.steamcmd_path))
        path_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        path_label.setWordWrap(True)
        path_label.setStyleSheet("font-size: 11px; color: #808080; background: rgba(255,255,255,0.05); padding: 10px; border-radius: 6px;")
        path_label.setMaximumWidth(580)
        container_layout.addWidget(path_label)
        
        # Сообщение - ЕДИНЫЙ СТАНДАРТ
        message_label = QLabel(
            get_text("steamcmd_description") + "\n\n" +
            get_text("steamcmd_manage_message")
        )
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setWordWrap(True)
        message_label.setStyleSheet("font-size: 13px; color: #b0b0b0;")
        message_label.setMaximumWidth(580)
        container_layout.addWidget(message_label)
        
        # Кнопки
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(15)
        buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        reinstall_btn = AnimatedActionButton(get_text("btn_reinstall"), "#3498db")
        reinstall_btn.setFixedSize(140, 50)
        reinstall_btn.clicked.connect(self.reinstall_clicked)
        buttons_layout.addWidget(reinstall_btn)
        
        delete_btn = AnimatedActionButton(get_text("btn_delete"), "#e74c3c")
        delete_btn.setFixedSize(140, 50)
        delete_btn.clicked.connect(self.delete_clicked)
        buttons_layout.addWidget(delete_btn)
        
        close_btn = AnimatedActionButton(get_text("btn_close"), "#95a5a6")
        close_btn.setFixedSize(140, 50)
        close_btn.clicked.connect(self.close_clicked)
        buttons_layout.addWidget(close_btn)
        
        container_layout.addLayout(buttons_layout)
        
        layout.addWidget(container, 0, Qt.AlignmentFlag.AlignCenter)
        
    def reinstall_clicked(self):
        self.result_code = 1
        self.close_with_animation()
        
    def delete_clicked(self):
        self.result_code = 2
        self.close_with_animation()
        
    def close_clicked(self):
        self.result_code = 0
        self.close_with_animation()
        
    def close_with_animation(self):
        self.opacity_anim.setDirection(QPropertyAnimation.Direction.Backward)
        self.opacity_anim.start()
        if self.blur_anim:
            self.blur_anim.setDirection(QPropertyAnimation.Direction.Backward)
            self.blur_anim.start()
        QTimer.singleShot(300, lambda: self.done(self.result_code))
    
    def close_keeping_blur(self):
        """Закрывает диалог без убирания блюра"""
        self.opacity_anim.setDirection(QPropertyAnimation.Direction.Backward)
        self.opacity_anim.start()
        # НЕ убираем блюр - он останется для следующего диалога
        QTimer.singleShot(300, lambda: self.done(self.result_code))
    
    def closeEvent(self, event):
        """При закрытии убираем blur если мы его создавали"""
        if self.blur_effect is not None and self.parent_widget:
            self.parent_widget.setGraphicsEffect(None)
        super().closeEvent(event)
        
    def showEvent(self, event):
        super().showEvent(event)
        if self.blur_anim:
            self.blur_anim.start()
        self.opacity_anim.start()


class MainWindow(QMainWindow):
    """Главное окно"""
    
    def __init__(self):
        super().__init__()
        self.game_folder = None
        self.gameinfo_path = None  
        self.workshop_path = None
        self.addons = []
        self.cards = []
        self.first_launch = False  # Флаг первого запуска для показа уведомления (определяется позже)
        self.steamcmd_custom_path = None  # Путь к SteamCMD
        self.last_donate_reminder = 0  # Время последнего напоминания о донатов
        self.current_language = "ru"  # Текущий язык интерфейса
        self.animations_disabled = False  # Флаг для временного отключения анимаций
        
        # Инициализируем локализацию ПЕРЕД созданием UI
        self.init_localization()
        
        # Создаём UI с правильным языком
        self.setup_ui()
        self.apply_dark_styles()  # Применяем только темную тему
        self.load_config()
        
        # Настраиваем систему обновлений
        try:
            self.setup_updater()
        except Exception as e:
            print(f"Ошибка настройки системы обновлений: {e}")
        
        if not self.game_folder:
            self.auto_detect_paths()
        
        # Welcome screen будет показан после show() в main
        QTimer.singleShot(100, self.show_welcome)
    
    def init_localization(self):
        """Инициализирует систему локализации"""
        print(f"🌍 init_localization called")
        try:
            # Проверяем, есть ли сохраненный язык
            saved_language = load_language_preference(CONFIG_FILE)
            print(f"🌍 init_localization: load_language_preference returned: {saved_language}")
            
            # Если конфиг не существует, отмечаем что нужно показать диалог языка
            if not CONFIG_FILE.exists():
                print("🌍 First launch detected, language dialog will be shown")
                self.needs_language_selection = True
                # Пока устанавливаем русский по умолчанию
                set_language("ru")
                self.current_language = "ru"
            else:
                print(f"🌍 Config exists, loading saved language: {saved_language}")
                # Загружаем сохраненный язык
                set_language(saved_language)
                self.current_language = saved_language
                self.needs_language_selection = False
                
            print(f"🌍 Language set to: {self.current_language}")
            
        except Exception as e:
            print(f"❌ Error initializing localization: {e}")
            # Fallback на русский
            set_language("ru")
            self.current_language = "ru"
            self.needs_language_selection = False
    
    def setup_ui(self):
        self.setWindowTitle(get_text("app_title"))
        self.setFixedSize(1000, 700)
        
        # Центральный виджет
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Header
        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(80)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(20, 0, 20, 0)  # Уменьшили отступы для экономии места
        
        # Иконка logo.png
        logo_icon = QLabel()
        logo_path = get_resource_path("logo.png")
        if logo_path.exists():
            pixmap = QPixmap(str(logo_path))
            if not pixmap.isNull():
                # Масштабируем до 50x50 для header
                scaled_pixmap = pixmap.scaled(50, 50, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                logo_icon.setPixmap(scaled_pixmap)
                h_layout.addWidget(logo_icon)
        
        # Отступ между иконкой и текстом
        h_layout.addSpacing(15)
        
        # Логотип (минималистичный)
        logo = QLabel(get_text("app_title"))
        logo.setObjectName("headerTitle")
        logo.setFixedWidth(350)  # Увеличиваем ширину еще больше
        logo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        logo.setWordWrap(False)  # Отключаем перенос строк
        logo.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        # Принудительно обновляем размер и текст
        logo.adjustSize()
        logo.updateGeometry()
        
        h_layout.addWidget(logo)
        
        # Сохраняем ссылку на logo для возможного обновления
        self.header_logo = logo
        
        # Добавляем растягивающийся элемент и минимальный отступ
        h_layout.addStretch()
        h_layout.addSpacing(30)  # Уменьшенный отступ для экономии места
        
        # Кнопка "Поддержать проект" с анимацией падающих сердечек
        donate_btn = AnimatedDonateButton(f"  {get_text('btn_support_project')}")
        donate_btn.clicked.connect(self.show_donate_dialog)
        h_layout.addWidget(donate_btn)
        
        # Кнопка проверки обновлений (если система обновлений доступна)
        if UPDATER_AVAILABLE:
            h_layout.addSpacing(2)
            
            update_btn = QPushButton(f"  {get_text('btn_updates')}")
            update_btn.setObjectName("updateButton")
            update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            update_btn.setFixedHeight(40)
            update_btn.setToolTip(get_text("btn_updates"))
            
            upd_icon_path = Path(__file__).parent / "upd.png"
            if upd_icon_path.exists():
                pixmap = QPixmap(str(upd_icon_path))
                if not pixmap.isNull():
                    scaled_pixmap = pixmap.scaled(16, 16, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    
                    white_pixmap = QPixmap(scaled_pixmap.size())
                    white_pixmap.fill(Qt.GlobalColor.transparent)
                    painter = QPainter(white_pixmap)
                    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                    painter.drawPixmap(0, 0, scaled_pixmap)
                    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                    painter.fillRect(white_pixmap.rect(), QColor(255, 255, 255))
                    painter.end()
                    
                    update_btn.setIcon(QIcon(white_pixmap))
                    update_btn.setIconSize(QSize(16, 16))
            
            update_btn.clicked.connect(self.check_for_updates)
            h_layout.addWidget(update_btn)
            
            h_layout.addSpacing(2)
            
            github_btn = QPushButton(f"  {get_text('btn_github')}")
            github_btn.setObjectName("githubButton")
            github_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            github_btn.setFixedHeight(40)
            github_btn.setToolTip(get_text("btn_github"))
            
            git_icon_path = Path(__file__).parent / "git.png"
            if git_icon_path.exists():
                pixmap = QPixmap(str(git_icon_path))
                if not pixmap.isNull():
                    scaled_pixmap = pixmap.scaled(16, 16, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    
                    white_pixmap = QPixmap(scaled_pixmap.size())
                    white_pixmap.fill(Qt.GlobalColor.transparent)
                    painter = QPainter(white_pixmap)
                    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                    painter.drawPixmap(0, 0, scaled_pixmap)
                    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                    painter.fillRect(white_pixmap.rect(), QColor(255, 255, 255))
                    painter.end()
                    
                    github_btn.setIcon(QIcon(white_pixmap))
                    github_btn.setIconSize(QSize(16, 16))
            
            github_btn.clicked.connect(self.open_github_repo)
            h_layout.addWidget(github_btn)
            
            # Кнопка Telegram (круглая, компактная)
            h_layout.addSpacing(2)
            
            telegram_btn = QPushButton()  # Убираем текст
            telegram_btn.setObjectName("telegramButton")
            telegram_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            telegram_btn.setFixedSize(32, 32)  # Меньший размер, чтобы не закрывать название
            telegram_btn.setToolTip("Telegram Community")  # Тултип на английском для универсальности
            
            tg_icon_path = Path(__file__).parent / "tg.png"
            if tg_icon_path.exists():
                pixmap = QPixmap(str(tg_icon_path))
                if not pixmap.isNull():
                    scaled_pixmap = pixmap.scaled(16, 16, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    
                    # Перекрашиваем в белый цвет для иконки
                    white_pixmap = QPixmap(scaled_pixmap.size())
                    white_pixmap.fill(Qt.GlobalColor.transparent)
                    painter = QPainter(white_pixmap)
                    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                    painter.drawPixmap(0, 0, scaled_pixmap)
                    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                    painter.fillRect(white_pixmap.rect(), QColor(255, 255, 255))
                    painter.end()
                    
                    telegram_btn.setIcon(QIcon(white_pixmap))
                    telegram_btn.setIconSize(QSize(16, 16))  # Пропорциональный размер иконки
            
            telegram_btn.clicked.connect(self.show_telegram_community_dialog)
            h_layout.addWidget(telegram_btn)
            
            # Добавляем отступ справа от кнопки Telegram
            h_layout.addSpacing(10)
        
        main_layout.addWidget(header)
        
        # Табы (по центру как на картинке)
        tabs_container = QWidget()
        tabs_container.setFixedHeight(60)
        tabs_layout = QHBoxLayout(tabs_container)
        tabs_layout.setContentsMargins(0, 10, 0, 0)
        
        tabs_layout.addStretch()
        
        # Кнопки табов с анимацией подпрыгивания
        self.tab_buttons = []
        tabs_data = [
            (get_text("tab_addons"), 0, "addon.png"),
            (get_text("tab_pirate_addons"), 1, "addon.png"),
            (get_text("tab_settings"), 2, "settings.png"),
            (get_text("tab_language"), 3, "lang.png"),
            (get_text("tab_help"), 4, "spravka.png"),
            (get_text("tab_contacts"), 5, "con.png")  # Иконка контактов
        ]
        
        for text, index, icon_name in tabs_data:
            btn = AnimatedTabButton(text, icon_name)
            btn.clicked.connect(lambda checked, i=index: self.switch_tab(i))
            tabs_layout.addWidget(btn)
            self.tab_buttons.append(btn)
        
        tabs_layout.addStretch()
        main_layout.addWidget(tabs_container)
        
        # Stacked widget для контента
        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack)
        
        self.create_addons_tab()
        self.create_pirate_addons_tab()
        self.create_settings_tab()
        self.create_language_tab()
        self.create_faq_tab()
        self.create_contacts_tab()
        
        # Активируем первую вкладку
        self.switch_tab(0)

    
    def create_addons_tab(self):
        """Вкладка аддонов Workshop"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Контейнер для заголовка и описания (чтобы скрывать во время загрузки)
        self.tab_header_container = QWidget()
        header_layout = QVBoxLayout(self.tab_header_container)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)
        
        # Заголовок с иконкой
        title_container = QHBoxLayout()
        title_container.setSpacing(0)  # Уменьшенный отступ между иконкой и текстом
        
        # Загружаем иконку addon.png
        title_icon = QLabel()
        addon_icon_path = Path(__file__).parent / "addon.png"
        if addon_icon_path.exists():
            pixmap = QPixmap(str(addon_icon_path))
            # Перекрашиваем в белый цвет
            painter = QPainter(pixmap)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(pixmap.rect(), QColor(255, 255, 255, 200))
            painter.end()
            
            # Масштабируем до 24x24
            scaled_pixmap = pixmap.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            title_icon.setPixmap(scaled_pixmap)
        title_icon.setFixedSize(24, 24)  # Фиксированный размер для выравнивания
        title_icon.setStyleSheet("margin-top: -9px; padding-top: 9px;")  # Сдвигаем вверх и добавляем padding чтобы не обрезалось
        title_container.addWidget(title_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        
        title = QLabel(get_text("tab_addons_title"))
        title.setObjectName("sectionTitle")
        title_container.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        title_container.addStretch()  # Stretch остается чтобы прижать к левому краю
        
        header_layout.addLayout(title_container)
        
        # Цвет текста для темной темы
        text_color = "#d0d0d0"
        
        desc = QLabel()
        desc.setWordWrap(True)
        desc.setTextFormat(Qt.TextFormat.RichText)
        
        # ВАЖНО: убираем фон у label
        desc.setAutoFillBackground(False)
        desc.setStyleSheet("background: transparent; border: none;")
        
        desc.setText(
            f'<span style="color: {text_color}; font-size: 12px;">'
            f'{get_text("addons_description_full")}'
            f'</span>'
        )
        header_layout.addWidget(desc)
        
        header_layout.addSpacing(10)
        
        # Добавляем контейнер заголовка в основной layout
        layout.addWidget(self.tab_header_container)
        
        # Контейнер для всех элементов управления (чтобы скрывать во время загрузки)
        self.controls_container = QWidget()
        controls_layout = QVBoxLayout(self.controls_container)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(0)
        
        # Поиск и кнопки (минималистичные)
        top = QHBoxLayout()
        top.setSpacing(5)  # Одинаковый отступ между всеми элементами
        top.setAlignment(Qt.AlignmentFlag.AlignVCenter)  # Выравнивание по вертикали
        top.setContentsMargins(8, 0, 0, 0)  # Отступ слева 8px чтобы выровнять с карточками
        
        # Контейнер для поля поиска с кнопкой очистки
        search_container = QWidget()
        search_container.setFixedWidth(380)  # Уменьшили на 20px
        search_container.setFixedHeight(45)
        
        # Поле поиска
        self.search = QLineEdit(search_container)
        self.search.setPlaceholderText(get_text("search_placeholder"))
        self.search.setObjectName("searchBox")
        self.search.setGeometry(0, 0, 380, 45)  # Уменьшили на 20px
        self.search.textChanged.connect(self.filter_addons)
        
        clear_btn = QPushButton(search_container)
        clear_btn.setFixedSize(32, 32)
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.clicked.connect(lambda: self.search.clear())
        
        # Позиционируем кнопку: справа с отступом 8px, по центру по вертикали
        clear_btn.move(340, 7)  # Сдвинули на 20px влево
        clear_btn.raise_()
        
        # Загружаем и устанавливаем иконку
        x_icon_path = Path(__file__).parent / "x.png"
        if x_icon_path.exists():
            pixmap = QPixmap(str(x_icon_path))
            painter = QPainter(pixmap)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(pixmap.rect(), QColor(255, 255, 255, 200))
            painter.end()
            clear_btn.setIcon(QIcon(pixmap))
            clear_btn.setIconSize(QSize(14, 14))
        
        # Стили для кнопки
        clear_btn.setStyleSheet("""
            QPushButton {
                background: rgba(60, 60, 60, 180);
                border: none;
                border-radius: 16px;
            }
            QPushButton:hover {
                background: rgba(80, 80, 80, 200);
            }
            QPushButton:pressed {
                background: rgba(50, 50, 50, 220);
            }
        """)
        
        # Добавляем анимацию масштабирования при наведении
        clear_btn._scale = 1.0
        clear_btn_anim = QPropertyAnimation(clear_btn, b"iconSize")
        clear_btn_anim.setDuration(150)
        clear_btn_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        original_enter = clear_btn.enterEvent
        original_leave = clear_btn.leaveEvent
        
        def on_clear_enter(event):
            clear_btn_anim.stop()
            clear_btn_anim.setStartValue(QSize(14, 14))
            clear_btn_anim.setEndValue(QSize(16, 16))
            clear_btn_anim.start()
            if original_enter:
                original_enter(event)
        
        def on_clear_leave(event):
            clear_btn_anim.stop()
            clear_btn_anim.setStartValue(QSize(16, 16))
            clear_btn_anim.setEndValue(QSize(14, 14))
            clear_btn_anim.start()
            if original_leave:
                original_leave(event)
        
        clear_btn.enterEvent = on_clear_enter
        clear_btn.leaveEvent = on_clear_leave
        
        top.addWidget(search_container)
        
        # Счетчик аддонов - компактный, закруглённый
        self.counter = QLabel("0")
        self.counter.setObjectName("compactCounter")
        self.counter.setFixedHeight(45)  # Как у кнопок
        self.counter.setMaximumWidth(180)  # Максимальная ширина чтобы не перекрывать поиск
        self.counter.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.counter.setWordWrap(False)  # Отключаем перенос строк
        self.counter.setStyleSheet("""
            QLabel#compactCounter {
                background: #2a2a2a;
                border-radius: 22px;
                color: #d0d0d0;
                font-size: 10px;
                font-weight: 500;
                padding: 0px 12px;
            }
        """)
        top.addWidget(self.counter)
        
        # Кнопка "Включить все" - анимированная синяя с иконкой
        enable_all_btn = AnimatedActionButton(get_text("btn_enable_all"), "allon.png")
        enable_all_btn.setObjectName("enableAllBtn")
        enable_all_btn.setFixedSize(135, 45)  # Уменьшил до 135
        enable_all_btn.setToolTip(get_text("btn_enable_all"))
        btn_font = QFont()
        btn_font.setPixelSize(10)
        btn_font.setWeight(QFont.Weight.DemiBold)
        enable_all_btn.setFont(btn_font)
        enable_all_btn.clicked.connect(self.enable_all_addons)
        top.addWidget(enable_all_btn)
        
        # Кнопка "Выключить все" - анимированная синяя с иконкой
        disable_all_btn = AnimatedActionButton(get_text("btn_disable_all"), "alloff.png")
        disable_all_btn.setObjectName("disableAllBtn")
        disable_all_btn.setFixedSize(145, 45)  # Уменьшил до 145
        disable_all_btn.setToolTip(get_text("btn_disable_all"))
        disable_all_btn.setFont(btn_font)
        disable_all_btn.clicked.connect(self.disable_all_addons)
        top.addWidget(disable_all_btn)
        
        # Кнопка обновления с анимацией вращения (перед сортировкой)
        refresh = AnimatedRefreshButton()
        refresh.clicked.connect(self.scan_addons)
        top.addWidget(refresh)
        
        # Выбор сортировки с иконкой (после обновления)
        self.sort_combo = AnimatedSortComboBox()
        self.sort_combo.currentIndexChanged.connect(lambda: self.display_addons())
        top.addWidget(self.sort_combo)
        
        controls_layout.addLayout(top)
        
        # Скролл
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("addonScroll")
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        self.addons_container = QWidget()
        self.addons_layout = QVBoxLayout(self.addons_container)
        self.addons_layout.setSpacing(10)
        self.addons_layout.addStretch()
        
        scroll.setWidget(self.addons_container)
        controls_layout.addWidget(scroll)
        
        # Добавляем контейнер с элементами управления в основной layout
        layout.addWidget(self.controls_container)
        
        self.stack.addWidget(tab)
    
    def create_pirate_addons_tab(self):
        """Вкладка аддонов для пиратки (устанавливает в left4dead2/addons)"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Заголовок с иконкой
        title_container = QHBoxLayout()
        title_container.setSpacing(0)  # Уменьшенный отступ между иконкой и текстом
        
        # Загружаем иконку addon.png
        title_icon = QLabel()
        addon_icon_path = Path(__file__).parent / "addon.png"
        if addon_icon_path.exists():
            pixmap = QPixmap(str(addon_icon_path))
            # Перекрашиваем в белый цвет
            painter = QPainter(pixmap)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(pixmap.rect(), QColor(255, 255, 255, 200))
            painter.end()
            
            # Масштабируем до 24x24
            scaled_pixmap = pixmap.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            title_icon.setPixmap(scaled_pixmap)
        title_icon.setFixedSize(24, 24)  # Фиксированный размер для выравнивания
        title_icon.setStyleSheet("margin-top: -9px; padding-top: 9px;")  # Сдвигаем вверх и добавляем padding чтобы не обрезалось
        title_container.addWidget(title_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        
        title = QLabel(get_text("tab_pirate_addons"))
        title.setObjectName("sectionTitle")
        title_container.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        title_container.addStretch()  # Stretch остается чтобы прижать к левому краю
        
        layout.addLayout(title_container)
        
        # Цвет текста для темной темы
        text_color = "#d0d0d0"
        
        desc = QLabel()
        desc.setWordWrap(True)
        desc.setTextFormat(Qt.TextFormat.RichText)
        
        # ВАЖНО: убираем фон у label
        desc.setAutoFillBackground(False)
        desc.setStyleSheet("background: transparent; border: none;")
        
        desc.setText(
            f'<span style="color: {text_color}; font-size: 12px;">'
            f'{get_text("pirate_addons_description_full")}'
            f'</span>'
        )
        layout.addWidget(desc)
        
        layout.addSpacing(10)
        
        # Поиск и кнопки (как в первой вкладке)
        top = QHBoxLayout()
        top.setSpacing(5)  # Одинаковый отступ между всеми элементами
        top.setAlignment(Qt.AlignmentFlag.AlignVCenter)  # Выравнивание по вертикали
        top.setContentsMargins(8, 0, 0, 0)  # Отступ слева 8px чтобы выровнять с карточками
        
        # Контейнер для поля поиска с кнопкой очистки
        pirate_search_container = QWidget()
        pirate_search_container.setFixedWidth(330)
        pirate_search_container.setFixedHeight(45)
        
        # Поле поиска (на всю высоту контейнера)
        self.pirate_search = QLineEdit(pirate_search_container)
        self.pirate_search.setPlaceholderText(get_text("search_placeholder"))
        self.pirate_search.setObjectName("searchBox")
        self.pirate_search.setGeometry(0, 0, 330, 45)
        self.pirate_search.textChanged.connect(self.filter_pirate_addons)
        
        clear_pirate_btn = QPushButton(pirate_search_container)
        clear_pirate_btn.setFixedSize(32, 32)
        clear_pirate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_pirate_btn.clicked.connect(lambda: self.pirate_search.clear())
        
        # Позиционируем кнопку: справа с отступом 8px, по центру по вертикали
        clear_pirate_btn.move(290, 7)
        clear_pirate_btn.raise_()
        
        # Загружаем и устанавливаем иконку
        x_icon_path = Path(__file__).parent / "x.png"
        if x_icon_path.exists():
            pixmap = QPixmap(str(x_icon_path))
            painter = QPainter(pixmap)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(pixmap.rect(), QColor(255, 255, 255, 200))
            painter.end()
            clear_pirate_btn.setIcon(QIcon(pixmap))
            clear_pirate_btn.setIconSize(QSize(14, 14))
        
        # Стили для кнопки
        clear_pirate_btn.setStyleSheet("""
            QPushButton {
                background: rgba(60, 60, 60, 180);
                border: none;
                border-radius: 16px;
            }
            QPushButton:hover {
                background: rgba(80, 80, 80, 200);
            }
            QPushButton:pressed {
                background: rgba(50, 50, 50, 220);
            }
        """)
        
        # Добавляем анимацию масштабирования при наведении
        clear_pirate_btn._scale = 1.0
        clear_pirate_anim = QPropertyAnimation(clear_pirate_btn, b"iconSize")
        clear_pirate_anim.setDuration(150)
        clear_pirate_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        original_pirate_enter = clear_pirate_btn.enterEvent
        original_pirate_leave = clear_pirate_btn.leaveEvent
        
        def on_pirate_clear_enter(event):
            clear_pirate_anim.stop()
            clear_pirate_anim.setStartValue(QSize(14, 14))
            clear_pirate_anim.setEndValue(QSize(16, 16))
            clear_pirate_anim.start()
            if original_pirate_enter:
                original_pirate_enter(event)
        
        def on_pirate_clear_leave(event):
            clear_pirate_anim.stop()
            clear_pirate_anim.setStartValue(QSize(16, 16))
            clear_pirate_anim.setEndValue(QSize(14, 14))
            clear_pirate_anim.start()
            if original_pirate_leave:
                original_pirate_leave(event)
        
        clear_pirate_btn.enterEvent = on_pirate_clear_enter
        clear_pirate_btn.leaveEvent = on_pirate_clear_leave
        
        top.addWidget(pirate_search_container)
        
        # Счетчик аддонов - компактный, закруглённый
        self.pirate_counter = QLabel("0")
        self.pirate_counter.setObjectName("compactCounter")
        self.pirate_counter.setFixedHeight(45)  # Как у кнопок
        self.pirate_counter.setMaximumWidth(180)  # Максимальная ширина чтобы не перекрывать поиск
        self.pirate_counter.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.pirate_counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pirate_counter.setWordWrap(False)  # Отключаем перенос строк
        self.pirate_counter.setStyleSheet("""
            QLabel#compactCounter {
                background: #2a2a2a;
                border-radius: 22px;
                color: #d0d0d0;
                font-size: 10px;
                font-weight: 500;
                padding: 0px 12px;
            }
        """)
        top.addWidget(self.pirate_counter)
        
        # Кнопка "Добавить VPK" - анимированная синяя с иконкой
        add_vpk_btn = AnimatedActionButton(get_text("btn_add_vpk"), "add.png")
        add_vpk_btn.setObjectName("addVpkBtn")
        add_vpk_btn.setFixedSize(160, 45)  # Увеличил ширину для лучшего центрирования
        add_vpk_btn.setToolTip(get_text("add_vpk_tooltip"))
        btn_font2 = QFont()
        btn_font2.setPixelSize(10)
        btn_font2.setWeight(QFont.Weight.Medium)
        add_vpk_btn.setFont(btn_font2)
        add_vpk_btn.clicked.connect(self.add_vpk_to_addons)
        top.addWidget(add_vpk_btn)
        
        # Кнопка "Workshop" - анимированная синяя с иконкой
        workshop_btn = AnimatedActionButton("Workshop", "link.png")
        workshop_btn.setObjectName("workshopBtn")
        workshop_btn.setFixedSize(130, 45)  # Увеличил ширину для лучшего центрирования
        workshop_btn.setToolTip(get_text("workshop_download_tooltip"))
        workshop_btn.setFont(btn_font2)
        workshop_btn.clicked.connect(self.download_from_workshop)
        top.addWidget(workshop_btn)
        
        # Кнопка обновления с анимацией вращения (перед сортировкой)
        refresh_pirate = AnimatedRefreshButton()
        refresh_pirate.clicked.connect(self.scan_pirate_addons)
        top.addWidget(refresh_pirate)
        
        # Выбор сортировки для пиратских аддонов с иконкой (после обновления)
        self.pirate_sort_combo = AnimatedSortComboBox()
        self.pirate_sort_combo.currentIndexChanged.connect(lambda: self.display_pirate_addons())
        top.addWidget(self.pirate_sort_combo)
        
        # Кнопка переключения вида (1/2 столбца) для пиратской вкладки
        self.pirate_view_toggle_btn = AnimatedViewToggleButton()
        self.pirate_view_toggle_btn.clicked.connect(self.toggle_pirate_view_mode)
        top.addWidget(self.pirate_view_toggle_btn)
        
        layout.addLayout(top)
        
        # Скролл для списка модов
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("addonScroll")
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        self.pirate_addons_container = QWidget()
        self.pirate_addons_layout = QVBoxLayout(self.pirate_addons_container)
        self.pirate_addons_layout.setSpacing(10)
        self.pirate_addons_layout.addStretch()
        self.is_pirate_two_column_mode = False  # Режим отображения для пиратской вкладки
        
        scroll.setWidget(self.pirate_addons_container)
        layout.addWidget(scroll)
        
        self.stack.addWidget(tab)
        
        # Сканируем моды при создании вкладки
        QTimer.singleShot(100, self.scan_pirate_addons)
    
    def scan_pirate_addons(self):
        """Сканирует моды в папке left4dead2/addons/"""
        print(f"🏴‍☠️ Starting pirate addons scan...")
        print(f"   game_folder: {self.game_folder}")
        
        if not self.game_folder:
            print("❌ No game folder set for pirate scan")
            self.set_counter_text(self.pirate_counter, get_text("configure_game_path"), 22)
            return
        
        addons_path = self.game_folder / "left4dead2" / "addons"
        print(f"   addons_path: {addons_path}")
        print(f"   addons_path exists: {addons_path.exists()}")
        
        # Если папка не существует, создаем её и показываем сообщение
        if not addons_path.exists():
            try:
                addons_path.mkdir(parents=True, exist_ok=True)
            except:
                pass
            self.show_no_pirate_addons_message()
            return
        
        # Очищаем список
        while self.pirate_addons_layout.count() > 1:
            item = self.pirate_addons_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Ищем .vpk и .vpk.disabled файлы
        all_files = list(addons_path.glob("*.vpk*"))
        
        # Создаем список модов с информацией о статусе
        self.pirate_addons_data = []
        for file_path in all_files:
            if file_path.suffix == '.vpk':
                # Включенный мод
                self.pirate_addons_data.append({'path': file_path, 'enabled': True, 'name': file_path.stem})
            elif file_path.name.endswith('.vpk.disabled'):
                # Выключенный мод
                name = file_path.name.replace('.vpk.disabled', '')
                self.pirate_addons_data.append({'path': file_path, 'enabled': False, 'name': name})
        
        if not self.pirate_addons_data:
            # Показываем красивое сообщение с кнопками
            self.show_no_pirate_addons_message()
            return
        
        # Отображаем карточки
        self.display_pirate_addons()
    
    def display_pirate_addons(self):
        """Отображает пиратские аддоны с учетом сортировки (оптимизированная версия)"""
        if not hasattr(self, 'pirate_addons_data') or not self.pirate_addons_data:
            return
        
        # Получаем выбранный тип сортировки
        sort_type = self.pirate_sort_combo.currentIndex() if hasattr(self, 'pirate_sort_combo') else 0
        
        # Применяем сортировку
        if sort_type == 0:  # По алфавиту
            sorted_addons = sorted(self.pirate_addons_data, key=lambda a: a['name'].lower())
        elif sort_type == 1:  # Сначала включенные
            sorted_addons = sorted(self.pirate_addons_data, key=lambda a: (not a['enabled'], a['name'].lower()))
        else:  # Сначала выключенные (sort_type == 2)
            sorted_addons = sorted(self.pirate_addons_data, key=lambda a: (a['enabled'], a['name'].lower()))
        
        # Собираем существующие карточки в словарь по пути к файлу
        existing_cards = {}
        # Извлекаем все элементы из layout
        while self.pirate_addons_layout.count():
            item = self.pirate_addons_layout.takeAt(0)
            if item and item.widget():
                widget = item.widget()
                if isinstance(widget, PirateAddonCard):
                    # Проверяем что карточка имеет правильный режим
                    if widget.two_column_mode == self.is_pirate_two_column_mode:
                        existing_cards[str(widget.addon_data['path'])] = widget
                    else:
                        # Удаляем карточку с неправильным режимом
                        widget.deleteLater()
        
        # Добавляем карточки в новом порядке (создаем только новые)
        for i, addon_data in enumerate(sorted_addons):
            path_key = str(addon_data['path'])
            if path_key in existing_cards:
                # Используем существующую карточку (с правильным режимом)
                card = existing_cards[path_key]
            else:
                # Создаем новую карточку с текущим режимом
                card = self.create_pirate_addon_card(addon_data, i)
            
            # Добавляем в layout в зависимости от режима
            if self.is_pirate_two_column_mode:
                # Режим 2 столбца - используем GridLayout
                row = i // 2
                col = i % 2
                self.pirate_addons_layout.addWidget(card, row, col)
            else:
                # Режим 1 столбец - используем VBoxLayout
                self.pirate_addons_layout.insertWidget(i, card)
        
        # Добавляем растяжку в конец для GridLayout
        if self.is_pirate_two_column_mode:
            last_row = (len(sorted_addons) - 1) // 2 + 1
            self.pirate_addons_layout.setRowStretch(last_row, 1)
        
        enabled_count = sum(1 for a in self.pirate_addons_data if a['enabled'])
        print(f"🏴‍☠️ Pirate scan completed: {len(self.pirate_addons_data)} addons found ({enabled_count} enabled)")
        self.set_counter_text(self.pirate_counter, get_text("addons_counter", total=len(self.pirate_addons_data), enabled=enabled_count), 22)
    
    def toggle_pirate_addon(self, addon_data, new_state):
        """Включает/выключает пиратский аддон через переименование"""
        try:
            file_path = addon_data['path']
            
            # Используем новое состояние из тумблера
            if new_state:
                # Включаем: переименовываем .vpk.disabled -> .vpk
                if file_path.name.endswith('.disabled'):
                    new_path = file_path.parent / file_path.name.replace('.vpk.disabled', '.vpk')
                    file_path.rename(new_path)
                    addon_data['enabled'] = True
                    addon_data['path'] = new_path
            else:
                # Выключаем: переименовываем .vpk -> .vpk.disabled
                if not file_path.name.endswith('.disabled'):
                    new_path = file_path.parent / f"{file_path.name}.disabled"
                    file_path.rename(new_path)
                    addon_data['enabled'] = False
                    addon_data['path'] = new_path
            
            # Находим карточку и обновляем только индикатор
            for i in range(self.pirate_addons_layout.count()):
                widget = self.pirate_addons_layout.itemAt(i).widget()
                if isinstance(widget, PirateAddonCard) and widget.addon_data == addon_data:
                    # Обновляем индикатор статуса
                    for child in widget.findChildren(QLabel):
                        if child.objectName() == "statusIndicator":
                            color = '#3498db' if addon_data['enabled'] else '#95a5a6'
                            child.setStyleSheet(f"color: {color}; font-size: 16px; background: transparent; border: none;")
                            break
                    break
            
            # Обновляем счетчик
            enabled_count = sum(1 for a in self.pirate_addons_data if a['enabled'])
            self.set_counter_text(self.pirate_counter, get_text("addons_counter", total=len(self.pirate_addons_data), enabled=enabled_count), 22)
            
        except Exception as e:
            QMessageBox.critical(self, get_text("error_title"), get_text("addon_switch_error", error=str(e)))
    
    def delete_pirate_addon(self, vpk_path):
        """Удаляет мод из папки addons/"""
        try:
            # Преобразуем в Path если это строка
            if isinstance(vpk_path, str):
                vpk_path = Path(vpk_path)
            
            # Проверяем что файл существует
            if not vpk_path.exists():
                CustomInfoDialog.information(
                    self, 
                    get_text("error_title"), 
                    get_text("file_not_found", filename=vpk_path.name),
                    icon_type="error"
                )
                return
            
            # Используем кастомный диалог удаления с красной иконкой мусорки
            reply = CustomDeleteDialog.confirm_delete(
                self,
                get_text("confirm_delete_mod"),
                get_text("confirm_delete_message", filename=vpk_path.name)
            )
            
            if reply:
                try:
                    vpk_path.unlink()
                    # Показываем успешное уведомление через CustomInfoDialog с синей галочкой
                    # Используем существующий blur от диалога подтверждения
                    CustomInfoDialog.information(
                        self, 
                        get_text("mod_deleted_title"), 
                        get_text("mod_deleted_message", filename=vpk_path.name),
                        use_existing_blur=True,
                        icon_type="success"
                    )
                    self.scan_pirate_addons()
                except Exception as e:
                    # Показываем ошибку через CustomInfoDialog с синим крестиком
                    # Используем существующий blur от диалога подтверждения
                    CustomInfoDialog.information(
                        self, 
                        get_text("delete_error"), 
                        get_text("delete_error_message", error=str(e)),
                        use_existing_blur=True,
                        icon_type="error"
                    )
        except Exception as e:
            # Ловим любые неожиданные ошибки
            import traceback
            error_details = traceback.format_exc()
            print(f"[ERROR] Unexpected error in delete_pirate_addon: {error_details}")
            CustomInfoDialog.information(
                self, 
                get_text("error_title"), 
                get_text("unexpected_error", error=str(e)),
                icon_type="error"
            )
    
    def open_addons_folder(self):
        """Открывает папку addons в проводнике"""
        if not self.game_folder:
            QMessageBox.warning(self, get_text("error_title"), get_text("specify_game_folder_first"))
            return
        
        addons_path = self.game_folder / "left4dead2" / "addons"
        addons_path.mkdir(parents=True, exist_ok=True)
        
        import subprocess
        subprocess.Popen(f'explorer "{addons_path}"')
    
    def create_pirate_addon_card(self, addon_data, index):
        """Создает карточку для мода из addons/"""
        card = PirateAddonCard(addon_data, index, self, self.is_pirate_two_column_mode)
        return card


    def create_settings_tab(self):
        """Вкладка настроек с анимациями"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(40, 20, 40, 20)
        layout.setSpacing(12)
        
        # Заголовок с иконкой
        title_container = QHBoxLayout()
        title_container.setSpacing(0)  # Уменьшенный отступ между иконкой и текстом
        
        # Загружаем иконку settings.png
        title_icon = QLabel()
        settings_icon_path = Path(__file__).parent / "settings.png"
        if settings_icon_path.exists():
            pixmap = QPixmap(str(settings_icon_path))
            # Перекрашиваем в белый цвет
            painter = QPainter(pixmap)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(pixmap.rect(), QColor(255, 255, 255, 200))
            painter.end()
            
            # Масштабируем до 24x24
            scaled_pixmap = pixmap.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            title_icon.setPixmap(scaled_pixmap)
        title_icon.setFixedSize(24, 24)  # Фиксированный размер для выравнивания
        title_icon.setStyleSheet("margin-top: -9px; padding-top: 9px;")  # Сдвигаем вверх и добавляем padding чтобы не обрезалось
        title_container.addWidget(title_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        
        title = QLabel(get_text("tab_settings"))
        title.setObjectName("sectionTitle")
        title_container.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        title_container.addStretch()  # Stretch остается чтобы прижать к левому краю
        
        layout.addLayout(title_container)
        
        # Карточка: Папка с игрой
        path_card = self.create_settings_card(
            get_text("settings_game_path"),
            get_text("settings_game_path_desc")
        )
        self.path_input = QLineEdit()
        self.path_input.setObjectName("settingsInput")
        self.path_input.setPlaceholderText(get_text("path_placeholder"))
        # Подключаем обновление статуса при изменении текста
        self.path_input.textChanged.connect(self.on_path_changed)
        path_card.layout().addWidget(self.path_input)
        
        browse_btn = QPushButton(get_text("btn_browse_folder"))
        browse_btn.setObjectName("settingsBtn")
        browse_btn.clicked.connect(self.browse_folder)
        path_card.layout().addWidget(browse_btn)
        
        layout.addWidget(path_card)
        self.animate_settings_card(path_card, 0)
        
        # Карточка: Статус файлов
        status_card = self.create_settings_card(
            get_text("settings_file_status"),
            get_text("settings_file_status_desc")
        )
        
        self.gameinfo_status = QLabel(get_text("gameinfo_found"))
        self.gameinfo_status.setObjectName("statusLabel")
        status_card.layout().addWidget(self.gameinfo_status)
        
        self.workshop_status = QLabel(get_text("workshop_found"))
        self.workshop_status.setObjectName("statusLabel")
        status_card.layout().addWidget(self.workshop_status)
        
        layout.addWidget(status_card)
        self.animate_settings_card(status_card, 1)
        

        
        # Карточка: Действия
        actions_card = self.create_settings_card(
            get_text("settings_actions"),
            get_text("settings_actions_desc")
        )
        
        restore_btn = QPushButton(get_text("btn_restore_gameinfo"))
        restore_btn.setObjectName("dangerBtn")
        restore_btn.clicked.connect(self.restore_gameinfo)
        actions_card.layout().addWidget(restore_btn)
        
        layout.addWidget(actions_card)
        self.animate_settings_card(actions_card, 2)
        
        layout.addStretch()
        
        self.stack.addWidget(tab)
    
    def create_settings_card(self, title, subtitle):
        """Создает карточку настроек с анимацией"""
        card = SettingsCard(title, subtitle)
        return card
    
    def animate_settings_card(self, card, index):
        """Анимация появления карточки настроек"""
        # Начинаем с нулевой прозрачности
        card.opacity_effect.setOpacity(0)
        
        # Сохраняем анимацию в карточке чтобы не удалилась сборщиком мусора
        card.fade_anim = QPropertyAnimation(card.opacity_effect, b"opacity")
        card.fade_anim.setDuration(400)
        card.fade_anim.setStartValue(0)
        card.fade_anim.setEndValue(1)
        card.fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        # Принудительно завершаем анимацию через 400ms + задержка
        total_time = (index * 100) + 400
        QTimer.singleShot(total_time, lambda: card.opacity_effect.setOpacity(1))
        
        # Задержка для каскадного эффекта
        QTimer.singleShot(index * 100, card.fade_anim.start)
    
    def handle_contact_link(self, url):
        """Обрабатывает клики по ссылкам в контактах"""
        if url.startswith('mailto:'):
            # Для email - копируем в буфер обмена
            email = url.replace('mailto:', '')
            clipboard = QApplication.clipboard()
            clipboard.setText(email)
            
            # Показываем простое компактное уведомление над курсором
            tooltip = SimpleCopyTooltip(self)
            tooltip.show_at_cursor()
        elif url.startswith('card:'):
            # Для номера карты - копируем в буфер обмена
            card_number = url.replace('card:', '')
            clipboard = QApplication.clipboard()
            clipboard.setText(card_number)
            
            # Показываем простое компактное уведомление над курсором
            tooltip = SimpleCopyTooltip(self)
            tooltip.show_at_cursor()
        else:
            # Для обычных ссылок - открываем в браузере
            import webbrowser
            webbrowser.open(url)
    
    def show_donate_dialog(self):
        """Показывает диалог с информацией о поддержке проекта"""
        CustomInfoDialog.information(
            self,
            get_text("support_title"),
            f'<div style="text-align: center; color: white;">{get_text("support_message")}</div>',
            icon_type="info"
        )
    
    def show_telegram_community_dialog(self):
        """Показывает диалог приглашения в Telegram сообщество"""
        # Создаем кастомный диалог с кнопками
        dialog = TelegramCommunityDialog(self)
        if dialog.exec():
            # Пользователь нажал "Присоединиться"
            import webbrowser
            webbrowser.open("https://t.me/addon_manager")
        # Если нажал "Позже" - ничего не делаем
    
    def check_daily_donate_reminder(self):
        """Показывает напоминание о донатах при каждом запуске"""
        print("🔔 check_daily_donate_reminder called - showing every startup")
        
        # Показываем напоминание при каждом запуске
        print("🔔 Showing donate reminder dialog")
        CustomInfoDialog.information(
            self,
            get_text("daily_reminder_title"),
            f'<div style="text-align: center; color: white;">{get_text("daily_reminder_message")}</div>',
            icon_type="info"
        )
        
        # После напоминания о донатах показываем приглашение в Telegram (с задержкой)
        QTimer.singleShot(300, self.check_telegram_community_invitation)
    
    def check_telegram_community_invitation(self):
        """Показывает приглашение в Telegram сообщество раз в час"""
        print("📱 check_telegram_community_invitation called - once per hour")
        
        import time
        current_time = time.time()
        # 1 час = 3600 секунд
        time_since_last_invitation = current_time - getattr(self, 'last_telegram_invitation', 0)
        print(f"📱 Telegram invitation check: {time_since_last_invitation} seconds since last (need 3600 for 1h)")
        
        # Показываем приглашение если прошло больше часа (или это первый запуск)
        if time_since_last_invitation >= 3600 or not hasattr(self, 'last_telegram_invitation'):
            print("📱 Showing Telegram invitation dialog - once per hour")
            
            # Обновляем время последнего приглашения
            self.last_telegram_invitation = current_time
            self.save_config()
            
            # Показываем диалог приглашения
            dialog = TelegramCommunityDialog(self)
            if dialog.exec():
                # Пользователь нажал "Присоединиться"
                import webbrowser
                webbrowser.open("https://t.me/addon_manager")
        else:
            print(f"📱 Telegram invitation not shown - need to wait {3600 - time_since_last_invitation:.0f} more seconds")
        
        # После всех уведомлений показываем элементы интерфейса
        QTimer.singleShot(200, self.show_interface_after_notifications)
    
    def show_interface_after_notifications(self):
        """Показывает элементы интерфейса после всех уведомлений"""
        print("✅ All notifications shown, displaying interface elements")
        
        # ОКОНЧАТЕЛЬНО РАЗБЛОКИРУЕМ МЫШЬ для главного окна
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        print("✅ Mouse events finally unblocked - interface fully ready")
        
        # Показываем все элементы вкладки
        if hasattr(self, 'tab_header_container'):
            self.tab_header_container.setEnabled(True)  # Разблокируем события мыши
            self.tab_header_container.show()
        
        if hasattr(self, 'controls_container'):
            self.controls_container.setEnabled(True)  # Разблокируем события мыши
            self.controls_container.show()
        
        # Финальная очистка событий
        QApplication.processEvents()
        
        # Включаем анимации обратно
        self.animations_disabled = False
        
        # Дополнительный сброс hover состояний после показа интерфейса
        QTimer.singleShot(200, self.force_reset_card_states)
    
    def reset_notification_timers_for_testing(self):
        """Сбрасывает таймеры уведомлений для тестирования (вызывается через консоль)"""
        print("🔄 Resetting notification timers for testing...")
        self.last_donate_reminder = 0
        self.last_telegram_invitation = 0
        self.save_config()
        print("✅ Notification timers reset. Call check_daily_donate_reminder() to test.")
    
    def force_show_notifications(self):
        """Принудительно показывает уведомления для тестирования"""
        print("🔔 Force showing donate reminder...")
        CustomInfoDialog.information(
            self,
            get_text("daily_reminder_title"),
            f'<div style="text-align: center; color: white;">{get_text("daily_reminder_message")}</div>',
            icon_type="info"
        )
        
        print("📱 Force showing Telegram invitation...")
        QTimer.singleShot(1000, lambda: self._force_show_telegram())
    
    def _force_show_telegram(self):
        """Вспомогательный метод для показа Telegram диалога"""
        dialog = TelegramCommunityDialog(self)
        if dialog.exec():
            import webbrowser
            webbrowser.open("https://t.me/addon_manager")
    
    def browse_folder(self):
        """Выбор папки с анимацией кнопки"""
        # Анимация кнопки
        sender = self.sender()
        if sender:
            self.animate_button_click(sender)
        
        folder = QFileDialog.getExistingDirectory(
            self,
            get_text("select_l4d2_folder"),
            str(Path.home())
        )
        if folder:
            self.path_input.setText(folder)
            self.game_folder = Path(folder)
            self.save_config()
            self.update_status()
    
    def animate_button_click(self, button):
        """Анимация клика по кнопке"""
        # Scale down и up
        anim = QPropertyAnimation(button, b"geometry")
        anim.setDuration(100)
        
        current = button.geometry()
        small = current.adjusted(2, 2, -2, -2)
        
        anim.setStartValue(current)
        anim.setKeyValueAt(0.5, small)
        anim.setEndValue(current)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
    
    def restore_gameinfo(self):
        """Восстановление gameinfo.txt"""
        # Анимация кнопки
        sender = self.sender()
        if sender:
            self.animate_button_click(sender)
        
        # Используем кастомный диалог подтверждения
        reply = CustomConfirmDialog.question(
            self,
            get_text("restore_gameinfo_title"),
            get_text("restore_gameinfo_confirm")
        )
        
        if reply:
            try:
                backup_path = self.gameinfo_path.with_suffix('.txt.backup')
                
                if not backup_path.exists():
                    CustomInfoDialog.information(
                        self, 
                        get_text("backup_not_found_title"), 
                        get_text("backup_not_found_message"),
                        icon_type="error"
                    )
                    return
                
                # Восстанавливаем из бэкапа
                shutil.copy2(backup_path, self.gameinfo_path)
                
                CustomInfoDialog.information(
                    self, 
                    get_text("file_restored_title"), 
                    get_text("file_restored_message"),
                    icon_type="success"
                )
                
                # Обновляем список аддонов
                self.scan_addons()
                
            except Exception as e:
                CustomInfoDialog.information(
                    self, 
                    get_text("restore_error_title"), 
                    get_text("restore_error_message", error=str(e)),
                    icon_type="error"
                )
    
    def on_path_changed(self, text):
        """Обработчик изменения пути"""
        if text:
            self.game_folder = Path(text)
            self.update_paths()
    
    def update_status(self):
        """Обновление статуса файлов"""
        if hasattr(self, 'gameinfo_status'):
            if self.gameinfo_path and self.gameinfo_path.exists():
                self.gameinfo_status.setText(get_text("gameinfo_found"))
                self.gameinfo_status.setStyleSheet("color: #27ae60;")
            else:
                self.gameinfo_status.setText(get_text("gameinfo_not_found"))
                self.gameinfo_status.setStyleSheet("color: #e74c3c;")
            
            if self.workshop_path and self.workshop_path.exists():
                self.workshop_status.setText(get_text("workshop_found"))
                self.workshop_status.setStyleSheet("color: #27ae60;")
            else:
                self.workshop_status.setText(get_text("workshop_not_found"))
                self.workshop_status.setStyleSheet("color: #e74c3c;")
    
    def create_language_tab(self):
        """Вкладка выбора языка"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(40, 20, 40, 20)
        layout.setSpacing(20)
        
        # Заголовок с иконкой
        title_container = QHBoxLayout()
        title_container.setSpacing(10)
        
        # Иконка языка
        title_icon = QLabel()
        lang_icon_path = get_resource_path("lang.png")
        if lang_icon_path.exists():
            pixmap = QPixmap(str(lang_icon_path))
            if not pixmap.isNull():
                # Перекрашиваем в белый цвет
                painter = QPainter(pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(pixmap.rect(), QColor(255, 255, 255, 200))
                painter.end()
                
                # Масштабируем до 24x24
                scaled_pixmap = pixmap.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                title_icon.setPixmap(scaled_pixmap)
        title_icon.setFixedSize(24, 24)
        title_icon.setStyleSheet("margin-top: -9px; padding-top: 9px;")
        title_container.addWidget(title_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        
        title = QLabel(get_text('tab_language'))
        title.setObjectName("sectionTitle")
        title_container.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        title_container.addStretch()
        
        layout.addLayout(title_container)
        
        # Описание
        description = QLabel(
            "Select your preferred interface language. The application will restart to apply changes.\n"
            "Выберите предпочитаемый язык интерфейса. Приложение перезапустится для применения изменений."
        )
        description.setStyleSheet("color: #bdc3c7; font-size: 13px; line-height: 1.5; margin-bottom: 20px;")
        description.setWordWrap(True)
        layout.addWidget(description)
        
        # Кнопки выбора языка
        languages_container = QWidget()
        languages_layout = QVBoxLayout(languages_container)
        languages_layout.setSpacing(15)
        
        # Русский язык
        self.russian_lang_btn = self.create_language_card("🇷🇺", "Русский", "Russian", "ru")
        languages_layout.addWidget(self.russian_lang_btn)
        
        # Английский язык
        self.english_lang_btn = self.create_language_card("🇺🇸", "English", "Английский", "en")
        languages_layout.addWidget(self.english_lang_btn)
        
        layout.addWidget(languages_container)
        layout.addStretch()
        
        self.stack.addWidget(tab)
    
    def create_language_card(self, flag, primary_name, secondary_name, language_code):
        """Создает карточку выбора языка"""
        card = QWidget()
        card.setObjectName("languageCard")
        card.setFixedHeight(80)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Добавляем эффект прозрачности для анимации
        card.opacity_effect = QGraphicsOpacityEffect()
        card.opacity_effect.setOpacity(1)
        card.setGraphicsEffect(card.opacity_effect)
        
        layout = QHBoxLayout(card)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(15)
        
        # Флаг
        flag_label = QLabel(flag)
        flag_label.setStyleSheet("font-size: 32px;")
        flag_label.setFixedSize(50, 50)
        flag_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(flag_label)
        
        # Текст
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        
        primary_label = QLabel(primary_name)
        primary_label.setStyleSheet("font-size: 16px; font-weight: 600; color: white;")
        text_layout.addWidget(primary_label)
        
        secondary_label = QLabel(secondary_name)
        secondary_label.setStyleSheet("font-size: 12px; color: #bdc3c7;")
        text_layout.addWidget(secondary_label)
        
        layout.addLayout(text_layout)
        layout.addStretch()
        
        # Индикатор выбора
        indicator = QLabel("✓" if self.current_language == language_code else "")
        indicator.setStyleSheet("font-size: 20px; color: #3498db; font-weight: bold;")
        indicator.setFixedSize(30, 30)
        indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(indicator)
        
        # Сохраняем ссылки для удобного доступа
        card.language_code = language_code
        card.indicator = indicator
        
        # Обработчик клика
        def on_click():
            self.change_language(language_code)
        
        card.mousePressEvent = lambda event: on_click()
        
        return card
    
    def create_faq_tab(self):
        """Вкладка справки с анимациями"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(15)
        
        # Заголовок с иконкой
        title_container = QHBoxLayout()
        title_container.setSpacing(0)  # Уменьшенный отступ между иконкой и текстом
        
        # Загружаем иконку spravka.png
        title_icon = QLabel()
        spravka_icon_path = Path(__file__).parent / "spravka.png"
        if spravka_icon_path.exists():
            pixmap = QPixmap(str(spravka_icon_path))
            # Перекрашиваем в белый цвет
            painter = QPainter(pixmap)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(pixmap.rect(), QColor(255, 255, 255, 200))
            painter.end()
            
            # Масштабируем до 24x24
            scaled_pixmap = pixmap.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            title_icon.setPixmap(scaled_pixmap)
        title_icon.setFixedSize(24, 24)  # Фиксированный размер для выравнивания
        title_icon.setStyleSheet("margin-top: -9px; padding-top: 9px;")  # Сдвигаем вверх и добавляем padding чтобы не обрезалось
        title_container.addWidget(title_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        
        title = QLabel(get_text("tab_help"))
        title.setObjectName("sectionTitle")
        title_container.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        title_container.addStretch()  # Stretch остается чтобы прижать к левому краю
        
        layout.addLayout(title_container)
        
        # Скролл для FAQ
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("faqScroll")
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(15)
        
        # FAQ карточки
        faqs = [
            (get_text("faq_about_title"), get_text("faq_about_content")),
            (get_text("faq_workshop_title"), get_text("faq_workshop_content")),
            (get_text("faq_pirate_title"), get_text("faq_pirate_content")),
            (get_text("faq_settings_title"), get_text("faq_settings_content")),
            (get_text("faq_gameinfo_title"), get_text("faq_gameinfo_content")),
            (get_text("faq_troubleshooting_title"), get_text("faq_troubleshooting_content")),
            (get_text("faq_safety_title"), get_text("faq_safety_content")),
        ]
        
        for i, (question, answer) in enumerate(faqs):
            card = self.create_faq_card(question, answer)
            scroll_layout.addWidget(card)
            self.animate_settings_card(card, i)
        
        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)
        
        self.stack.addWidget(tab)
    
    def create_faq_card(self, question, answer):
        """Создает FAQ карточку"""
        card = SettingsCard(question, answer)
        
        # Делаем все QLabel с прозрачным фоном
        for widget in card.findChildren(QLabel):
            widget.setAutoFillBackground(False)
            widget.setStyleSheet("background: transparent; border: none;")
            if widget.text() == answer:
                widget.setWordWrap(True)
        
        return card
    
    def create_contacts_tab(self):
        """Вкладка контактов"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(20)
        
        # Заголовок с иконкой
        title_container = QHBoxLayout()
        title_container.setSpacing(0)  # Уменьшенный отступ между иконкой и текстом
        
        # Иконка con.png залитая белым
        icon_label = QLabel()
        icon_path = Path(__file__).parent / "con.png"
        if icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                
                # Перекрашиваем в белый цвет
                colored_pixmap = QPixmap(scaled_pixmap.size())
                colored_pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(colored_pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                painter.drawPixmap(0, 0, scaled_pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(colored_pixmap.rect(), QColor(255, 255, 255))  # Белый цвет
                painter.end()
                
                icon_label.setPixmap(colored_pixmap)
        icon_label.setFixedSize(24, 24)  # Фиксированный размер для выравнивания
        icon_label.setStyleSheet("margin-top: -9px; padding-top: 9px;")  # Сдвигаем вверх и добавляем padding чтобы не обрезалось
        title_container.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
        
        # Текст заголовка
        title = QLabel(get_text("contacts_title"))
        title.setObjectName("sectionTitle")
        title_container.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        title_container.addStretch()
        
        layout.addLayout(title_container)
        
        # Скролл для контента
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("contactsScroll")
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(20)
        
        # Карточка "Нашли баг?"
        bug_card = SettingsCard(
            get_text("contacts_bug_title"),
            get_text("contacts_bug_content")
        )
        scroll_layout.addWidget(bug_card)
        self.animate_settings_card(bug_card, 0)
        
        # Карточка "Поддержать проект"
        donate_card = SettingsCard(
            get_text("contacts_support_title"),
            get_text("contacts_support_content")
        )
        scroll_layout.addWidget(donate_card)
        self.animate_settings_card(donate_card, 1)
        
        # Карточка "Связь с разработчиком"
        contact_card = SettingsCard(
            get_text("contacts_developer_title"),
            get_text("contacts_developer_content")
        )
        scroll_layout.addWidget(contact_card)
        self.animate_settings_card(contact_card, 2)
        
        # Делаем все QLabel с прозрачным фоном и включаем HTML
        for card in [bug_card, donate_card, contact_card]:
            for widget in card.findChildren(QLabel):
                widget.setAutoFillBackground(False)
                widget.setStyleSheet("background: transparent; border: none;")
                widget.setWordWrap(True)
                widget.setTextFormat(Qt.TextFormat.RichText)  # Включаем HTML
                widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse)
                widget.setOpenExternalLinks(False)  # Отключаем автоматическое открытие
                widget.linkActivated.connect(self.handle_contact_link)  # Обрабатываем клики вручную
        
        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)
        
        self.stack.addWidget(tab)
    
    def switch_tab(self, index):
        """Переключение табов с blur + fade анимацией"""
        # Если уже на этой вкладке - ничего не делаем
        if self.stack.currentIndex() == index:
            return
        
        # Обновляем кнопки
        for i, btn in enumerate(self.tab_buttons):
            btn.setChecked(i == index)
        
        # Создаем blur эффект для анимации
        blur_effect = QGraphicsBlurEffect()
        blur_effect.setBlurRadius(0)
        self.stack.setGraphicsEffect(blur_effect)
        
        # Создаем opacity эффект для fade
        opacity_effect = QGraphicsOpacityEffect()
        opacity_effect.setOpacity(1.0)
        current_widget = self.stack.currentWidget()
        if current_widget:
            current_widget.setGraphicsEffect(opacity_effect)
        
        # Анимация blur (появление)
        self.tab_blur_anim = QPropertyAnimation(blur_effect, b"blurRadius")
        self.tab_blur_anim.setDuration(200)
        self.tab_blur_anim.setStartValue(0)
        self.tab_blur_anim.setEndValue(15)
        self.tab_blur_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        # Анимация fade (затухание)
        self.tab_fade_anim = QPropertyAnimation(opacity_effect, b"opacity")
        self.tab_fade_anim.setDuration(200)
        self.tab_fade_anim.setStartValue(1.0)
        self.tab_fade_anim.setEndValue(0.0)
        self.tab_fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        # Когда анимации завершились - переключаем вкладку
        self.tab_fade_anim.finished.connect(lambda: self.finish_tab_switch(index))
        
        # Запускаем обе анимации одновременно
        self.tab_blur_anim.start()
        self.tab_fade_anim.start()
    
    def finish_tab_switch(self, index):
        """Завершает переключение вкладки с fade-in эффектом"""
        # Переключаем вкладку
        self.stack.setCurrentIndex(index)
        
        # Создаем opacity эффект для новой вкладки
        new_widget = self.stack.currentWidget()
        if new_widget:
            opacity_effect = QGraphicsOpacityEffect()
            opacity_effect.setOpacity(0.0)
            new_widget.setGraphicsEffect(opacity_effect)
            
            # Анимация fade-in (появление)
            self.tab_fade_in_anim = QPropertyAnimation(opacity_effect, b"opacity")
            self.tab_fade_in_anim.setDuration(200)
            self.tab_fade_in_anim.setStartValue(0.0)
            self.tab_fade_in_anim.setEndValue(1.0)
            self.tab_fade_in_anim.setEasingCurve(QEasingCurve.Type.InCubic)
            self.tab_fade_in_anim.finished.connect(lambda: self.cleanup_tab_effects())
            self.tab_fade_in_anim.start()
        
        # Анимация убирания blur
        blur_effect = self.stack.graphicsEffect()
        if blur_effect and isinstance(blur_effect, QGraphicsBlurEffect):
            self.tab_blur_out_anim = QPropertyAnimation(blur_effect, b"blurRadius")
            self.tab_blur_out_anim.setDuration(200)
            self.tab_blur_out_anim.setStartValue(15)
            self.tab_blur_out_anim.setEndValue(0)
            self.tab_blur_out_anim.setEasingCurve(QEasingCurve.Type.InCubic)
            self.tab_blur_out_anim.start()
    
    def cleanup_tab_effects(self):
        """Очищает графические эффекты после переключения вкладки"""
        # Убираем blur эффект
        self.stack.setGraphicsEffect(None)
        
        # Убираем графические эффекты с текущей вкладки и всех её дочерних элементов
        current_widget = self.stack.currentWidget()
        if current_widget:
            try:
                # Убираем эффект с самой вкладки
                current_widget.setGraphicsEffect(None)
                
                # Убираем эффекты со всех контейнеров
                for container in current_widget.findChildren(QWidget):
                    if container.graphicsEffect():
                        container.setGraphicsEffect(None)
                
                # Убираем эффекты с карточек (только если они есть)
                try:
                    for card in current_widget.findChildren(AnimatedCard):
                        if card.graphicsEffect():
                            card.setGraphicsEffect(None)
                except:
                    pass
                
                try:
                    for card in current_widget.findChildren(PirateAddonCard):
                        if card.graphicsEffect():
                            card.setGraphicsEffect(None)
                except:
                    pass
                
                # Принудительно устанавливаем полную прозрачность для всех SettingsCard
                for card in current_widget.findChildren(SettingsCard):
                    if hasattr(card, 'opacity_effect') and card.opacity_effect:
                        card.opacity_effect.setOpacity(1)
            except Exception as e:
                print(f"Ошибка при переключении вкладки: {e}")
    
    def show_welcome(self):
        """Показывает диалог выбора языка (если нужно) и welcome dialog"""
        # Сначала показываем диалог выбора языка при первом запуске
        if hasattr(self, 'needs_language_selection') and self.needs_language_selection:
            print("🌍 Showing language selection dialog before welcome")
            selected_language = show_language_selection_dialog(self)
            
            # Применяем выбранный язык
            print(f"🌍 Setting language to: {selected_language}")
            set_language(selected_language)
            self.current_language = selected_language
            
            # Сохраняем выбранный язык
            print(f"🌍 Saving language preference...")
            save_language_preference(CONFIG_FILE)
            
            # КРИТИЧНО: Пересоздаём весь UI с новым языком
            print(f"🌍 Recreating UI with new language...")
            self.recreate_ui_with_language()
            
            self.needs_language_selection = False
            print(f"🌍 Language selected and saved: {selected_language}")
            
            # Проверяем, что язык действительно установлен
            from localization import get_text
            print(f"🌍 Test translation: tab_addons = '{get_text('tab_addons')}'")
            print(f"🌍 Test translation: tab_settings = '{get_text('tab_settings')}'")
            print(f"🌍 Test translation: btn_support_project = '{get_text('btn_support_project')}'")
        
        # Затем показываем welcome dialog
        # Оставляем blur после закрытия для плавного перехода к уведомлению
        dialog = BlurDialog(self, keep_blur_on_close=True)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Проверяем путь к игре после приветствия
            if not self.validate_game_path():
                self.prompt_game_folder()
            else:
                # Обеспечиваем правильную загрузку аддонов после выбора языка
                print("🌍 Starting addon scan with selected language...")
                self.scan_addons()
            
            # Напоминание о донатах теперь показывается после загрузки аддонов
        else:
            # Если пользователь отменил, убираем blur
            self.setGraphicsEffect(None)
    
    def recreate_ui_with_language(self):
        """Пересоздаёт весь UI с новым языком"""
        try:
            print("🌍 Recreating UI...")
            
            # Удаляем старый центральный виджет
            old_widget = self.centralWidget()
            if old_widget:
                old_widget.deleteLater()
            
            # Пересоздаём UI
            self.setup_ui()
            self.apply_dark_styles()
            
            # Обновляем пути если они были установлены
            if hasattr(self, 'game_folder') and self.game_folder:
                self.update_paths()
            
            print("🌍 UI recreated successfully")
            
        except Exception as e:
            print(f"❌ Error recreating UI: {e}")
            import traceback
            traceback.print_exc()
    
    def update_ui_language(self):
        """Обновляет язык интерфейса"""
        try:
            print(f"🌍 Starting comprehensive UI language update...")
            
            # Обновляем заголовок окна
            new_title = get_text("app_title")
            print(f"🌍 Setting window title to: '{new_title}'")
            self.setWindowTitle(new_title)
            
            # Обновляем текст вкладок
            if hasattr(self, 'tab_buttons') and self.tab_buttons:
                print(f"🌍 Found {len(self.tab_buttons)} tab buttons")
                tab_texts = [
                    get_text("tab_addons"),
                    get_text("tab_pirate_addons"), 
                    get_text("tab_settings"),
                    get_text("tab_language"),
                    get_text("tab_help"),
                    get_text("tab_contacts")
                ]
                
                print(f"🌍 Tab texts: {tab_texts}")
                
                for i, btn in enumerate(self.tab_buttons):
                    if i < len(tab_texts):
                        old_text = btn.text()
                        btn.setText(tab_texts[i])
                        print(f"🌍 Tab {i}: '{old_text}' -> '{tab_texts[i]}'")
            else:
                print("🌍 No tab buttons found!")
            
            # Обновляем заголовки кнопок в хедере
            if hasattr(self, 'donate_btn'):
                new_text = get_text("btn_support_project")
                print(f"🌍 Setting donate button to: '{new_text}'")
                self.donate_btn.setText(new_text)
            if hasattr(self, 'update_btn'):
                new_text = get_text("btn_updates")
                print(f"🌍 Setting update button to: '{new_text}'")
                self.update_btn.setText(new_text)
            if hasattr(self, 'github_btn'):
                print(f"🌍 Setting GitHub button to: 'GitHub'")
                self.github_btn.setText("GitHub")
            
            # Обновляем все кнопки управления
            if hasattr(self, 'enable_all_btn'):
                self.enable_all_btn.setText(get_text("btn_enable_all"))
                print(f"🌍 Updated enable_all_btn")
            if hasattr(self, 'disable_all_btn'):
                self.disable_all_btn.setText(get_text("btn_disable_all"))
                print(f"🌍 Updated disable_all_btn")
            if hasattr(self, 'refresh_btn'):
                self.refresh_btn.setText(get_text("btn_refresh"))
                print(f"🌍 Updated refresh_btn")
            
            # Обновляем поисковые поля
            if hasattr(self, 'search_input'):
                self.search_input.setPlaceholderText(get_text("search_placeholder"))
                print(f"🌍 Updated main search placeholder")
            if hasattr(self, 'pirate_search_input'):
                self.pirate_search_input.setPlaceholderText(get_text("search_placeholder"))
                print(f"🌍 Updated pirate search placeholder")
            
            # Обновляем описания вкладок
            if hasattr(self, 'addons_description'):
                self.addons_description.setText(get_text("addons_description_full"))
                print(f"🌍 Updated addons description")
            if hasattr(self, 'pirate_description'):
                self.pirate_description.setText(get_text("pirate_addons_description_full"))
                print(f"🌍 Updated pirate description")
            
            # Обновляем счетчики аддонов
            if hasattr(self, 'addons') and self.addons:
                enabled_count = sum(1 for a in self.addons if a.get('enabled'))
                counter_text = get_text("addons_counter", total=len(self.addons), enabled=enabled_count)
                print(f"🌍 Setting main counter to: '{counter_text}'")
                self.set_counter_text(self.counter, counter_text)
            
            if hasattr(self, 'pirate_addons_data') and self.pirate_addons_data:
                enabled_count = sum(1 for a in self.pirate_addons_data if a['enabled'])
                counter_text = get_text("addons_counter", total=len(self.pirate_addons_data), enabled=enabled_count)
                print(f"🌍 Setting pirate counter to: '{counter_text}'")
                self.set_counter_text(self.pirate_counter, counter_text, 22)
            
            # Обновляем все кнопки на пиратской вкладке
            if hasattr(self, 'add_vpk_btn'):
                self.add_vpk_btn.setText(get_text("btn_add_vpk"))
                print(f"🌍 Updated add_vpk_btn")
            if hasattr(self, 'workshop_btn'):
                self.workshop_btn.setText(get_text("download_from_workshop"))
                print(f"🌍 Updated workshop_btn")
            
            # Принудительно обновляем все видимые элементы
            self.repaint()
            if hasattr(self, 'stack'):
                self.stack.repaint()
            
            print(f"🌍 Comprehensive UI language update completed for: {self.current_language}")
            
        except Exception as e:
            print(f"❌ Error updating UI language: {e}")
            import traceback
            traceback.print_exc()
    
    def update_ui_language_delayed(self):
        """Отложенное обновление языка интерфейса после завершения всех диалогов"""
        print(f"🌍 Delayed UI language update...")
        
        # Обновляем основной интерфейс
        self.update_ui_language()
        
        # Обновляем все вкладки и их содержимое
        self.update_all_tabs_content()
        
        # Обновляем все карточки аддонов с новым языком
        if hasattr(self, 'addons') and self.addons:
            try:
                self.refresh_cards()
                print("🌍 Cards refreshed with new language")
            except Exception as e:
                print(f"❌ Error refreshing cards: {e}")
        
        # Обновляем карточки пиратских аддонов
        if hasattr(self, 'pirate_addons_data') and self.pirate_addons_data:
            try:
                self.refresh_pirate_cards()
                print("🌍 Pirate cards refreshed with new language")
            except Exception as e:
                print(f"❌ Error refreshing pirate cards: {e}")
        
        # Принудительно обновляем все видимые элементы
        self.repaint()
        if hasattr(self, 'stack'):
            self.stack.repaint()
        
        # Обновляем все дочерние виджеты
        for widget in self.findChildren(QWidget):
            widget.repaint()
        
        print(f"🌍 Delayed update completed")
    
    def update_all_tabs_content(self):
        """Обновляет содержимое всех вкладок с новым языком"""
        try:
            print("🌍 Updating all tabs content...")
            
            # Обновляем описания вкладок
            if hasattr(self, 'addons_description'):
                self.addons_description.setText(get_text("addons_description_full"))
                print("🌍 Updated addons_description")
            
            if hasattr(self, 'pirate_description'):
                self.pirate_description.setText(get_text("pirate_addons_description_full"))
                print("🌍 Updated pirate_description")
            
            # Обновляем все кнопки управления
            if hasattr(self, 'enable_all_btn'):
                self.enable_all_btn.setText(get_text("btn_enable_all"))
                print("🌍 Updated enable_all_btn")
            if hasattr(self, 'disable_all_btn'):
                self.disable_all_btn.setText(get_text("btn_disable_all"))
                print("🌍 Updated disable_all_btn")
            if hasattr(self, 'refresh_btn'):
                self.refresh_btn.setText(get_text("btn_refresh"))
                print("🌍 Updated refresh_btn")
            
            # Обновляем кнопки пиратской вкладки
            if hasattr(self, 'add_vpk_btn'):
                self.add_vpk_btn.setText(get_text("btn_add_vpk"))
                print("🌍 Updated add_vpk_btn")
            if hasattr(self, 'workshop_btn'):
                self.workshop_btn.setText(get_text("download_from_workshop"))
                print("🌍 Updated workshop_btn")
            if hasattr(self, 'pirate_enable_all_btn'):
                self.pirate_enable_all_btn.setText(get_text("btn_enable_all"))
                print("🌍 Updated pirate_enable_all_btn")
            if hasattr(self, 'pirate_disable_all_btn'):
                self.pirate_disable_all_btn.setText(get_text("btn_disable_all"))
                print("🌍 Updated pirate_disable_all_btn")
            if hasattr(self, 'pirate_refresh_btn'):
                self.pirate_refresh_btn.setText(get_text("btn_refresh"))
                print("🌍 Updated pirate_refresh_btn")
            
            # Обновляем поисковые поля
            if hasattr(self, 'search_input'):
                self.search_input.setPlaceholderText(get_text("search_placeholder"))
                print("🌍 Updated search_input placeholder")
            if hasattr(self, 'pirate_search_input'):
                self.pirate_search_input.setPlaceholderText(get_text("search_placeholder"))
                print("🌍 Updated pirate_search_input placeholder")
            
            # Обновляем настройки
            if hasattr(self, 'game_path_label'):
                self.game_path_label.setText(get_text("settings_game_path"))
                print("🌍 Updated game_path_label")
            if hasattr(self, 'browse_btn'):
                self.browse_btn.setText(get_text("btn_browse_folder"))
                print("🌍 Updated browse_btn")
            if hasattr(self, 'restore_btn'):
                self.restore_btn.setText(get_text("btn_restore_gameinfo"))
                print("🌍 Updated restore_btn")
            
            # Обновляем статусы файлов
            if hasattr(self, 'gameinfo_status'):
                if hasattr(self, 'game_path') and self.game_path:
                    gameinfo_path = self.game_path / "left4dead2" / "gameinfo.txt"
                    if gameinfo_path.exists():
                        self.gameinfo_status.setText(get_text("status_gameinfo_found"))
                    else:
                        self.gameinfo_status.setText(get_text("status_gameinfo_not_found"))
                print("🌍 Updated gameinfo_status")
            
            if hasattr(self, 'workshop_status'):
                if hasattr(self, 'game_path') and self.game_path:
                    workshop_path = self.game_path / "steamapps" / "workshop" / "content" / "550"
                    if workshop_path.exists():
                        self.workshop_status.setText(get_text("status_workshop_found"))
                    else:
                        self.workshop_status.setText(get_text("status_workshop_not_found"))
                print("🌍 Updated workshop_status")
            
            print("🌍 All tabs content updated successfully")
            
        except Exception as e:
            print(f"❌ Error updating tabs content: {e}")
            import traceback
            traceback.print_exc()
    

    
    def show_language_menu(self):
        """Показывает меню выбора языка"""
        try:
            # Создаем контекстное меню
            menu = QMenu(self)
            menu.setStyleSheet("""
                QMenu {
                    background: #2a2a2a;
                    border: 2px solid #3498db;
                    border-radius: 8px;
                    padding: 5px;
                }
                QMenu::item {
                    background: transparent;
                    color: white;
                    padding: 8px 20px;
                    border-radius: 4px;
                    font-size: 13px;
                }
                QMenu::item:selected {
                    background: #3498db;
                }
                QMenu::item:checked {
                    background: #2980b9;
                    font-weight: bold;
                }
            """)
            
            # Русский язык
            russian_action = menu.addAction("🇷🇺 Русский")
            russian_action.setCheckable(True)
            russian_action.setChecked(self.current_language == "ru")
            russian_action.triggered.connect(lambda: self.change_language("ru"))
            
            # Английский язык
            english_action = menu.addAction("🇺🇸 English")
            english_action.setCheckable(True)
            english_action.setChecked(self.current_language == "en")
            english_action.triggered.connect(lambda: self.change_language("en"))
            
            # Показываем меню под кнопкой
            button = self.sender()
            menu.exec(button.mapToGlobal(QPoint(0, button.height())))
            
        except Exception as e:
            print(f"❌ Error showing language menu: {e}")
    
    def change_language(self, language_code):
        """Изменяет язык интерфейса"""
        try:
            if language_code == self.current_language:
                return  # Язык уже установлен
            
            # Устанавливаем новый язык
            set_language(language_code)
            old_language = self.current_language
            self.current_language = language_code
            
            # Сохраняем в конфиг
            save_language_preference(CONFIG_FILE)
            
            # Обновляем индикаторы на карточках языка
            self.update_language_indicators()
            
            print(f"🌍 Language changed to: {language_code}")
            
            # Обновляем интерфейс без перезапуска
            print(f"🌍 Updating interface to new language: {language_code}")
            self.update_ui_language()
            self.update_all_tabs_content()
            
            # Планируем дополнительное обновление
            QTimer.singleShot(500, self.update_ui_language_delayed)
            
            # Показываем уведомление об успешной смене языка
            language_name = "English" if language_code == "en" else "Русский"
            QTimer.singleShot(1000, lambda: self.show_language_changed_notification(language_name))
            
        except Exception as e:
            print(f"❌ Error changing language: {e}")
    
    def show_language_changed_notification(self, language_name):
        """Показывает уведомление об успешной смене языка"""
        try:
            # Создаем простое уведомление
            from l4d2_pyqt_main import CustomInfoDialog
            
            message = f"Language successfully changed to {language_name}!" if self.current_language == "en" else f"Язык успешно изменен на {language_name}!"
            title = "Language Changed" if self.current_language == "en" else "Язык изменен"
            
            dialog = CustomInfoDialog(self)
            dialog.set_content(
                title,
                message,
                "information"
            )
            
            # Автоматически закрываем через 2 секунды
            QTimer.singleShot(2000, dialog.accept)
            
            dialog.exec()
            
        except Exception as e:
            print(f"❌ Error showing language notification: {e}")
    
    def force_quit(self):
        """Принудительно закрывает приложение"""
        try:
            print("🔄 Force quitting application...")
            
            # Закрываем все окна
            for widget in QApplication.topLevelWidgets():
                widget.close()
            
            # Завершаем приложение
            QApplication.instance().quit()
            
            # Если это не помогло, используем sys.exit
            import sys
            sys.exit(0)
            
        except Exception as e:
            print(f"❌ Error force quitting: {e}")
            import sys
            sys.exit(1)
    
    def update_language_indicators(self):
        """Обновляет индикаторы выбранного языка"""
        try:
            # Обновляем индикаторы на карточках языка
            if hasattr(self, 'russian_lang_btn') and hasattr(self, 'english_lang_btn'):
                for card in [self.russian_lang_btn, self.english_lang_btn]:
                    if hasattr(card, 'language_code') and hasattr(card, 'indicator'):
                        # Показываем галочку только для текущего языка
                        is_current = card.language_code == self.current_language
                        card.indicator.setText("✓" if is_current else "")
                        print(f"🔄 Updated indicator for {card.language_code}: {'✓' if is_current else 'empty'}")
        except Exception as e:
            print(f"❌ Error updating language indicators: {e}")
    
    def show_animation_warning(self):
        """Показывает уведомление о возможных визуальных багах раз в час"""
        # РАЗБЛОКИРУЕМ МЫШЬ когда показываем первое уведомление
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        print("✅ Mouse events unblocked for main window - notifications starting")
        
        # Проверяем что диалог загрузки точно закрыт
        if hasattr(self, 'loading_dialog') and self.loading_dialog:
            # Если диалог загрузки еще открыт, отложим показ уведомления
            print("⏳ Loading dialog still open, delaying animation warning...")
            QTimer.singleShot(300, self.show_animation_warning)
            return
        
        import time
        current_time = time.time()
        # 1 час = 3600 секунд
        time_since_last_warning = current_time - getattr(self, 'last_animation_warning', 0)
        print(f"ℹ️ Animation warning check: {time_since_last_warning} seconds since last (need 3600 for 1h)")
        
        # Показываем предупреждение если прошло больше часа (или это первый запуск)
        if time_since_last_warning >= 3600 or not hasattr(self, 'last_animation_warning'):
            print("ℹ️ Showing animation warning dialog - once per hour")
            
            # Обновляем время последнего предупреждения
            self.last_animation_warning = current_time
            self.save_config()
            
            # Показываем кастомный информационный диалог БЕЗ использования существующего blur
            CustomInfoDialog.information(
                self,
                get_text("information_title"),
                get_text("interface_info_message"),
                use_existing_blur=False,  # НЕ используем существующий blur
                icon_type="info"
            )
        else:
            print(f"ℹ️ Animation warning not shown - need to wait {3600 - time_since_last_warning:.0f} more seconds")
        
        # После проверки предупреждения об анимациях запускаем цепочку остальных уведомлений
        QTimer.singleShot(200, self.check_daily_donate_reminder)
    

    
    def validate_game_path(self):
        """Проверяет корректность пути к игре"""
        if not self.game_folder:
            return False
        
        # Проверяем что папка существует
        if not self.game_folder.exists():
            return False
        
        # Проверяем что это действительно папка L4D2 (есть gameinfo.txt)
        gameinfo = self.game_folder / "left4dead2" / "gameinfo.txt"
        if not gameinfo.exists():
            return False
        
        return True
    
    def prompt_game_folder(self):
        """Предлагает указать папку с игрой"""
        # Это первый запуск - нужно показать уведомление после загрузки
        self.first_launch = True
        
        dialog = SetupDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # scan_addons() уже вызывается в SetupDialog через таймер
            # Не вызываем здесь чтобы избежать дублирования
            pass
    
    def check_gameinfo_sync(self):
        """Проверяет синхронизацию между файлами/папками и gameinfo.txt"""
        if not self.addons:
            return
        
        # Получаем аддоны из gameinfo
        addons_in_gameinfo = self.get_enabled_addons()
        
        # Ищем аддоны которые есть (vpk + папка) но не в gameinfo
        missing_in_gameinfo = []
        for addon in self.addons:
            if addon['enabled'] and addon['id'] not in addons_in_gameinfo:
                missing_in_gameinfo.append(addon['id'])
        
        # Показываем уведомление если есть проблемы
        if missing_in_gameinfo:
            msg = QMessageBox(self)
            msg.setWindowTitle(get_text("attention_title"))
            msg.setText(
                get_text("missing_gameinfo_message", 
                    count=len(missing_in_gameinfo),
                    ids=', '.join(missing_in_gameinfo[:5]),
                    more='...' if len(missing_in_gameinfo) > 5 else ''
                )
            )
            msg.setIcon(QMessageBox.Icon.Warning)
            
            # Кнопки
            btn_force = msg.addButton(get_text("force_add_button"), QMessageBox.ButtonRole.ActionRole)
            btn_ok = msg.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
            
            msg.exec()
            clicked = msg.clickedButton()
            
            # Если выбрано "Внести принудительно"
            if clicked == btn_force:
                self.force_add_to_gameinfo(missing_in_gameinfo)
    
    def force_add_to_gameinfo(self, addon_ids):
        """Принудительно добавляет аддоны в gameinfo.txt"""
        if not addon_ids:
            return
        
        # Показываем прогресс
        progress = QProgressDialog("Добавление в gameinfo.txt...", "Отмена", 0, len(addon_ids), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        
        success_count = 0
        for i, addon_id in enumerate(addon_ids):
            if progress.wasCanceled():
                break
            
            progress.setValue(i)
            progress.setLabelText(get_text("adding_addon", addon_id=addon_id))
            QApplication.processEvents()
            
            try:
                self.add_to_gameinfo(addon_id)
                success_count += 1
            except Exception as e:
                print(f"Ошибка добавления {addon_id}: {e}")
        
        progress.setValue(len(addon_ids))
        
        QMessageBox.information(
            self,
            get_text("ready_title"),
            get_text("added_to_gameinfo", success=success_count, total=len(addon_ids))
        )
    
    def show_no_addons_message(self):
        """Показывает сообщение когда нет аддонов"""
        # Убираем блюр если есть
        self.setGraphicsEffect(None)
        
        # Полностью очищаем контейнер аддонов (включая stretch)
        while self.addons_layout.count() > 0:
            item = self.addons_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.spacerItem():
                # Удаляем spacer
                pass
        
        # Создаем виджет с сообщением
        no_addons_widget = QWidget()
        no_addons_layout = QVBoxLayout(no_addons_widget)
        no_addons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        no_addons_layout.setSpacing(15)
        no_addons_layout.setContentsMargins(0, 50, 0, 0)  # Добавляем отступ сверху
        
        # Иконка noadd.png (маленькая)
        icon_label = QLabel()
        icon_path = Path(__file__).parent / "noadd.png"
        if icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                # Масштабируем до 100x100
                scaled_pixmap = pixmap.scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                
                # Перекрашиваем в синий цвет #3498db
                blue_pixmap = QPixmap(scaled_pixmap.size())
                blue_pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(blue_pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                painter.drawPixmap(0, 0, scaled_pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(blue_pixmap.rect(), QColor(52, 152, 219))  # #3498db
                painter.end()
                
                icon_label.setPixmap(blue_pixmap)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        no_addons_layout.addWidget(icon_label)
        
        # Заголовок
        title_label = QLabel(get_text("no_addons_found"))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 18px; font-weight: 600; color: #d0d0d0;")
        no_addons_layout.addWidget(title_label)
        
        # Описание (минимум текста)
        desc_label = QLabel(
            get_text("workshop_no_addons_desc")
        )
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("font-size: 13px; color: #a0a0a0; line-height: 1.4;")
        no_addons_layout.addWidget(desc_label)
        
        # Кнопки
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(15)
        buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Кнопка обновления
        refresh_btn = AnimatedActionButton(get_text("btn_refresh_list"), "#3498db")
        refresh_btn.setFixedSize(180, 50)
        refresh_btn.clicked.connect(self.scan_addons)
        buttons_layout.addWidget(refresh_btn)
        
        # Кнопка "Что делать?"
        help_btn = AnimatedActionButton(get_text("btn_what_to_do"), "#95a5a6")
        help_btn.setFixedSize(180, 50)
        help_btn.clicked.connect(self.show_no_addons_help)
        buttons_layout.addWidget(help_btn)
        
        no_addons_layout.addLayout(buttons_layout)
        
        # Добавляем виджет в layout
        self.addons_layout.addWidget(no_addons_widget)
        self.addons_layout.addStretch()  # Добавляем stretch в конец
        
        # Показываем контейнер и счетчик
        self.addons_container.show()
        self.addons_container.setEnabled(True)
        self.set_counter_text(self.counter, get_text("addons_counter", total=0, enabled=0))
        self.counter.show()
    
    def show_no_pirate_addons_message(self):
        """Показывает сообщение когда нет пиратских аддонов"""
        # Убираем блюр если есть
        self.setGraphicsEffect(None)
        
        # Полностью очищаем контейнер аддонов (включая stretch)
        while self.pirate_addons_layout.count() > 0:
            item = self.pirate_addons_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.spacerItem():
                # Удаляем spacer
                pass
        
        # Создаем виджет с сообщением
        no_addons_widget = QWidget()
        no_addons_layout = QVBoxLayout(no_addons_widget)
        no_addons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        no_addons_layout.setSpacing(15)
        no_addons_layout.setContentsMargins(0, 50, 0, 0)  # Добавляем отступ сверху
        
        # Иконка noadd.png
        icon_label = QLabel()
        icon_path = Path(__file__).parent / "noadd.png"
        if icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                # Масштабируем до 90x90 (меньше чтобы оставить место для padding)
                scaled_pixmap = pixmap.scaled(90, 90, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                
                # Создаем новый pixmap с padding (110x110 с иконкой 90x90 внутри)
                padded_size = 110
                padding = (padded_size - scaled_pixmap.width()) // 2
                
                padded_pixmap = QPixmap(padded_size, padded_size)
                padded_pixmap.fill(Qt.GlobalColor.transparent)
                
                painter = QPainter(padded_pixmap)
                painter.drawPixmap(padding, padding, scaled_pixmap)
                painter.end()
                
                # Перекрашиваем в синий цвет #3498db
                blue_pixmap = QPixmap(padded_pixmap.size())
                blue_pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(blue_pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                painter.drawPixmap(0, 0, padded_pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(blue_pixmap.rect(), QColor(52, 152, 219))  # #3498db
                painter.end()
                
                icon_label.setPixmap(blue_pixmap)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        no_addons_layout.addWidget(icon_label)
        
        # Заголовок
        title_label = QLabel(get_text("no_addons_found"))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 18px; font-weight: 600; color: #d0d0d0;")
        no_addons_layout.addWidget(title_label)
        
        # Описание (минимум текста)
        desc_label = QLabel(
            get_text("addons_no_mods_desc")
        )
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("font-size: 13px; color: #a0a0a0; line-height: 1.4;")
        no_addons_layout.addWidget(desc_label)
        
        # Кнопки
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(15)
        buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Кнопка обновления
        refresh_btn = AnimatedActionButton(get_text("btn_refresh_list"), "#3498db")
        refresh_btn.setFixedSize(180, 50)
        refresh_btn.clicked.connect(self.scan_pirate_addons)
        buttons_layout.addWidget(refresh_btn)
        
        # Кнопка "Что делать?"
        help_btn = AnimatedActionButton(get_text("btn_what_to_do"), "#95a5a6")
        help_btn.setFixedSize(180, 50)
        help_btn.clicked.connect(self.show_no_pirate_addons_help)
        buttons_layout.addWidget(help_btn)
        
        no_addons_layout.addLayout(buttons_layout)
        
        # Добавляем виджет в layout
        self.pirate_addons_layout.addWidget(no_addons_widget)
        self.pirate_addons_layout.addStretch()  # Добавляем stretch в конец
        
        # Показываем контейнер и счетчик
        self.pirate_addons_container.show()
        self.pirate_addons_container.setEnabled(True)
        self.set_counter_text(self.pirate_counter, get_text("addons_counter", total=0, enabled=0), 22)
        self.pirate_counter.show()
    
    def show_no_pirate_addons_help(self):
        """Показывает подробную информацию о том, что делать когда нет пиратских аддонов"""
        # Убираем букву диска из пути
        addons_path = self.game_folder / "left4dead2" / "addons"
        addons_path_str = str(addons_path)
        if len(addons_path_str) > 2 and addons_path_str[1] == ':':
            addons_path_str = addons_path_str[2:]
        
        CustomInfoDialog.information(
            self,
            get_text("no_pirate_addons_help_title"),
            get_text("no_pirate_addons_help_message", path=addons_path_str),
            use_existing_blur=False,
            icon_type="info"
        )
    
    def show_no_addons_help(self):
        """Показывает подробную информацию о том, что делать когда нет аддонов"""
        # Убираем букву диска из пути
        workshop_path_str = str(self.workshop_path)
        if len(workshop_path_str) > 2 and workshop_path_str[1] == ':':
            workshop_path_str = workshop_path_str[2:]
        
        CustomInfoDialog.information(
            self,
            get_text("no_addons_help_title"),
            get_text("no_addons_help_message", path=workshop_path_str)
        )
    
    def scan_addons(self):
        """Сканирует аддоны из workshop (оптимизированная версия с потоками)"""
        # Защита от повторного запуска
        if hasattr(self, 'loading_dialog') and self.loading_dialog:
            print("⚠️ Scan already in progress, ignoring duplicate call")
            return
        
        print(f"🔍 Starting scan with paths:")
        print(f"   game_folder: {self.game_folder}")
        print(f"   workshop_path: {self.workshop_path}")
        
        if not self.game_folder or not self.workshop_path:
            print("❌ Missing paths, cannot scan")
            self.set_counter_text(self.counter, get_text("configure_game_path"))
            return
            
        if not self.workshop_path.exists():
            print(f"❌ Workshop path does not exist: {self.workshop_path}")
            self.set_counter_text(self.counter, get_text("workshop_folder_not_found", path=self.workshop_path))
            return
        
        # Скрываем ВСЕ элементы вкладки во время загрузки
        self.tab_header_container.hide()
        self.tab_header_container.setEnabled(False)
        self.controls_container.hide()
        self.controls_container.setEnabled(False)
        
        # Показываем диалог загрузки
        self.loading_dialog = LoadingDialog(self, keep_blur_on_close=self.first_launch)
        self.loading_dialog.show()
        
        # Таймер принудительного закрытия диалога (на случай зависания)
        self.loading_timeout_timer = QTimer()
        self.loading_timeout_timer.setSingleShot(True)
        self.loading_timeout_timer.timeout.connect(self.on_loading_finished)
        self.loading_timeout_timer.start(30000)  # 30 секунд максимум
        
        # Очищаем старые данные
        while self.addons_layout.count() > 1:
            item = self.addons_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self.addons = []
        self.set_counter_text(self.counter, get_text("scanning_status"))
        
        # Отключаем анимации на время загрузки
        self.animations_disabled = True
        
        # БЛОКИРУЕМ МЫШЬ для главного окна во время загрузки
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        print("🚫 Mouse events blocked for main window during loading")
        
        # Проверяем существование папки
        if not self.workshop_path.exists():
            self.set_counter_text(self.counter, get_text("workshop_folder_not_found", path=self.workshop_path))
            self.loading_dialog.close()
            return
        
        # Запускаем сканирование в отдельном потоке
        self.scan_worker = AddonScanWorker(self.workshop_path)
        self.scan_worker.progress_updated.connect(self.loading_dialog.update_progress)
        self.scan_worker.scan_completed.connect(self.on_scan_completed)
        self.scan_worker.scan_error.connect(self.on_scan_error)
        self.scan_worker.start()
    
    def on_scan_completed(self, addons):
        """Вызывается когда сканирование завершено"""
        print(f"📁 Scan completed: {len(addons)} addons found")
        
        if not addons:
            # Если аддоны не найдены - закрываем диалог и показываем сообщение
            self.on_loading_finished()
            self.show_no_addons_message()
            return
        
        self.addons = addons
        
        # Отображаем карточки
        self.display_addons()
        
        # Запускаем загрузку информации из Steam в отдельном потоке
        self.steam_worker = SteamInfoWorker(self.addons)
        # Проверяем что диалог еще существует перед подключением
        if hasattr(self, 'loading_dialog') and self.loading_dialog:
            self.steam_worker.progress_updated.connect(self.loading_dialog.update_progress)
        self.steam_worker.info_loaded.connect(self.on_steam_info_loaded)
        self.steam_worker.start()
    
    def on_scan_error(self, error_msg):
        """Вызывается при ошибке сканирования"""
        print(f"❌ Scan error: {error_msg}")
        
        # Закрываем диалог загрузки
        self.on_loading_finished()
        
        # Показываем сообщение об ошибке
        self.set_counter_text(self.counter, get_text("folder_read_error", error=error_msg))
    
    def on_steam_info_loaded(self, updated_addons):
        """Вызывается когда информация из Steam загружена"""
        print(f"🔄 Steam info loaded for {len(updated_addons)} addons")
        self.addons = updated_addons
        
        # Перерисовываем карточки с новой информацией
        try:
            self.refresh_cards()
            print("✅ Cards refreshed successfully")
        except Exception as e:
            print(f"❌ Error refreshing cards: {e}")
        
        # Обновляем прогресс только если диалог еще существует
        if hasattr(self, 'loading_dialog') and self.loading_dialog:
            self.loading_dialog.update_progress(100, get_text("ready_status"))
        
        # Закрываем диалог загрузки НЕМЕДЛЕННО
        self.on_loading_finished()
    
    def on_loading_finished(self):
        """Вызывается после завершения всей загрузки"""
        try:
            # Принудительно очищаем все события мыши перед завершением
            QApplication.processEvents()
            
            if hasattr(self, 'loading_dialog') and self.loading_dialog:
                # Принудительно убираем blur эффект ПЕРЕД закрытием
                if hasattr(self.loading_dialog, 'parent_widget') and self.loading_dialog.parent_widget:
                    self.loading_dialog.parent_widget.setGraphicsEffect(None)
                
                # Закрываем диалог
                self.loading_dialog.close()
                self.loading_dialog.deleteLater()
                self.loading_dialog = None
                
                print("✅ Loading dialog closed successfully")
                
                # Принудительно убираем любые оставшиеся blur эффекты
                self.setGraphicsEffect(None)
                
        except Exception as e:
            print(f"❌ Ошибка закрытия диалога загрузки: {e}")
        
        # Останавливаем таймер если он еще работает
        if hasattr(self, 'loading_timeout_timer'):
            self.loading_timeout_timer.stop()
        
        # Принудительно очищаем все события мыши и обновляем интерфейс
        QApplication.processEvents()
        
        # Сбрасываем состояние всех виджетов
        self.reset_widget_states()
        
        # Обновляем счетчик аддонов
        if hasattr(self, 'addons') and self.addons:
            enabled_count = sum(1 for a in self.addons if a.get('enabled'))
            self.set_counter_text(self.counter, get_text("addons_counter", total=len(self.addons), enabled=enabled_count))
        
        # Проверяем синхронизацию с gameinfo.txt
        self.check_gameinfo_sync()
        
        # Показываем все уведомления при каждом запуске
        print("🎯 Scheduling all notifications after loading completes")
        
        # Сначала показываем предупреждение об анимациях
        # Минимальная задержка чтобы диалог загрузки закрылся
        QTimer.singleShot(200, self.show_animation_warning)
        
        # ТАЙМЕР БЕЗОПАСНОСТИ: разблокируем мышь через 5 секунд в любом случае
        QTimer.singleShot(5000, self.emergency_unblock_mouse)
        
        # Элементы вкладки покажутся после закрытия всех уведомлений
        # Пока не показываем их, они появятся после последнего диалога
            
        # Финальная очистка событий
        QApplication.processEvents()
    
    def emergency_unblock_mouse(self):
        """Экстренная разблокировка мыши если что-то пошло не так"""
        try:
            if self.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents):
                self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                print("🚨 Emergency mouse unblock activated - 5 seconds timeout reached")
        except Exception as e:
            print(f"❌ Error in emergency mouse unblock: {e}")
    
    def reset_widget_states(self):
        """Сбрасывает состояние всех виджетов после загрузки"""
        try:
            print("🔄 Resetting widget states...")
            
            # Сбрасываем состояние hover для всех карточек аддонов (если они уже созданы)
            if hasattr(self, 'addons_layout'):
                for i in range(self.addons_layout.count()):
                    widget = self.addons_layout.itemAt(i).widget()
                    if isinstance(widget, AnimatedCard):
                        # Принудительно вызываем leaveEvent для сброса hover состояния
                        fake_event = QEvent(QEvent.Type.Leave)
                        widget.leaveEvent(fake_event)
                        
                        # Убираем графические эффекты
                        if widget.graphicsEffect():
                            widget.setGraphicsEffect(None)
            
            # Сбрасываем курсор мыши
            self.setCursor(Qt.CursorShape.ArrowCursor)
            
            # Принудительно обновляем все виджеты
            self.update()
            
            print("✅ Widget states reset")
            
        except Exception as e:
            print(f"❌ Ошибка сброса состояния виджетов: {e}")
    
    def get_enabled_addons_from_folders(self):
        """Получает список включенных аддонов по наличию папок и vpk файлов в steamapps/workshop/"""
        enabled = set()
        
        if not self.workshop_path or not self.workshop_path.exists():
            return enabled
        
        try:
            # Аддон включен если есть И vpk файл И папка с одним ID
            vpk_files = {f.stem for f in self.workshop_path.glob("*.vpk") if f.stem.isdigit()}
            addon_folders = {f.name for f in self.workshop_path.iterdir() if f.is_dir() and f.name.isdigit()}
            
            # Пересечение - аддоны у которых есть и файл и папка
            enabled = vpk_files & addon_folders
            
        except Exception as e:
            print(f"Ошибка проверки папок: {e}")
        
        return enabled
    
    def get_enabled_addons(self):
        """Получает список включенных аддонов из gameinfo.txt"""
        enabled = set()
        
        if not self.gameinfo_path or not self.gameinfo_path.exists():
            return enabled
        
        try:
            with open(self.gameinfo_path, 'r', encoding='utf-8') as f:
                content = f.read()
                # Ищем строки с left4dead2\addons\workshop\ID
                matches = re.findall(r'Game\s+left4dead2\\addons\\workshop\\([^\s\\]+)', content)
                enabled.update(matches)
        except Exception as e:
            print(f"Ошибка чтения gameinfo.txt: {e}")
        
        return enabled
    
    def display_addons(self):
        """Отображает карточки аддонов с сортировкой (оптимизированная версия)"""
        # Получаем выбранный тип сортировки
        sort_type = self.sort_combo.currentIndex() if hasattr(self, 'sort_combo') else 0
        
        # Применяем сортировку
        if sort_type == 0:  # По алфавиту
            sorted_addons = sorted(self.addons, key=lambda a: a.get('name', '').lower())
        elif sort_type == 1:  # Сначала включенные
            sorted_addons = sorted(self.addons, key=lambda a: (not a.get('enabled', False), a.get('name', '').lower()))
        else:  # Сначала выключенные (sort_type == 2)
            sorted_addons = sorted(self.addons, key=lambda a: (a.get('enabled', False), a.get('name', '').lower()))
        
        # Собираем существующие карточки в словарь
        existing_cards = {}
        # Извлекаем все элементы из layout
        while self.addons_layout.count():
            item = self.addons_layout.takeAt(0)
            if item and item.widget():
                widget = item.widget()
                if isinstance(widget, AnimatedCard):
                    existing_cards[widget.addon['id']] = widget
        
        # Удаляем карточки которые больше не нужны
        addon_ids = {addon['id'] for addon in sorted_addons}
        for card_id, card in list(existing_cards.items()):
            if card_id not in addon_ids:
                card.deleteLater()
                del existing_cards[card_id]
        
        # Добавляем карточки в новом порядке (создаем только новые)
        for i, addon in enumerate(sorted_addons):
            if addon['id'] in existing_cards:
                # Используем существующую карточку
                card = existing_cards[addon['id']]
                card.addon = addon  # Обновляем данные аддона
                card.index = i
                # Обновляем состояние toggle switch из данных аддона
                card.update_state()
            else:
                # Создаем новую карточку
                card = AnimatedCard(addon, i, self)
                card.toggled.connect(self.toggle_addon)
            
            # Добавляем в layout (всегда 1 столбец)
            self.addons_layout.insertWidget(i, card)
            
            # Обрабатываем события каждые 20 карточек для плавности
            if i % 20 == 0:
                QApplication.processEvents()
        
        enabled_count = sum(1 for a in self.addons if a.get('enabled'))
        self.set_counter_text(self.counter, get_text("addons_counter", total=len(self.addons), enabled=enabled_count))
        
        # Принудительно сбрасываем hover состояния всех карточек после создания
        QTimer.singleShot(100, self.force_reset_card_states)
    
    def force_reset_card_states(self):
        """Принудительно сбрасывает hover состояния всех карточек аддонов"""
        try:
            print("🔄 Force resetting card hover states...")
            
            # Временно отключаем анимации для гарантированного сброса
            was_disabled = getattr(self, 'animations_disabled', False)
            self.animations_disabled = True
            
            # Сбрасываем состояния всех карточек
            if hasattr(self, 'addons_layout'):
                for i in range(self.addons_layout.count()):
                    widget = self.addons_layout.itemAt(i).widget()
                    if isinstance(widget, AnimatedCard):
                        # Используем новый метод принудительного сброса
                        widget.force_reset_state()
            
            # Обрабатываем события
            QApplication.processEvents()
            
            # Восстанавливаем предыдущее состояние анимаций
            self.animations_disabled = was_disabled
            
            print("✅ Card hover states reset successfully")
            
        except Exception as e:
            print(f"❌ Error resetting card states: {e}")
    
    def load_steam_info_with_progress(self, loading_dialog):
        """Загружает информацию из Steam Workshop API с прогрессом"""
        if not self.addons:
            loading_dialog.close()
            return
        
        # Формируем запрос для всех аддонов
        addon_ids = [addon['id'] for addon in self.addons]
        total = len(addon_ids)
        
        try:
            # Формируем POST данные
            post_data = {
                'itemcount': len(addon_ids),
            }
            
            for i, addon_id in enumerate(addon_ids):
                post_data[f'publishedfileids[{i}]'] = addon_id
            
            # Кодируем данные
            import urllib.parse
            data = urllib.parse.urlencode(post_data).encode('utf-8')
            
            # Делаем запрос
            response = urlopen(STEAM_API_URL, data=data, timeout=5)
            result = json.loads(response.read().decode('utf-8'))
            
            if result.get('response', {}).get('publishedfiledetails'):
                details = result['response']['publishedfiledetails']
                
                for idx, detail in enumerate(details):
                    addon_id = detail.get('publishedfileid')
                    result_code = detail.get('result', 0)
                    
                    if result_code == 1:  # Success
                        title = detail.get('title', f'Аддон {addon_id}')
                        description = detail.get('description', '')
                        preview_url = detail.get('preview_url', '')
                        
                        # Очищаем BBCode из описания
                        description = self.clean_bbcode(description)
                        
                        # Обновляем данные аддона
                        for addon in self.addons:
                            if addon['id'] == addon_id:
                                addon['name'] = title
                                addon['description'] = description[:150] + '...' if len(description) > 150 else description
                                addon['preview_url'] = preview_url
                                break
                    else:
                        # Аддон недоступен (удален, приватный и т.д.)
                        for addon in self.addons:
                            if addon['id'] == addon_id:
                                addon['name'] = f'Аддон {addon_id} (недоступен)'
                                addon['description'] = get_text("addon_removed_description")
                                break
                    
                    # Обновляем прогресс
                    progress = 50 + int((idx + 1) / total * 40)
                    loading_dialog.update_progress(progress, get_text("loaded_progress", current=idx + 1, total=total))
                    
                    # Обрабатываем события каждые 5 аддонов
                    if idx % 5 == 0:
                        QApplication.processEvents()
                
                loading_dialog.update_progress(95, "Обновление интерфейса...")
                
                # Перерисовываем карточки с новой информацией
                self.refresh_cards()
                
                loading_dialog.update_progress(100, get_text("ready_status"))
                QTimer.singleShot(500, loading_dialog.close)
        
        except Exception as e:
            print(f"Ошибка загрузки из Steam API: {e}")
            loading_dialog.close()
    
    def load_steam_info(self):
        """Загружает информацию из Steam Workshop API (без прогресса)"""
        if not self.addons:
            return
        
        # Формируем запрос для всех аддонов
        addon_ids = [addon['id'] for addon in self.addons]
        
        try:
            # Формируем POST данные
            post_data = {
                'itemcount': len(addon_ids),
            }
            
            for i, addon_id in enumerate(addon_ids):
                post_data[f'publishedfileids[{i}]'] = addon_id
            
            # Кодируем данные
            import urllib.parse
            data = urllib.parse.urlencode(post_data).encode('utf-8')
            
            # Делаем запрос
            response = urlopen(STEAM_API_URL, data=data, timeout=5)
            result = json.loads(response.read().decode('utf-8'))
            
            if result.get('response', {}).get('publishedfiledetails'):
                details = result['response']['publishedfiledetails']
                
                for detail in details:
                    if detail.get('result') == 1:  # Success
                        addon_id = detail.get('publishedfileid')
                        title = detail.get('title', f'Аддон {addon_id}')
                        description = detail.get('description', '')
                        preview_url = detail.get('preview_url', '')
                        
                        # Очищаем BBCode из описания
                        description = self.clean_bbcode(description)
                        
                        # Обновляем данные аддона
                        for addon in self.addons:
                            if addon['id'] == addon_id:
                                addon['name'] = title
                                addon['description'] = description[:150] + '...' if len(description) > 150 else description
                                addon['preview_url'] = preview_url
                                break
                
                # Перерисовываем карточки с новой информацией
                self.refresh_cards()
        
        except Exception as e:
            print(f"Ошибка загрузки из Steam API: {e}")
    
    def clean_bbcode(self, text):
        """Удаляет BBCode теги из текста"""
        # Удаляем все BBCode теги
        text = re.sub(r'\[.*?\]', '', text)
        # Удаляем лишние пробелы
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    
    def refresh_cards(self):
        """Обновляет карточки с новой информацией"""
        # Удаляем старые карточки
        count = 0
        while self.addons_layout.count() > 1:
            item = self.addons_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            count += 1
            # Обрабатываем события каждые 10 карточек
            if count % 10 == 0:
                QApplication.processEvents()
        
        # Создаем новые с обновленной информацией
        self.display_addons()
    
    def toggle_addon(self, addon_data):
        """Включает/выключает аддон"""
        addon_id = addon_data['id']
        
        # Показываем курсор ожидания
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        
        try:
            # Находим аддон в списке и карточку
            addon_card = None
            for addon in self.addons:
                if addon['id'] == addon_id:
                    # Используем текущее состояние из addon_data (уже обновлено в on_toggle_changed)
                    new_status = addon_data.get('enabled', False)
                    addon['enabled'] = new_status
                    
                    # Выполняем операцию
                    if new_status:
                        self.enable_addon(addon)
                    else:
                        self.disable_addon(addon)
                    
                    # Находим карточку в интерфейсе
                    for i in range(self.addons_layout.count()):
                        widget = self.addons_layout.itemAt(i).widget()
                        if isinstance(widget, AnimatedCard) and widget.addon['id'] == addon_id:
                            addon_card = widget
                            break
                    
                    break
            
            # Обновляем только индикатор (тумблер уже в правильном состоянии)
            if addon_card:
                for child in addon_card.findChildren(QLabel):
                    if child.objectName() == "statusIndicator":
                        color = '#3498db' if addon['enabled'] else '#95a5a6'
                        child.setStyleSheet(f"color: {color}; font-size: 16px; background: transparent; border: none;")
                        break
            
            # Обновляем счетчик
            enabled_count = sum(1 for a in self.addons if a.get('enabled'))
            self.set_counter_text(self.counter, get_text("addons_counter", total=len(self.addons), enabled=enabled_count))
            
            # Проверяем синхронизацию с gameinfo.txt
            self.check_gameinfo_sync()
            
        finally:
            # Восстанавливаем курсор
            QApplication.restoreOverrideCursor()
    
    def update_card_status(self, card, is_enabled):
        """Обновляет визуальный статус карточки без перерисовки"""
        # Обновляем переключатель (блокируем сигналы чтобы не вызвать повторное переключение)
        card.toggle_switch.blockSignals(True)
        card.toggle_switch.setChecked(is_enabled)
        card.toggle_switch.blockSignals(False)
        
        # Обновляем индикатор статуса
        for child in card.findChildren(QLabel):
            if child.objectName() == "statusIndicator":
                color = '#3498db' if is_enabled else '#95a5a6'
                child.setStyleSheet(f"color: {color}; font-size: 16px; background: transparent; border: none;")
                break
    
    def enable_addon(self, addon):
        """Включает аддон (правильная логика из оригинала)"""
        if not self.gameinfo_path or not self.workshop_path:
            QMessageBox.warning(self, get_text("error_title"), get_text("configure_game_path_short"))
            return
        
        try:
            # Определяем папку addons/workshop
            gameinfo_dir = Path(self.gameinfo_path).parent
            workshop_dir = gameinfo_dir / "addons" / "workshop"
            workshop_dir.mkdir(parents=True, exist_ok=True)
            
            # Создаём папку для мода: addons/workshop/ID/
            mod_id = addon['id']
            mod_dir = workshop_dir / mod_id
            mod_dir.mkdir(exist_ok=True)
            
            # Копируем .vpk файл и называем pak01_dir.vpk
            vpk_source = Path(addon['path'])
            vpk_dest = mod_dir / "pak01_dir.vpk"
            
            # Копируем только если файла нет или размер отличается
            if not vpk_dest.exists() or vpk_dest.stat().st_size != vpk_source.stat().st_size:
                shutil.copy2(vpk_source, vpk_dest)
            
            # Добавляем в gameinfo.txt (путь к папке, а не к файлу!)
            self.add_to_gameinfo(mod_id)
            
        except Exception as e:
            QMessageBox.critical(self, get_text("error_title"), get_text("addon_enable_error", error=str(e)))
    
    def disable_addon(self, addon):
        """Выключает аддон (правильная логика из оригинала)"""
        try:
            # Удаляем из gameinfo.txt
            self.remove_from_gameinfo(addon['id'])
            
            # Удаляем папку аддона addons/workshop/ID/
            gameinfo_dir = Path(self.gameinfo_path).parent
            addon_dir = gameinfo_dir / "addons" / "workshop" / addon['id']
            
            if addon_dir.exists():
                shutil.rmtree(addon_dir)
            
        except Exception as e:
            QMessageBox.critical(self, get_text("error_title"), get_text("addon_disable_error", error=str(e)))
    
    def add_to_gameinfo(self, addon_id):
        """Добавляет аддон в gameinfo.txt"""
        if not self.gameinfo_path.exists():
            return
        
        try:
            # Создаем бэкап только один раз (проверка быстрая)
            backup_path = self.gameinfo_path.with_suffix('.txt.backup')
            if not backup_path.exists():
                try:
                    shutil.copy2(self.gameinfo_path, backup_path)
                except:
                    pass  # Игнорируем ошибки бэкапа
            
            with open(self.gameinfo_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Ищем секцию SearchPaths
            search_paths_index = -1
            for i, line in enumerate(lines):
                if 'SearchPaths' in line:
                    search_paths_index = i
                    break
            
            if search_paths_index == -1:
                return
            
            # Проверяем, не добавлен ли уже (путь к ПАПКЕ, а не к .vpk!)
            addon_line = f'\t\t\tGame\tleft4dead2\\addons\\workshop\\{addon_id}\n'
            if addon_line in lines:
                return
            
            # Находим место для вставки (после первой Game строки)
            insert_index = search_paths_index + 1
            for i in range(search_paths_index + 1, len(lines)):
                if 'Game' in lines[i]:
                    insert_index = i + 1
                    break
            
            # Вставляем строку
            lines.insert(insert_index, addon_line)
            
            # Записываем обратно
            with open(self.gameinfo_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
        
        except Exception as e:
            print(f"Ошибка добавления в gameinfo.txt: {e}")
    
    def remove_from_gameinfo(self, addon_id):
        """Удаляет аддон из gameinfo.txt"""
        if not self.gameinfo_path.exists():
            return
        
        try:
            with open(self.gameinfo_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Удаляем строку с этим аддоном (используем regex для гибкости)
            pattern = rf'\s*Game\s+left4dead2\\addons\\workshop\\{re.escape(addon_id)}\s*\n'
            content = re.sub(pattern, '', content)
            
            # Записываем обратно
            with open(self.gameinfo_path, 'w', encoding='utf-8') as f:
                f.write(content)
        
        except Exception as e:
            print(f"Ошибка удаления из gameinfo.txt: {e}")
    

    
    def toggle_pirate_view_mode(self):
        """Переключает режим отображения между 1 и 2 столбцами для пиратской вкладки"""
        self.is_pirate_two_column_mode = not self.is_pirate_two_column_mode
        self.pirate_view_toggle_btn.is_two_columns = self.is_pirate_two_column_mode
        self.pirate_view_toggle_btn.update()
        
        # Обновляем tooltip
        if self.is_pirate_two_column_mode:
            self.pirate_view_toggle_btn.setToolTip(get_text("tooltip_switch_to_single"))
        else:
            self.pirate_view_toggle_btn.setToolTip(get_text("tooltip_switch_to_double"))
        
        # Пересоздаём layout (удаляя старые карточки, т.к. они имеют неправильный размер)
        self.recreate_pirate_addons_layout_with_delete()
        
        # Перерисовываем аддоны (создаст новые карточки с правильным размером)
        self.display_pirate_addons()
    
    def recreate_pirate_addons_layout_with_delete(self):
        """Пересоздаёт layout для пиратских аддонов, удаляя старые карточки"""
        old_layout = self.pirate_addons_container.layout()
        if old_layout:
            # Удаляем все виджеты
            while old_layout.count():
                item = old_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            
            # Удаляем старый layout
            QWidget().setLayout(old_layout)
        
        # Создаём новый layout
        if self.is_pirate_two_column_mode:
            self.pirate_addons_layout = QGridLayout()
            self.pirate_addons_layout.setSpacing(10)
            self.pirate_addons_layout.setColumnStretch(0, 1)
            self.pirate_addons_layout.setColumnStretch(1, 1)
        else:
            self.pirate_addons_layout = QVBoxLayout()
            self.pirate_addons_layout.setSpacing(10)
            self.pirate_addons_layout.addStretch()
        
        # Устанавливаем новый layout на контейнер
        self.pirate_addons_container.setLayout(self.pirate_addons_layout)
    
    def recreate_pirate_addons_layout(self):
        """Пересоздаёт layout для пиратских аддонов в зависимости от режима"""
        # Сохраняем все виджеты перед удалением layout
        saved_widgets = []
        old_layout = self.pirate_addons_container.layout()
        if old_layout:
            # Извлекаем все виджеты (но НЕ удаляем их)
            while old_layout.count():
                item = old_layout.takeAt(0)
                if item.widget():
                    widget = item.widget()
                    widget.setParent(None)  # Отсоединяем от родителя
                    saved_widgets.append(widget)
            
            # Удаляем старый layout
            QWidget().setLayout(old_layout)
        
        # Создаём новый layout
        if self.is_pirate_two_column_mode:
            self.pirate_addons_layout = QGridLayout()
            self.pirate_addons_layout.setSpacing(10)
            self.pirate_addons_layout.setColumnStretch(0, 1)
            self.pirate_addons_layout.setColumnStretch(1, 1)
        else:
            self.pirate_addons_layout = QVBoxLayout()
            self.pirate_addons_layout.setSpacing(10)
            self.pirate_addons_layout.addStretch()
        
        # Устанавливаем новый layout на контейнер
        self.pirate_addons_container.setLayout(self.pirate_addons_layout)
        
        # Возвращаем виджеты обратно в контейнер (чтобы display_pirate_addons мог их найти)
        for widget in saved_widgets:
            widget.setParent(self.pirate_addons_container)
    
    def enable_all_addons(self):
        """Включает все аддоны"""
        if not self.addons:
            return
        
        # Используем кастомный диалог
        if not CustomConfirmDialog.question(
            self,
            get_text("confirmation_title"),
            get_text("confirm_enable_all", count=len(self.addons))
        ):
            return
        
        # Показываем кастомный прогресс (0-100%)
        progress = CustomProgressDialog(self, get_text("enabling_addons"), get_text("btn_cancel"), 0, 100)
        progress.show()
        
        total = len(self.addons)
        for i, addon in enumerate(self.addons):
            if progress.wasCanceled():
                break
            
            # Конвертируем в проценты (0-100)
            percent = int((i / total) * 100)
            progress.setValue(percent)
            progress.setLabelText(get_text("enabling_addon", name=addon['name'], current=i+1, total=total))
            QApplication.processEvents()
            
            if not addon.get('enabled'):
                addon['enabled'] = True
                self.enable_addon(addon)
        
        progress.setValue(100)
        
        # Полностью перерисовываем карточки с новым состоянием
        self.display_addons()
        self.check_gameinfo_sync()
        
        # Закрываем прогресс без убирания блюра
        progress.close_keeping_blur()
        
        # Небольшая задержка для плавности
        QApplication.processEvents()
        import time
        time.sleep(0.35)
        
        # Показываем кастомное информационное окно (используем существующий блюр)
        CustomInfoDialog.information(self, get_text("ready_title"), get_text("enabled_addons_count", count=len(self.addons)), use_existing_blur=True, icon_type="success")
    
    def disable_all_addons(self):
        """Выключает все аддоны и удаляет их папки"""
        if not self.addons:
            return
        
        # Используем кастомный диалог
        if not CustomConfirmDialog.question(
            self,
            get_text("confirmation_title"),
            get_text("confirm_disable_all", count=len(self.addons))
        ):
            return
        
        # Показываем кастомный прогресс (0-100%)
        progress = CustomProgressDialog(self, get_text("disabling_addons"), get_text("btn_cancel"), 0, 100)
        progress.show()
        
        total = len(self.addons)
        
        # Восстанавливаем gameinfo из бэкапа (0-10%)
        progress.setValue(0)
        progress.setLabelText(get_text("restoring_gameinfo"))
        QApplication.processEvents()
        
        try:
            backup_path = self.gameinfo_path.with_suffix('.txt.backup')
            if backup_path.exists():
                shutil.copy2(backup_path, self.gameinfo_path)
            else:
                # Если нет бэкапа, удаляем все записи вручную
                for addon in self.addons:
                    self.remove_from_gameinfo(addon['id'])
        except Exception as e:
            progress.close_keeping_blur()
            
            # Небольшая задержка для плавности
            QApplication.processEvents()
            import time
            time.sleep(0.35)
            
            CustomInfoDialog.information(
                self, 
                get_text("error_title"), 
                get_text("gameinfo_restore_error", error=str(e)),
                use_existing_blur=True,
                icon_type="error"
            )
            return
        
        progress.setValue(10)
        
        # Удаляем папки аддонов (10-100%)
        gameinfo_dir = Path(self.gameinfo_path).parent
        workshop_dir = gameinfo_dir / "addons" / "workshop"
        
        for i, addon in enumerate(self.addons):
            if progress.wasCanceled():
                break
            
            # Конвертируем в проценты (10-100)
            percent = int(10 + (i / total) * 90)
            progress.setValue(percent)
            progress.setLabelText(get_text("deleting_folder", addon_id=addon['id'], current=i+1, total=total))
            QApplication.processEvents()
            
            try:
                addon_dir = workshop_dir / addon['id']
                if addon_dir.exists():
                    shutil.rmtree(addon_dir)
            except Exception as e:
                print(f"Ошибка удаления папки {addon['id']}: {e}")
        
        progress.setValue(100)
        
        # Обновляем статус всех аддонов
        for addon in self.addons:
            addon['enabled'] = False
        
        # Полностью перерисовываем карточки с новым состоянием
        self.display_addons()
        
        # Закрываем прогресс без убирания блюра
        progress.close_keeping_blur()
        
        # Небольшая задержка для плавности
        QApplication.processEvents()
        import time
        time.sleep(0.35)
        
        # Показываем кастомное информационное окно (используем существующий блюр)
        CustomInfoDialog.information(self, get_text("ready_title"), get_text("all_addons_disabled"), use_existing_blur=True, icon_type="success")
    
    def add_vpk_to_addons(self):
        """Добавляет .vpk файл в папку addons/ (для пиратки)"""
        if not self.game_folder:
            CustomInfoDialog.information(
                self, 
                get_text("error_title"), 
                get_text("specify_game_folder_error"),
                icon_type="error"
            )
            return
        
        # Диалог выбора файлов (можно выбрать несколько)
        vpk_files, _ = QFileDialog.getOpenFileNames(
            self,
            "Выберите .vpk файлы для установки",
            str(Path.home()),
            "VPK Files (*.vpk)"
        )
        
        if not vpk_files:
            return
        
        # Папка addons
        addons_dir = self.game_folder / "left4dead2" / "addons"
        addons_dir.mkdir(parents=True, exist_ok=True)
        
        # Кастомный прогресс-диалог
        progress = CustomProgressDialog(
            self,
            get_text("copying_files"),
            get_text("btn_cancel"),
            0,
            100
        )
        progress.show()
        
        success_count = 0
        skipped_count = 0
        failed_files = []
        total = len(vpk_files)
        user_canceled = False
        
        for i, vpk_file in enumerate(vpk_files):
            if progress.wasCanceled():
                user_canceled = True
                break
            
            vpk_path = Path(vpk_file)
            percent = int((i / total) * 100)
            progress.setValue(percent)
            progress.setLabelText(get_text("copying_file", filename=vpk_path.name, current=i+1, total=total))
            QApplication.processEvents()
            
            try:
                dest_path = addons_dir / vpk_path.name
                
                # Проверяем не существует ли уже
                if dest_path.exists():
                    # Скрываем прогресс-диалог временно
                    progress.hide()
                    
                    # Используем кастомный диалог подтверждения БЕЗ создания нового blur
                    reply = CustomConfirmDialog.question(
                        self,
                        get_text("file_exists_title"),
                        get_text("file_exists_message", filename=vpk_path.name),
                        use_existing_blur=False  # Создаем свой blur т.к. прогресс скрыт
                    )
                    
                    # Показываем прогресс-диалог обратно
                    progress.show()
                    
                    if not reply:
                        skipped_count += 1
                        continue
                
                # Копируем
                shutil.copy2(vpk_path, dest_path)
                success_count += 1
                
            except Exception as e:
                failed_files.append(f"{vpk_path.name}: {str(e)}")
        
        progress.setValue(100)
        
        # Если пользователь отменил или все файлы пропущены - просто закрываем без сообщения
        if user_canceled or (success_count == 0 and len(failed_files) == 0):
            progress.close()
            # Убираем blur
            if self.graphicsEffect():
                self.setGraphicsEffect(None)
            central_widget = self.centralWidget()
            if central_widget and central_widget.graphicsEffect():
                central_widget.setGraphicsEffect(None)
            # Обновляем список модов
            self.scan_pirate_addons()
            return
        
        progress.close_keeping_blur()
        
        # Небольшая задержка для плавности
        QApplication.processEvents()
        import time
        time.sleep(0.35)
        
        # Результат
        result_msg = get_text("install_result", 
            success=success_count, 
            total=total, 
            skipped=skipped_count if skipped_count > 0 else 0,
            path=addons_dir
        )
        result_msg += "Активируйте их в меню Add-ons в игре."
        
        if failed_files:
            result_msg += f"\n\nОшибки:\n" + "\n".join(failed_files[:3])
            if len(failed_files) > 3:
                result_msg += f"\n... и еще {len(failed_files) - 3}"
            
            # Если есть ошибки - показываем с иконкой ошибки
            CustomInfoDialog.information(
                self, 
                get_text("installation_completed_errors"), 
                result_msg,
                use_existing_blur=True,
                icon_type="error"
            )
        else:
            # Если все успешно - показываем с зеленой галочкой
            CustomInfoDialog.information(
                self, 
                get_text("installation_completed"), 
                result_msg,
                use_existing_blur=True,
                icon_type="success"
            )
        
        # Обновляем список модов
        self.scan_pirate_addons()
    
    def ensure_steamcmd_installed(self, use_existing_blur=False):
        """Проверяет наличие SteamCMD и предлагает установить если нет"""
        # Определяем папку программы (работает и для .py и для .exe)
        if getattr(sys, 'frozen', False):
            # Если запущен как .exe (PyInstaller)
            program_dir = Path(sys.executable).parent
        else:
            # Если запущен как .py скрипт
            program_dir = Path(__file__).parent
        
        steamcmd_path = program_dir / "steamcmd"
        steamcmd_exe = steamcmd_path / "steamcmd.exe"
        
        if steamcmd_exe.exists():
            return steamcmd_path
        
        # SteamCMD не найден - предлагаем установить
        if use_existing_blur:
            # Используем существующий блюр
            dialog = CustomConfirmDialog(
                self,
                get_text("install_steamcmd_title"),
                get_text("install_steamcmd_confirm") + "\n\n" + get_text("steamcmd_install_details", path=steamcmd_path),
                use_existing_blur=True
            )
            reply_code = dialog.exec()
            reply = reply_code == dialog.DialogCode.Accepted
            
            if reply:
                dialog.close_keeping_blur()
            else:
                dialog.close()
        else:
            # Создаём новый блюр
            reply = CustomConfirmDialog.question(
                self,
                get_text("install_steamcmd_title"),
                get_text("install_steamcmd_confirm") + "\n\n" + get_text("steamcmd_install_details", path=steamcmd_path)
            )
        
        if reply is None or (not use_existing_blur and reply is False):
            # Пользователь закрыл окно или нажал "Нет"
            if not reply and reply is not None:
                # Нажал "Нет" - предлагаем выбрать папку
                from PyQt6.QtWidgets import QFileDialog
                selected_dir = QFileDialog.getExistingDirectory(
                    self,
                    "Выберите папку для установки SteamCMD",
                    str(program_dir),
                    QFileDialog.Option.ShowDirsOnly
                )
                
                if not selected_dir:
                    # Пользователь отменил выбор
                    return None
                
                steamcmd_path = Path(selected_dir) / "steamcmd"
                steamcmd_exe = steamcmd_path / "steamcmd.exe"
            else:
                return None
        
        # Создаём прогресс-диалог (используем существующий блюр если есть)
        progress = CustomProgressDialog(
            self,
            "Установка SteamCMD...",
            "Отмена",
            0,
            100,
            use_existing_blur=use_existing_blur
        )
        progress.show()
        progress.setValue(10)
        QApplication.processEvents()
        
        try:
            import urllib.request
            import zipfile
            import tempfile
            
            # URL для скачивания SteamCMD
            steamcmd_url = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
            
            progress.setLabelText(get_text("downloading_steamcmd_simple"))
            progress.setValue(20)
            QApplication.processEvents()
            
            # Скачиваем во временную папку
            temp_dir = Path(tempfile.mkdtemp())
            zip_path = temp_dir / "steamcmd.zip"
            
            # Переменные для отслеживания скорости
            import time
            last_update_time = [time.time()]
            last_downloaded = [0]
            
            # Функция форматирования размера
            def format_bytes(bytes_val):
                if bytes_val < 1024:
                    return f"{bytes_val} B"
                elif bytes_val < 1024 * 1024:
                    return f"{bytes_val / 1024:.2f} KB"
                else:
                    return f"{bytes_val / (1024 * 1024):.2f} MB"
            
            # Скачиваем с прогрессом
            def download_progress(block_num, block_size, total_size):
                if progress.wasCanceled():
                    raise Exception("Отменено пользователем")
                
                downloaded = block_num * block_size
                if total_size > 0:
                    percent = min(int((downloaded / total_size) * 40) + 20, 60)
                    progress.setValue(percent)
                    
                    # Вычисляем скорость
                    current_time = time.time()
                    time_diff = current_time - last_update_time[0]
                    
                    if time_diff >= 0.3:  # Обновляем каждые 0.3 сек
                        bytes_diff = downloaded - last_downloaded[0]
                        download_speed = bytes_diff / time_diff if time_diff > 0 else 0
                        last_downloaded[0] = downloaded
                        last_update_time[0] = current_time
                        
                        speed_str = format_bytes(download_speed) + "/s"
                        downloaded_str = format_bytes(downloaded)
                        total_str = format_bytes(total_size)
                        
                        progress.setLabelText(
                            get_text("downloading_steamcmd", 
                                downloaded=downloaded_str, 
                                total=total_str, 
                                speed=speed_str
                            )
                        )
                    
                    QApplication.processEvents()
            
            urllib.request.urlretrieve(steamcmd_url, zip_path, download_progress)
            
            progress.setLabelText(get_text("extracting_steamcmd"))
            progress.setValue(65)
            QApplication.processEvents()
            
            # Создаём папку steamcmd
            steamcmd_path.mkdir(parents=True, exist_ok=True)
            
            # Распаковываем
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(steamcmd_path)
            
            progress.setValue(80)
            progress.setLabelText(get_text("steamcmd_first_run"))
            QApplication.processEvents()
            
            # Первый запуск SteamCMD для инициализации
            import subprocess
            init_process = subprocess.Popen(
                [str(steamcmd_exe), "+quit"],
                cwd=str(steamcmd_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
                universal_newlines=True,
                bufsize=1
            )
            
            # Ждём завершения с анимацией прогресса и таймаутом
            init_progress = 80
            loop_counter = 0
            start_time = time.time()
            timeout = 30  # Таймаут 30 секунд (инициализация не обязательна)
            
            # Читаем вывод в отдельном потоке
            import threading
            output_lines = []
            
            def read_output():
                try:
                    for line in iter(init_process.stdout.readline, ''):
                        output_lines.append(line.strip())
                except:
                    pass
            
            output_thread = threading.Thread(target=read_output, daemon=True)
            output_thread.start()
            
            while init_process.poll() is None:
                # Процесс ещё работает
                elapsed = time.time() - start_time
                
                if progress.wasCanceled():
                    # Пользователь отменил - убиваем процесс и продолжаем
                    init_process.kill()
                    break
                
                # Показываем простое сообщение без технических деталей
                progress.setLabelText(
                    get_text("steamcmd_wait", seconds=int(elapsed))
                )
                
                # Обрабатываем события интерфейса чаще
                QApplication.processEvents()
                
                # Плавно увеличиваем прогресс от 80 до 100
                loop_counter += 1
                if loop_counter % 5 == 0 and init_progress < 100:
                    init_progress += 1
                    progress.setValue(init_progress)
                
                # Автоматически завершаем при достижении 100%
                if init_progress >= 100:
                    init_process.kill()
                    break
                
                # Проверяем таймаут
                if elapsed > timeout:
                    # Таймаут - убиваем процесс и продолжаем
                    init_process.kill()
                    break
                
                time.sleep(0.01)  # Очень короткая задержка
            
            progress.setValue(100)
            progress.close_keeping_blur()
            
            # Небольшая задержка для плавности
            QApplication.processEvents()
            import time
            time.sleep(0.35)
            
            # Показываем успешное сообщение и ждём его закрытия
            CustomInfoDialog.information(
                self,
                get_text("success_title"),
                get_text("steamcmd_success_message"),
                use_existing_blur=True,
                icon_type="success"
            )
            
            # Очищаем временные файлы
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
            
            return steamcmd_path
            
        except Exception as e:
            has_progress = 'progress' in locals()
            
            if has_progress:
                progress.close_keeping_blur()
                
                # Небольшая задержка для плавности
                QApplication.processEvents()
                import time
                time.sleep(0.35)
            
            if get_text("cancelled_text") not in str(e):
                CustomInfoDialog.information(
                    self,
                    get_text("installation_error_title"),
                    get_text("steamcmd_error_message", error=str(e)),
                    f"https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip\n\n"
                    f"И распаковать в папку программы.",
                    use_existing_blur=has_progress and use_existing_blur
                )
            
            return None
    
    def auto_download_workshop_addon(self, addon_id, use_existing_blur=False, show_success_message=True, batch_info=None, existing_progress=None):
        """Автоматически скачивает мод через SteamCMD"""
        try:
            import subprocess
            import tempfile
            import zipfile
            
            print(f"[DEBUG] auto_download_workshop_addon вызван с addon_id={addon_id}, use_existing_blur={use_existing_blur}")
            
            # Проверяем и устанавливаем SteamCMD если нужно
            steamcmd_path = self.ensure_steamcmd_installed(use_existing_blur=use_existing_blur)
            
            print(f"[DEBUG] steamcmd_path = {steamcmd_path}")
            
            if not steamcmd_path:
                # Пользователь отменил установку
                print("[DEBUG] Пользователь отменил установку SteamCMD")
                return
            
            steamcmd_exe = steamcmd_path / "steamcmd.exe"
            print(f"[DEBUG] steamcmd_exe = {steamcmd_exe}")
        except Exception as e:
            import traceback
            error_msg = get_text("download_error_start", error=str(e), traceback=traceback.format_exc())
            print(error_msg)
            CustomInfoDialog.information(self, get_text("error_title"), get_text("unexpected_error", error=str(e)), icon_type="error")
            return
        
        # Формируем префикс для серии модов и вычисляем базовый прогресс
        batch_prefix = ""
        base_progress = 0  # Базовый прогресс для текущего мода
        progress_multiplier = 1.0  # Множитель для прогресса текущего мода
        
        if batch_info:
            current_num, total_num = batch_info
            batch_prefix = f"[{current_num}/{total_num}] "
            # Вычисляем базовый прогресс (сколько уже скачано)
            base_progress = int(((current_num - 1) / total_num) * 100)
            # Вычисляем множитель (какую часть общего прогресса занимает текущий мод)
            progress_multiplier = 1.0 / total_num
        
        # Используем существующий прогресс-диалог или создаём новый
        if existing_progress:
            progress = existing_progress
            # Устанавливаем начальный прогресс с учетом batch
            initial_progress = base_progress + int(10 * progress_multiplier)
            progress.setValue(initial_progress)
            QApplication.processEvents()
        else:
            # Создаём прогресс-диалог (используем существующий блюр если есть)
            initial_title = f"{batch_prefix}Скачивание мода {addon_id}..."
            progress = CustomProgressDialog(
                self,
                initial_title,
                "Отмена",
                0,
                100,
                use_existing_blur=use_existing_blur
            )
            progress.show()
            # Устанавливаем начальный прогресс с учетом batch
            initial_progress = base_progress + int(10 * progress_multiplier)
            progress.setValue(initial_progress)
            QApplication.processEvents()
        
        try:
            # Получаем информацию о моде
            progress.setLabelText(f"{batch_prefix}{get_text('getting_mod_info')}")
            progress.setValue(base_progress + int(20 * progress_multiplier))
            QApplication.processEvents()
            
            addon_info = self.get_workshop_addon_info(addon_id)
            addon_name = addon_info.get('title', f'addon_{addon_id}')
            
            # Сразу очищаем имя от недопустимых символов
            import re
            addon_name = re.sub(r'[<>:"/\\|?*]', '_', addon_name)
            addon_name = addon_name.strip()
            if not addon_name:
                addon_name = f'addon_{addon_id}'
            
            # Обновляем batch_prefix с названием мода
            if batch_info:
                current_num, total_num = batch_info
                batch_prefix = f"[{current_num}/{total_num}] {addon_name}\n"
            else:
                batch_prefix = f"{addon_name}\n"
            
            # Создаём временную папку для скачивания
            temp_dir = Path(tempfile.mkdtemp())
            download_path = temp_dir / addon_id
            
            progress.setLabelText(f"{batch_prefix}{get_text('starting_steamcmd')}")
            progress.setValue(base_progress + int(30 * progress_multiplier))
            QApplication.processEvents()
            
            # Команда SteamCMD для скачивания Workshop мода
            # Используем @NoPromptForPassword для ускорения
            cmd = [
                str(steamcmd_exe),
                "+@NoPromptForPassword", "1",  # Не запрашивать пароль
                "+@ShutdownOnFailedCommand", "1",  # Выходить при ошибке
                "+login", "anonymous",
                "+workshop_download_item", "550", addon_id,  # 550 = L4D2 App ID
                "+quit"
            ]
            
            # Запускаем SteamCMD
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(steamcmd_path),
                creationflags=subprocess.CREATE_NO_WINDOW,
                universal_newlines=True,
                bufsize=1
            )
            
            # Переменные для отслеживания прогресса
            import re
            import time
            import threading
            import queue
            
            current_progress = base_progress + int(30 * progress_multiplier)
            last_update_time = time.time()
            downloaded_bytes = 0
            total_bytes = 0
            last_downloaded = 0
            download_speed = 0
            last_ui_update = time.time()
            last_file_check = time.time()
            download_started = False
            
            # Путь где SteamCMD скачивает файлы
            workshop_download_path = steamcmd_path / "steamapps" / "workshop" / "downloads" / "550" / addon_id
            
            # Функция для чтения вывода в отдельном потоке
            output_queue = queue.Queue()
            
            def read_output():
                try:
                    for line in iter(process.stdout.readline, ''):
                        if line:
                            output_queue.put(line)
                except:
                    pass
            
            # Запускаем чтение в отдельном потоке
            reader_thread = threading.Thread(target=read_output, daemon=True)
            reader_thread.start()
            
            # Ждём завершения с обновлением прогресса
            status_text = get_text("steamcmd_initializing")
            is_downloading = False
            download_folder = steamcmd_path / "steamapps" / "workshop" / "downloads" / "550" / addon_id
            content_folder = steamcmd_path / "steamapps" / "workshop" / "content" / "550" / addon_id
            last_folder_check = time.time()
            last_folder_size = 0
            download_started = False
            
            while process.poll() is None:
                # Проверяем отмену
                if progress.wasCanceled():
                    process.kill()
                    progress.close()
                    import shutil
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return
                
                # Обрабатываем все доступные строки из очереди
                try:
                    while True:
                        line = output_queue.get_nowait()
                        line_lower = line.lower()
                        
                        # Выводим все строки для отладки
                        print(f"[SteamCMD] {line.strip()}")
                        
                        # Проверяем критические ошибки
                        if "fatal error" in line_lower:
                            # Проверяем ошибку нехватки места на диске
                            if "250мб" in line_lower or "250mb" in line_lower or "disk space" in line_lower or "свободного места" in line_lower:
                                process.kill()
                                progress.close_keeping_blur()
                                import shutil
                                shutil.rmtree(temp_dir, ignore_errors=True)
                                
                                QTimer.singleShot(350, lambda: CustomInfoDialog.information(
                                    self,
                                    get_text("insufficient_disk_space"),
                                    get_text("steamcmd_disk_space_message"),
                                    "3. Переустановите SteamCMD заново\n\n"
                                    "После этого попробуйте скачать моды снова.",
                                    use_existing_blur=True
                                ))
                                return
                            else:
                                # Другая критическая ошибка
                                error_msg = line.strip()
                                process.kill()
                                progress.close_keeping_blur()
                                import shutil
                                shutil.rmtree(temp_dir, ignore_errors=True)
                                
                                if batch_info:
                                    raise Exception(f"SteamCMD ошибка: {error_msg}")
                                else:
                                    QTimer.singleShot(350, lambda msg=error_msg: CustomInfoDialog.information(
                                        self,
                                        get_text("steamcmd_error_title"),
                                        get_text("steamcmd_critical_error", error=msg),
                                        use_existing_blur=True
                                    ))
                                    return
                        
                        # Отслеживаем различные этапы
                        if "loading steam api" in line_lower or "connecting" in line_lower:
                            status_text = "Подключение к Steam..."
                            progress.setLabelText(f"{batch_prefix}{status_text}")
                        elif "logging in" in line_lower or "anonymous" in line_lower:
                            status_text = "Авторизация..."
                            progress.setLabelText(f"{batch_prefix}{status_text}")
                        elif "waiting for" in line_lower or "checking" in line_lower:
                            status_text = "Проверка мода..."
                            progress.setLabelText(f"{batch_prefix}{status_text}")
                        elif "downloading" in line_lower and "workshop" in line_lower:
                            is_downloading = True
                            status_text = "Скачивание файлов..."
                            progress.setLabelText(f"{batch_prefix}{status_text}")
                        
                        # Парсим вывод SteamCMD для получения реального прогресса
                        # Формат: "Downloading item 123456 ... (X / Y bytes)"
                        download_match = re.search(r'(\d+)\s*/\s*(\d+)\s*bytes', line, re.IGNORECASE)
                        if download_match:
                            downloaded_bytes = int(download_match.group(1))
                            total_bytes = int(download_match.group(2))
                            
                            if total_bytes > 0:
                                # Вычисляем процент (30-70% диапазон для скачивания)
                                download_percent = (downloaded_bytes / total_bytes) * 40 + 30
                                # Учитываем batch прогресс
                                current_progress = base_progress + int(download_percent * progress_multiplier)
                                progress.setValue(current_progress)
                                
                                # Вычисляем скорость
                                current_time = time.time()
                                time_diff = current_time - last_update_time
                                if time_diff >= 0.5:  # Обновляем скорость каждые 0.5 сек
                                    bytes_diff = downloaded_bytes - last_downloaded
                                    download_speed = bytes_diff / time_diff if time_diff > 0 else 0
                                    last_downloaded = downloaded_bytes
                                    last_update_time = current_time
                                    
                                    # Форматируем размеры
                                    def format_bytes(bytes_val):
                                        if bytes_val < 1024:
                                            return f"{bytes_val} B"
                                        elif bytes_val < 1024 * 1024:
                                            return f"{bytes_val / 1024:.2f} KB"
                                        else:
                                            return f"{bytes_val / (1024 * 1024):.2f} MB"
                                    
                                    speed_str = format_bytes(download_speed) + "/s"
                                    downloaded_str = format_bytes(downloaded_bytes)
                                    total_str = format_bytes(total_bytes)
                                    
                                    status_text = "Скачивание файлов..."
                                    progress.setLabelText(
                                        f"{batch_prefix}{status_text}\n"
                                        f"{downloaded_str} / {total_str} ({speed_str})"
                                    )
                        
                        # Обновляем прогресс на основе текстовых сообщений
                        elif "downloading" in line_lower:
                            local_progress = base_progress + int(35 * progress_multiplier)
                            if current_progress < local_progress:
                                current_progress = local_progress
                                progress.setValue(current_progress)
                            if downloaded_bytes == 0:  # Если еще нет данных о размере
                                status_text = "Скачивание файлов..."
                                progress.setLabelText(f"{batch_prefix}{status_text}")
                        elif "success" in line_lower:
                            current_progress = base_progress + int(70 * progress_multiplier)
                            progress.setValue(current_progress)
                            status_text = "Проверка целостности..."
                            progress.setLabelText(f"{batch_prefix}{status_text}")
                
                except queue.Empty:
                    pass
                
                # Мониторим папки скачивания (проверяем каждые 0.5 сек для снижения нагрузки)
                current_time = time.time()
                if downloaded_bytes == 0 and current_time - last_folder_check >= 0.5:
                    try:
                        folder_size = 0
                        
                        # Проверяем папку downloads (ограничиваем глубину поиска для скорости)
                        if download_folder.exists():
                            try:
                                # Быстрый подсчет - только прямые файлы, без глубокой рекурсии
                                folder_size = sum(f.stat().st_size for f in download_folder.iterdir() if f.is_file())
                                # Если есть подпапки, проверяем их тоже (но не глубже)
                                for subdir in download_folder.iterdir():
                                    if subdir.is_dir():
                                        folder_size += sum(f.stat().st_size for f in subdir.iterdir() if f.is_file())
                            except:
                                pass
                        
                        # Если в downloads пусто, проверяем content (файлы уже скачаны)
                        if folder_size == 0 and content_folder.exists():
                            try:
                                folder_size = sum(f.stat().st_size for f in content_folder.iterdir() if f.is_file())
                                for subdir in content_folder.iterdir():
                                    if subdir.is_dir():
                                        folder_size += sum(f.stat().st_size for f in subdir.iterdir() if f.is_file())
                            except:
                                pass
                            
                            if folder_size > 0 and not download_started:
                                download_started = True
                                progress.setLabelText(f"{batch_prefix}{get_text('extracting_files')}")
                        
                        # Обновляем статус в зависимости от размера
                        if folder_size > 0:
                            # Вычисляем скорость
                            time_diff = current_time - last_folder_check
                            if last_folder_size > 0 and time_diff > 0:
                                size_diff = folder_size - last_folder_size
                                folder_speed = size_diff / time_diff
                                
                                # Форматируем размеры
                                def format_bytes(bytes_val):
                                    if bytes_val < 1024:
                                        return f"{bytes_val} B"
                                    elif bytes_val < 1024 * 1024:
                                        return f"{bytes_val / 1024:.2f} KB"
                                    else:
                                        return f"{bytes_val / (1024 * 1024):.2f} MB"
                                
                                size_str = format_bytes(folder_size)
                                speed_str = format_bytes(folder_speed) + "/s" if folder_speed > 0 else ""
                                
                                if not download_started:
                                    download_started = True
                                    is_downloading = True
                                
                                if speed_str:
                                    progress.setLabelText(
                                        f"{batch_prefix}Скачивание файлов...\n"
                                        f"{size_str} ({speed_str})"
                                    )
                                else:
                                    progress.setLabelText(
                                        f"{batch_prefix}Скачивание файлов...\n"
                                        f"{size_str}"
                                    )
                            elif folder_size > 0:
                                # Первый раз видим файлы
                                def format_bytes(bytes_val):
                                    if bytes_val < 1024:
                                        return f"{bytes_val} B"
                                    elif bytes_val < 1024 * 1024:
                                        return f"{bytes_val / 1024:.2f} KB"
                                    else:
                                        return f"{bytes_val / (1024 * 1024):.2f} MB"
                                
                                size_str = format_bytes(folder_size)
                                progress.setLabelText(
                                    f"{batch_prefix}Скачивание файлов...\n"
                                    f"{size_str}"
                                )
                            
                            last_folder_size = folder_size
                        else:
                            # Folder is empty or doesn't exist - show waiting status
                            if not download_started:
                                # Считаем сколько времени прошло с начала
                                elapsed = current_time - last_update_time
                                if elapsed > 3:  # Если прошло больше 3 секунд
                                    progress.setLabelText(f"{batch_prefix}{get_text('waiting_steamcmd_data')}")
                        
                        last_folder_check = current_time
                    except Exception as e:
                        print(f"[DEBUG] Ошибка мониторинга папки: {e}")
                
                # Принудительно обновляем UI чаще для плавности (каждые 50мс)
                if current_time - last_ui_update >= 0.05:
                    QApplication.processEvents()
                    last_ui_update = current_time
                
                # Небольшая задержка чтобы не нагружать CPU (уменьшена для плавности)
                time.sleep(0.03)
            
            process.wait()
            
            progress.setValue(base_progress + int(72 * progress_multiplier))
            progress.setLabelText(f"{batch_prefix}{get_text('finishing_download')}")
            QApplication.processEvents()
            
            # Даем SteamCMD время переместить файлы
            time.sleep(1)
            
            # Путь к скачанному моду
            workshop_content = steamcmd_path / "steamapps" / "workshop" / "content" / "550" / addon_id
            
            print(f"[DEBUG] Проверка папки: {workshop_content}")
            
            # Умное ожидание: если есть активность скачивания - ждем 30 сек, иначе 3 минуты
            wait_attempts = 0
            max_wait_with_activity = 60  # 60 попыток × 0.5 сек = 30 секунд (если идет скачивание)
            max_wait_no_activity = 360  # 360 попыток × 0.5 сек = 3 минуты (если нет активности)
            last_check_time = time.time()
            
            # Проверяем альтернативные пути во время ожидания
            workshop_downloads = steamcmd_path / "steamapps" / "workshop" / "downloads" / "550" / addon_id
            
            # Переменные для отслеживания активности
            download_activity_detected = False
            last_download_size = 0
            no_activity_start = None
            
            while not workshop_content.exists():
                elapsed_seconds = int(wait_attempts * 0.5)
                
                # Проверяем, идет ли еще скачивание (есть ли активность в downloads)
                download_activity = False
                current_download_size = 0
                
                if workshop_downloads.exists():
                    try:
                        # Проверяем размер папки downloads
                        current_download_size = sum(f.stat().st_size for f in workshop_downloads.rglob('*') if f.is_file())
                        
                        if current_download_size > 0:
                            download_activity = True
                            download_activity_detected = True
                            
                            # Проверяем, растет ли размер (идет ли активное скачивание)
                            if current_download_size > last_download_size:
                                no_activity_start = None  # Сбрасываем таймер неактивности
                            elif no_activity_start is None:
                                no_activity_start = time.time()  # Начинаем отсчет неактивности
                            
                            last_download_size = current_download_size
                            
                            # Форматируем размер
                            def format_bytes(bytes_val):
                                if bytes_val < 1024:
                                    return f"{bytes_val} B"
                                elif bytes_val < 1024 * 1024:
                                    return f"{bytes_val / 1024:.2f} KB"
                                else:
                                    return f"{bytes_val / (1024 * 1024):.2f} MB"
                            
                            size_str = format_bytes(current_download_size)
                            
                            # Определяем максимальное время ожидания
                            max_wait = max_wait_with_activity if download_activity_detected else max_wait_no_activity
                            max_seconds = max_wait // 2
                            
                            progress.setLabelText(
                                f"{batch_prefix}Скачивание в процессе...\n"
                                f"Загружено: {size_str} (ожидание {elapsed_seconds}s / {max_seconds}s)"
                            )
                        else:
                            # Папка downloads пустая
                            max_wait = max_wait_with_activity if download_activity_detected else max_wait_no_activity
                            max_seconds = max_wait // 2
                            
                            progress.setLabelText(
                                f"{batch_prefix}Ожидание завершения скачивания...\n"
                                f"({elapsed_seconds}s / {max_seconds}s)"
                            )
                    except Exception as e:
                        print(f"[DEBUG] Ошибка проверки downloads: {e}")
                        max_wait = max_wait_with_activity if download_activity_detected else max_wait_no_activity
                        max_seconds = max_wait // 2
                        
                        progress.setLabelText(
                            f"{batch_prefix}Ожидание завершения скачивания...\n"
                            f"({elapsed_seconds}s / {max_seconds}s)"
                        )
                else:
                    # Папка downloads не существует
                    max_wait = max_wait_with_activity if download_activity_detected else max_wait_no_activity
                    max_seconds = max_wait // 2
                    
                    progress.setLabelText(
                        f"{batch_prefix}Ожидание завершения скачивания...\n"
                        f"({elapsed_seconds}s / {max_seconds}s)"
                    )
                
                # Определяем лимит ожидания в зависимости от активности
                if download_activity_detected:
                    # Если была обнаружена активность скачивания - ждем только 30 секунд
                    current_max_wait = max_wait_with_activity
                    
                    # Дополнительная проверка: если размер не меняется более 10 секунд - прерываем
                    if no_activity_start and (time.time() - no_activity_start) > 10:
                        print(f"[DEBUG] Размер не меняется более 10 секунд, прерываем ожидание")
                        break
                else:
                    # Если активности не было - ждем 3 минуты (мод может быть недоступен)
                    current_max_wait = max_wait_no_activity
                
                # Проверяем превышение лимита
                if wait_attempts >= current_max_wait:
                    print(f"[DEBUG] Достигнут лимит ожидания: {wait_attempts} попыток ({elapsed_seconds}s)")
                    break
                
                print(f"[DEBUG] Папка не найдена, ожидание... ({wait_attempts + 1}/{current_max_wait}, {elapsed_seconds}s, активность: {download_activity})")
                
                time.sleep(0.5)
                wait_attempts += 1
                QApplication.processEvents()
                
                # Проверяем отмену
                if progress.wasCanceled():
                    import shutil
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return
            
            if not workshop_content.exists():
                print(f"[DEBUG] Мод {addon_id} не найден после скачивания (ожидание {wait_attempts * 0.5}s)")
                
                # Детальная диагностика
                diagnostic_info = []
                
                # Проверяем альтернативные пути (иногда SteamCMD сохраняет в downloads)
                workshop_downloads = steamcmd_path / "steamapps" / "workshop" / "downloads" / "550" / addon_id
                if workshop_downloads.exists():
                    print(f"[DEBUG] Мод найден в downloads, но не перемещен в content")
                    try:
                        downloads_content = list(workshop_downloads.iterdir())
                        print(f"[DEBUG] Содержимое downloads: {downloads_content}")
                        
                        # Проверяем размер
                        download_size = sum(f.stat().st_size for f in workshop_downloads.rglob('*') if f.is_file())
                        def format_bytes(bytes_val):
                            if bytes_val < 1024:
                                return f"{bytes_val} B"
                            elif bytes_val < 1024 * 1024:
                                return f"{bytes_val / 1024:.2f} KB"
                            else:
                                return f"{bytes_val / (1024 * 1024):.2f} MB"
                        
                        if download_size > 0:
                            diagnostic_info.append(f"• Найдены файлы в downloads ({format_bytes(download_size)})")
                            diagnostic_info.append("• Возможно, скачивание не завершилось")
                        else:
                            diagnostic_info.append("• Папка downloads пустая")
                    except Exception as e:
                        diagnostic_info.append(f"• Ошибка проверки downloads: {e}")
                else:
                    diagnostic_info.append("• Папка downloads не создана")
                
                # Проверяем логи SteamCMD
                steamcmd_log = steamcmd_path / "logs" / "workshop_log.txt"
                if steamcmd_log.exists():
                    try:
                        with open(steamcmd_log, 'r', encoding='utf-8', errors='ignore') as f:
                            log_lines = f.readlines()[-10:]  # Последние 10 строк
                            for line in log_lines:
                                if "error" in line.lower() or "failed" in line.lower():
                                    diagnostic_info.append(f"• Лог: {line.strip()}")
                    except:
                        pass
                
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
                
                # Формируем сообщение об ошибке
                diagnostic_text = "\n".join(diagnostic_info) if diagnostic_info else "Нет дополнительной информации"
                
                # Если это batch скачивание - просто выбрасываем исключение чтобы счетчик failed увеличился
                if batch_info:
                    # Более информативное сообщение об ошибке
                    if "downloads" in diagnostic_text and "MB" in diagnostic_text:
                        raise Exception(get_text("download_timeout_error"))
                    else:
                        raise Exception(get_text("mod_unavailable_or_removed"))
                else:
                    # Если одиночное скачивание - показываем ошибку
                    progress.close_keeping_blur()
                    
                    # Определяем тип ошибки для более точного сообщения
                    if "downloads" in diagnostic_text and "MB" in diagnostic_text:
                        error_title = "Таймаут скачивания"
                        # Определяем какой таймаут использовался
                        timeout_used = max_wait_with_activity if download_activity_detected else max_wait_no_activity
                        timeout_seconds = timeout_used // 2
                        
                        error_message = (
                            f"{get_text('download_timeout_seconds', addon_id=addon_id, timeout_seconds=timeout_seconds)}\n\n"
                            f"{get_text('diagnostics')}\n{diagnostic_text}\n\n"
                            f"{get_text('what_to_do')}\n"
                            f"{get_text('try_download_again')}\n"
                            f"{get_text('check_internet_speed')}\n"
                            f"{get_text('large_mods_time')}\n"
                            f"{get_text('workshop_download_direct')}"
                        )
                    else:
                        error_title = get_text("mod_unavailable_title")
                        error_message = (
                            f"{get_text('failed_to_download_mod', addon_id=addon_id)}\n\n"
                            f"{get_text('diagnostics')}\n{diagnostic_text}\n\n"
                            f"{get_text('most_likely_causes')}\n"
                            f"{get_text('workshop_mod_removed')}\n"
                            f"{get_text('workshop_mod_private')}\n"
                            f"{get_text('workshop_mod_blocked')}\n"
                            f"{get_text('workshop_connection_issues')}\n\n"
                            f"{get_text('what_to_do')}\n"
                            f"{get_text('workshop_check_browser')}\n"
                            f"{get_text('workshop_try_steam')}\n"
                            f"{get_text('workshop_find_alternative')}"
                        )
                    
                    QTimer.singleShot(350, lambda: CustomInfoDialog.information(
                        self,
                        error_title,
                        error_message,
                        use_existing_blur=True
                    ))
                    return
            
            progress.setValue(base_progress + int(75 * progress_multiplier))
            progress.setLabelText(f"{batch_prefix}{get_text('searching_vpk_files')}")
            QApplication.processEvents()
            
            # Копируем файлы в папку addons
            addons_dir = self.game_folder / "left4dead2" / "addons"
            addons_dir.mkdir(parents=True, exist_ok=True)
            
            # Ищем .vpk файлы (оптимизированный поиск - только 2 уровня)
            vpk_files = []
            try:
                # Сначала проверяем корневую папку
                vpk_files = [f for f in workshop_content.iterdir() if f.is_file() and f.suffix == '.vpk']
                # Если не найдено, проверяем подпапки (1 уровень)
                if not vpk_files:
                    for subdir in workshop_content.iterdir():
                        if subdir.is_dir():
                            vpk_files.extend([f for f in subdir.iterdir() if f.is_file() and f.suffix == '.vpk'])
            except:
                pass
            
            print(f"[DEBUG] {get_text('found_vpk_files_debug', count=len(vpk_files))}")
            
            # Если .vpk не найдены, ищем .bin файлы (формат SteamCMD)
            if not vpk_files:
                try:
                    bin_files = [f for f in workshop_content.iterdir() if f.is_file() and f.suffix == '.bin']
                    if not bin_files:
                        for subdir in workshop_content.iterdir():
                            if subdir.is_dir():
                                bin_files.extend([f for f in subdir.iterdir() if f.is_file() and f.suffix == '.bin'])
                except:
                    bin_files = []
                
                if bin_files:
                    # .bin файлы - это на самом деле .vpk файлы, просто переименованные
                    print(f"[DEBUG] Найдено {len(bin_files)} .bin файлов, будут обработаны как .vpk")
                    vpk_files = bin_files
                else:
                    # Если ничего не найдено - проверяем все файлы в папке с детальной информацией
                    try:
                        all_files = []
                        total_size = 0
                        file_types = {}
                        
                        # Собираем все файлы (до 30 штук для отображения)
                        for item in workshop_content.rglob('*'):
                            if item.is_file():
                                file_size = item.stat().st_size
                                total_size += file_size
                                
                                # Считаем типы файлов
                                ext = item.suffix.lower()
                                file_types[ext] = file_types.get(ext, 0) + 1
                                
                                # Форматируем размер
                                def format_bytes(bytes_val):
                                    if bytes_val < 1024:
                                        return f"{bytes_val} B"
                                    elif bytes_val < 1024 * 1024:
                                        return f"{bytes_val / 1024:.1f} KB"
                                    else:
                                        return f"{bytes_val / (1024 * 1024):.1f} MB"
                                
                                # Относительный путь от workshop_content
                                rel_path = item.relative_to(workshop_content)
                                all_files.append(f"- {rel_path} ({format_bytes(file_size)})")
                                
                                if len(all_files) >= 30:
                                    all_files.append("- ... (и другие)")
                                    break
                        
                        # Форматируем общий размер
                        def format_bytes(bytes_val):
                            if bytes_val < 1024:
                                return f"{bytes_val} B"
                            elif bytes_val < 1024 * 1024:
                                return f"{bytes_val / 1024:.1f} KB"
                            else:
                                return f"{bytes_val / (1024 * 1024):.1f} MB"
                        
                        total_size_str = format_bytes(total_size)
                        
                        # Формируем статистику по типам файлов
                        file_types_str = ", ".join([f"{ext or '[без расширения]'}: {count}" for ext, count in sorted(file_types.items())])
                        
                        if not all_files:
                            file_list = get_text("folder_empty")
                            file_stats = ""
                        else:
                            file_list = "\n".join(all_files)
                            file_stats = f"\n\nСтатистика:\n• Всего файлов: {len(all_files)}\n• Общий размер: {total_size_str}\n• Типы файлов: {file_types_str}"
                    except Exception as e:
                        file_list = f"Не удалось прочитать содержимое папки: {e}"
                        file_stats = ""
                    
                    print(f"[DEBUG] В моде {addon_id} не найдено VPK файлов. Файлы:\n{file_list}{file_stats}")
                    
                    import shutil
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    
                    # Если это batch скачивание - просто выбрасываем исключение
                    if batch_info:
                        raise Exception(get_text("no_vpk_found_batch", types=file_types_str))
                    else:
                        # Если одиночное скачивание - показываем ошибку
                        progress.close_keeping_blur()
                        
                        # Небольшая задержка для плавности
                        QApplication.processEvents()
                        import time
                        time.sleep(0.35)
                        
                        # Определяем тип контента для более точного сообщения
                        if '.txt' in file_types or '.md' in file_types:
                            content_type = get_text("possibly_description")
                        elif '.jpg' in file_types or '.png' in file_types:
                            content_type = get_text("possibly_images")
                        elif not file_types:
                            content_type = get_text("folder_empty_subfolders")
                        else:
                            content_type = get_text("unknown_content_type")
                        
                        CustomInfoDialog.information(
                            self,
                            get_text("vpk_files_not_found"),
                            f"{get_text('no_vpk_bin_files_found')}\n\n"
                            f"{get_text('found_files')}\n{file_list}{file_stats}\n\n"
                            f"{content_type}\n\n"
                            f"{get_text('possible_causes')}\n"
                            f"{get_text('mod_collection_no_files')}\n"
                            f"{get_text('mod_different_format')}\n"
                            f"{get_text('mod_corrupted')}\n"
                            f"{get_text('not_game_content')}\n\n"
                            f"{get_text('what_to_do')}\n"
                            f"{get_text('check_mod_workshop')}\n"
                            f"{get_text('download_steam_direct')}\n"
                            f"{get_text('collection_download_separate')}",
                            use_existing_blur=True
                        )
                        return
            
            # Копируем .vpk файлы
            import re
            # Очищаем имя от всех недопустимых символов Windows
            safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', addon_name)
            # Убираем точки в конце (Windows не разрешает)
            safe_name = safe_name.rstrip('. ')
            # Ограничиваем длину
            safe_name = safe_name[:50]
            # Если после очистки имя пустое, используем ID
            if not safe_name or safe_name == '_':
                safe_name = f'addon_{addon_id}'
            
            progress.setValue(base_progress + int(80 * progress_multiplier))
            progress.setLabelText(f"{batch_prefix}{get_text('copying_files')}")
            QApplication.processEvents()
            
            copied_files = []
            for i, vpk_file in enumerate(vpk_files):
                # Показываем какой файл копируем
                progress.setLabelText(f"{batch_prefix}{get_text('copying_files_progress', current=i+1, total=len(vpk_files))}")
                QApplication.processEvents()
                
                if len(vpk_files) == 1:
                    new_name = f"{safe_name}.vpk"
                else:
                    new_name = f"{safe_name}_{i+1}.vpk"
                
                dest_file = addons_dir / new_name
                
                # Если файл существует, добавляем суффикс
                counter = 1
                while dest_file.exists():
                    if len(vpk_files) == 1:
                        new_name = f"{safe_name}_{counter}.vpk"
                    else:
                        new_name = f"{safe_name}_{i+1}_{counter}.vpk"
                    dest_file = addons_dir / new_name
                    counter += 1
                
                import shutil
                
                # Получаем размер файла
                file_size = vpk_file.stat().st_size
                def format_bytes(bytes_val):
                    if bytes_val < 1024:
                        return f"{bytes_val} B"
                    elif bytes_val < 1024 * 1024:
                        return f"{bytes_val / 1024:.2f} KB"
                    else:
                        return f"{bytes_val / (1024 * 1024):.2f} MB"
                
                size_str = format_bytes(file_size)
                progress.setLabelText(f"{batch_prefix}{get_text('copying_files_with_size', current=i+1, total=len(vpk_files), size=size_str)}")
                
                shutil.copy2(vpk_file, dest_file)
                copied_files.append(new_name)
                
                # Обновляем прогресс для каждого файла с учетом batch
                file_progress = 80 + (i + 1) / len(vpk_files) * 15
                progress.setValue(base_progress + int(file_progress * progress_multiplier))
                QApplication.processEvents()
            
            progress.setValue(base_progress + int(95 * progress_multiplier))
            progress.setLabelText(f"{batch_prefix}{get_text('updating_list')}")
            QApplication.processEvents()
            
            # Обновляем список пиратских аддонов
            self.scan_pirate_addons()
            
            # Устанавливаем финальный прогресс для текущего мода
            progress.setValue(base_progress + int(100 * progress_multiplier))
            
            # Закрываем прогресс только если это не existing_progress и последний мод
            if not existing_progress:
                if not batch_info or batch_info[0] == batch_info[1]:
                    progress.close_keeping_blur()
                else:
                    # Если это не последний мод, просто обновляем UI
                    QApplication.processEvents()
            else:
                # Если используем existing_progress, просто обновляем UI
                QApplication.processEvents()
            
            # Показываем успешное сообщение только если это не массовое скачивание
            if show_success_message:
                files_list = "\n".join(copied_files)
                QTimer.singleShot(350, lambda: CustomInfoDialog.information(
                    self,
                    get_text("success_title"),
                    get_text("mod_download_success", name=addon_name, count=len(copied_files), path=str(dest_file.parent)),
                    get_text("go_to_pirate_tab"),
                    use_existing_blur=True
                ))
            
            # Очищаем временные файлы
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
            
        except Exception as e:
            if 'progress' in locals():
                # Закрываем прогресс только если это не batch или последний в batch
                if not batch_info or batch_info[0] == batch_info[1]:
                    progress.close_keeping_blur()
                    
                    # Небольшая задержка для плавности
                    QApplication.processEvents()
                    import time
                    time.sleep(0.35)
            
            # Формируем понятное сообщение об ошибке
            error_msg = str(e)
            if "WinError" in error_msg and "123" in error_msg:
                error_msg = get_text("syntax_error_filename")
            else:
                error_msg = get_text("failed_download_auto", error=error_msg)
            
            # Показываем ошибку только если это не batch скачивание
            # При batch ошибки будут показаны в итоговом сообщении
            if not batch_info:
                CustomInfoDialog.information(
                    self,
                    get_text("error_title"),
                    error_msg,
                    use_existing_blur=True if 'progress' in locals() else False
                )
            else:
                # При batch просто выбрасываем исключение дальше
                raise
    
    def get_workshop_addon_info(self, addon_id):
        """Получает информацию об аддоне из Steam API"""
        try:
            from urllib.request import urlopen
            import json
            
            data = f"itemcount=1&publishedfileids[0]={addon_id}".encode('utf-8')
            response = urlopen(STEAM_API_URL, data=data, timeout=5)
            result = json.loads(response.read().decode('utf-8'))
            
            if result.get('response', {}).get('publishedfiledetails'):
                details = result['response']['publishedfiledetails'][0]
                if details.get('result') == 1:
                    return {
                        'title': details.get('title', f'Аддон {addon_id}'),
                        'description': self.clean_bbcode(details.get('description', '')),
                        'preview_url': details.get('preview_url', ''),
                        'type': details.get('consumer_app_id', 0)  # Тип: коллекция или мод
                    }
        except:
            pass
        
        return {
            'title': f'Аддон {addon_id}',
            'description': '',
            'preview_url': '',
            'type': 0
        }
    
    def get_collection_items(self, collection_id):
        """Получает список модов из коллекции Steam"""
        try:
            from urllib.request import urlopen
            import json
            
            print(f"[DEBUG] Запрос коллекции ID: {collection_id}")
            
            # Сначала получаем информацию о коллекции
            data = f"itemcount=1&publishedfileids[0]={collection_id}".encode('utf-8')
            response = urlopen(STEAM_API_URL, data=data, timeout=10)
            result = json.loads(response.read().decode('utf-8'))
            
            print(f"[DEBUG] Ответ API: {json.dumps(result, indent=2, ensure_ascii=False)[:1000]}")
            
            if result.get('response', {}).get('publishedfiledetails'):
                details = result['response']['publishedfiledetails'][0]
                
                print(f"[DEBUG] Тип файла: {details.get('file_type', 'unknown')}")
                print(f"[DEBUG] Consumer app id: {details.get('consumer_app_id', 'unknown')}")
                print(f"[DEBUG] Количество children: {len(details.get('children', []))}")
                
                # Проверяем что это коллекция
                # file_type может быть 0 (коллекция) или другое значение
                if details.get('result') == 1:
                    # Получаем список дочерних элементов
                    children = details.get('children', [])
                    
                    print(f"[DEBUG] Children: {children[:5]}")  # Первые 5 для отладки
                    
                    if children and len(children) > 0:
                        # Извлекаем ID модов
                        addon_ids = [child.get('publishedfileid') for child in children if child.get('publishedfileid')]
                        collection_title = details.get('title', f'Коллекция {collection_id}')
                        
                        print(f"[DEBUG] Найдено модов в коллекции: {len(addon_ids)}")
                        
                        return {
                            'title': collection_title,
                            'addon_ids': addon_ids,
                            'count': len(addon_ids)
                        }
                    else:
                        print(f"[DEBUG] Нет children, возможно это не коллекция")
                        # Пробуем альтернативный метод - парсинг HTML
                        return self.get_collection_items_from_html(collection_id)
        except Exception as e:
            import traceback
            print(f"[DEBUG] Ошибка при получении коллекции через API: {e}")
            print(f"[DEBUG] Traceback: {traceback.format_exc()}")
            # Пробуем альтернативный метод
            return self.get_collection_items_from_html(collection_id)
        
        return None
    
    def get_collection_items_from_html(self, collection_id):
        """Получает список модов из коллекции парсингом HTML страницы"""
        try:
            from urllib.request import urlopen, Request
            import re
            
            print(f"[DEBUG] Пробуем получить коллекцию через HTML парсинг")
            
            # Загружаем HTML страницу коллекции
            url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={collection_id}"
            headers = {'User-Agent': 'Mozilla/5.0'}
            request = Request(url, headers=headers)
            response = urlopen(request, timeout=10)
            html = response.read().decode('utf-8')
            
            # Ищем все ID модов в коллекции
            # Формат: sharedfiles/filedetails/?id=XXXXXXXXX
            pattern = r'sharedfiles/filedetails/\?id=(\d+)'
            matches = re.findall(pattern, html)
            
            # Убираем дубликаты и сам ID коллекции
            addon_ids = list(set(matches))
            if collection_id in addon_ids:
                addon_ids.remove(collection_id)
            
            print(f"[DEBUG] Найдено модов через HTML: {len(addon_ids)}")
            
            if addon_ids:
                # Пытаемся получить название коллекции
                title_match = re.search(r'<div class="workshopItemTitle">([^<]+)</div>', html)
                collection_title = title_match.group(1) if title_match else f'Коллекция {collection_id}'
                
                return {
                    'title': collection_title,
                    'addon_ids': addon_ids,
                    'count': len(addon_ids)
                }
        except Exception as e:
            import traceback
            print(f"[DEBUG] Ошибка при HTML парсинге: {e}")
            print(f"[DEBUG] Traceback: {traceback.format_exc()}")
        
        return None
    
    def manage_steamcmd(self, use_existing_blur=False):
        """Управление SteamCMD - показывает информацию и позволяет переустановить или удалить"""
        # Определяем папку программы
        if getattr(sys, 'frozen', False):
            program_dir = Path(sys.executable).parent
        else:
            program_dir = Path(__file__).parent
        
        steamcmd_path = program_dir / "steamcmd"
        steamcmd_exe = steamcmd_path / "steamcmd.exe"
        
        if not steamcmd_exe.exists():
            CustomInfoDialog.information(
                self,
                "SteamCMD не установлен",
                "SteamCMD не найден.\n\n"
                "Он будет автоматически установлен при первом скачивании мода.",
                use_existing_blur=use_existing_blur
            )
            return
        
        # Создаем кастомный диалог в стиле CustomConfirmDialog
        dialog = CustomSteamCMDManageDialog(self, steamcmd_path, use_existing_blur=use_existing_blur)
        result = dialog.exec()
        
        if result == 1:  # Переустановить
            self.reinstall_steamcmd(None, steamcmd_path)
        elif result == 2:  # Удалить
            self.delete_steamcmd(None, steamcmd_path)
    
    def reinstall_steamcmd(self, parent_dialog, steamcmd_path):
        """Переустанавливает SteamCMD"""
        # Небольшая задержка для корректного закрытия
        QApplication.processEvents()
        
        # Потом показываем подтверждение
        reply = CustomConfirmDialog.question(
            self,
            "Переустановить SteamCMD?",
            "Это удалит текущую установку SteamCMD и скачает её заново.\n\n"
            "Продолжить?"
        )
        
        if not reply:
            return
        
        # Удаляем старую установку
        try:
            import shutil
            if steamcmd_path.exists():
                shutil.rmtree(steamcmd_path)
        except Exception as e:
            CustomInfoDialog.information(
                self,
                get_text("error_title"),
                get_text("delete_old_installation_error", error=str(e))
            )
            return
        
        # Устанавливаем заново
        result = self.ensure_steamcmd_installed(use_existing_blur=False)
    
    def delete_steamcmd(self, parent_dialog, steamcmd_path):
        """Удаляет SteamCMD"""
        # Небольшая задержка для корректного закрытия
        QApplication.processEvents()
        
        # Потом показываем подтверждение
        reply = CustomConfirmDialog.question(
            self,
            "Удалить SteamCMD?",
            "Это удалит SteamCMD с вашего компьютера.\n\n"
            "Вы сможете установить его снова при необходимости.\n\n"
            "Продолжить?"
        )
        
        if not reply:
            return
        
        # Удаляем
        try:
            import shutil
            if steamcmd_path.exists():
                shutil.rmtree(steamcmd_path)
            
            CustomInfoDialog.information(
                self,
                "Успешно",
                "SteamCMD успешно удалён."
            )
            
        except Exception as e:
            CustomInfoDialog.information(
                self,
                get_text("error_title"),
                get_text("delete_steamcmd_error", error=str(e))
            )
    
    def download_from_workshop(self):
        """Скачивает мод из Steam Workshop через SteamCMD"""
        if not self.game_folder:
            CustomInfoDialog.information(self, get_text("error_title"), get_text("specify_game_folder_first"), icon_type="error")
            return
        
        # Проверяем, установлен ли SteamCMD
        if getattr(sys, 'frozen', False):
            program_dir = Path(sys.executable).parent
        else:
            program_dir = Path(__file__).parent
        
        steamcmd_exe = program_dir / "steamcmd" / "steamcmd.exe"
        show_steamcmd_btn = steamcmd_exe.exists()
        
        # Диалог ввода ссылки или ID с кастомным стилем
        dialog = CustomInputDialog(
            self,
            get_text("download_from_workshop"),
            f"{get_text('workshop_download_prompt')}\n\n{get_text('workshop_download_example')}",
            "",
            show_steamcmd_btn=show_steamcmd_btn,
            use_existing_blur=False
        )
        
        # Запускаем диалог
        result = dialog.exec()
        
        # Проверяем, нажали ли на кнопку настроек SteamCMD
        if dialog.steamcmd_clicked:
            # Открываем настройки SteamCMD с существующим блюром
            self.manage_steamcmd(use_existing_blur=True)
            
            # После закрытия настроек SteamCMD убираем blur перед возвратом
            # Проверяем есть ли blur на главном окне или центральном виджете
            if self.graphicsEffect():
                self.setGraphicsEffect(None)
            central_widget = self.centralWidget()
            if central_widget and central_widget.graphicsEffect():
                central_widget.setGraphicsEffect(None)
            
            # Если пользователь нажал "Отмена" в настройках SteamCMD, просто возвращаемся
            # Не показываем диалог снова
            return
            
            if result != QDialog.DialogCode.Accepted:
                return
            
            url = dialog2.input_text
            if not url:
                return
            
            # Извлекаем ID из ссылки или используем как есть
            import re
            match = re.search(r'id=(\d+)', url)
            if match:
                addon_id = match.group(1)
            elif url.strip().isdigit():
                addon_id = url.strip()
            else:
                CustomInfoDialog.information(self, get_text("error_title"), get_text("invalid_format_error"), use_existing_blur=True, icon_type="error")
                return
            
            # Сразу начинаем скачивание через SteamCMD
            try:
                self.auto_download_workshop_addon(addon_id, use_existing_blur=True)
            except Exception as e:
                import traceback
                error_msg = f"Ошибка при скачивании:\n{str(e)}\n\n{traceback.format_exc()}"
                print(error_msg)
                CustomInfoDialog.information(self, get_text("error_title"), get_text("unexpected_error", error=str(e)), use_existing_blur=True, icon_type="error")
            return
        
        if result != QDialog.DialogCode.Accepted:
            return
        
        urls = dialog.input_text
        if not urls:
            return
        
        # Проверяем, список это или одна ссылка
        if isinstance(urls, list):
            # Список ссылок - скачиваем все
            self.download_multiple_addons(urls)
        else:
            # Одна ссылка
            import re
            match = re.search(r'id=(\d+)', urls)
            if match:
                addon_id = match.group(1)
            elif urls.strip().isdigit():
                addon_id = urls.strip()
            else:
                CustomInfoDialog.information(self, get_text("error_title"), get_text("invalid_format_error"), icon_type="error")
                return
            
            # Проверяем, это коллекция или отдельный мод
            print(f"[DEBUG] Проверка ID: {addon_id}")
            
            try:
                # Показываем прогресс проверки
                check_progress = CustomProgressDialog(
                    self,
                    "Проверка...",
                    "",
                    0,
                    0,  # Неопределенный прогресс
                    use_existing_blur=False
                )
                check_progress.show()
                check_progress.setLabelText(get_text("checking_content_type"))
                QApplication.processEvents()
                
                collection_info = self.get_collection_items(addon_id)
                
                check_progress.close_keeping_blur()
                
                # Небольшая задержка для плавности
                QApplication.processEvents()
                import time
                time.sleep(0.1)
                
                if collection_info and collection_info.get('count', 0) > 0:
                    # Это коллекция - показываем подтверждение с блюром
                    dialog = CustomConfirmDialog(
                        self,
                        get_text("download_collection_title"),
                        get_text("download_collection_message", 
                            title=collection_info['title'], 
                            count=collection_info['count']
                        ),
                        use_existing_blur=True
                    )
                    reply_code = dialog.exec()
                    reply = reply_code == dialog.DialogCode.Accepted
                    
                    if reply:
                        # Скачиваем все моды из коллекции
                        addon_ids = collection_info['addon_ids']
                        if addon_ids and len(addon_ids) > 0:
                            # Преобразуем в список ссылок для download_multiple_addons
                            urls_list = [str(aid) for aid in addon_ids]
                            self.download_multiple_addons(urls_list)
                        else:
                            CustomInfoDialog.information(
                                self, 
                                get_text("error_title"), 
                                get_text("collection_error_message"),
                                use_existing_blur=True
                            )
                    # Если отказались, просто закрываем блюр
                    else:
                        # Закрываем блюр
                        if hasattr(self, 'blur_effect') and self.blur_effect:
                            self.blur_effect.deleteLater()
                            self.blur_effect = None
                else:
                    # Это обычный мод - скачиваем
                    self.auto_download_workshop_addon(addon_id, use_existing_blur=True)
                    
            except Exception as e:
                import traceback
                error_msg = f"Ошибка при проверке контента:\n{str(e)}\n\n{traceback.format_exc()}"
                print(error_msg)
                
                # Закрываем прогресс если он открыт
                if 'check_progress' in locals():
                    try:
                        check_progress.close()
                    except:
                        pass
                
                CustomInfoDialog.information(
                    self, 
                    get_text("error_title"), 
                    get_text("download_error_message", error=str(e))
                )
                return
    
    def download_multiple_addons(self, urls):
        """Скачивает несколько аддонов из списка ссылок"""
        import re
        
        # Извлекаем ID из всех ссылок
        addon_ids = []
        for url in urls:
            match = re.search(r'id=(\d+)', url)
            if match:
                addon_ids.append(match.group(1))
            elif url.strip().isdigit():
                addon_ids.append(url.strip())
        
        if not addon_ids:
            CustomInfoDialog.information(self, get_text("error_title"), get_text("no_valid_links_error"), icon_type="error")
            return
        
        # Показываем подтверждение
        reply = CustomConfirmDialog.question(
            self,
            get_text("download_multiple_title"),
            get_text("download_multiple_message", count=len(addon_ids))
        )
        
        if not reply:
            return
        
        # Создаем один прогресс-диалог для всех модов
        progress = CustomProgressDialog(
            self,
            get_text("downloading_mods"),
            "Отмена",
            0,
            100,
            use_existing_blur=False
        )
        progress.show()
        QApplication.processEvents()
        
        # Скачиваем все моды по очереди
        success_count = 0
        failed_count = 0
        failed_mods = []  # Список неудачных модов с причинами
        
        for i, addon_id in enumerate(addon_ids):
            # Проверяем отмену
            if progress.wasCanceled():
                progress.close()
                return
            
            try:
                # Показываем прогресс в заголовке
                print(f"Скачивание {i+1}/{len(addon_ids)}: {addon_id}")
                # Передаем существующий прогресс-диалог и информацию о batch
                self.auto_download_workshop_addon(
                    addon_id, 
                    use_existing_blur=True,  # Всегда True т.к. прогресс уже создан
                    show_success_message=False,
                    batch_info=(i + 1, len(addon_ids)),  # (текущий, всего)
                    existing_progress=progress  # Передаем существующий прогресс
                )
                success_count += 1
            except Exception as e:
                error_msg = str(e)
                print(f"Ошибка при скачивании {addon_id}: {error_msg}")
                failed_count += 1
                failed_mods.append((addon_id, error_msg))
        
        # Закрываем прогресс-диалог
        progress.close_keeping_blur()
        
        # Небольшая задержка для плавности
        QApplication.processEvents()
        import time
        time.sleep(0.35)
        
        # Показываем итоговое сообщение
        result_msg = get_text("download_completed", success=success_count, failed=failed_count if failed_count > 0 else 0)
        
        CustomInfoDialog.information(self, get_text("ready_title"), result_msg, use_existing_blur=True, icon_type="success")
    
    def filter_addons(self, search_text):
        """Фильтрует аддоны по поисковому запросу (быстрая версия)"""
        search_text = search_text.lower()
        
        visible_count = 0
        enabled_count = 0
        
        # Просто скрываем/показываем существующие карточки
        for i in range(self.addons_layout.count() - 1):  # -1 чтобы не трогать spacer
            widget = self.addons_layout.itemAt(i).widget()
            if isinstance(widget, AnimatedCard):
                addon = widget.addon
                # Проверяем совпадение
                matches = (search_text in addon['name'].lower() or 
                          search_text in addon.get('description', '').lower())
                
                widget.setVisible(matches)
                
                if matches:
                    visible_count += 1
                    if addon.get('enabled'):
                        enabled_count += 1
        
        # Обновляем счетчик
        if search_text:
            counter_text = get_text("counter_found", visible=visible_count, enabled=enabled_count)
        else:
            total = sum(1 for a in self.addons if a.get('enabled'))
            counter_text = get_text("addons_counter", total=len(self.addons), enabled=total)
        
        # Используем вспомогательную функцию для установки текста
        self.set_counter_text(self.counter, counter_text)
    
    def filter_pirate_addons(self, search_text):
        """Фильтрует пиратские аддоны по поисковому запросу (быстрая версия)"""
        search_text = search_text.lower()
        
        visible_count = 0
        enabled_count = 0
        
        # Просто скрываем/показываем существующие карточки
        for i in range(self.pirate_addons_layout.count() - 1):  # -1 чтобы не трогать spacer
            widget = self.pirate_addons_layout.itemAt(i).widget()
            if isinstance(widget, PirateAddonCard):
                addon = widget.addon_data
                # Проверяем совпадение по имени
                matches = search_text in addon['name'].lower()
                
                widget.setVisible(matches)
                
                if matches:
                    visible_count += 1
                    if addon.get('enabled'):
                        enabled_count += 1
        
        # Обновляем счетчик
        if search_text:
            counter_text = get_text("counter_found", visible=visible_count, enabled=enabled_count)
        else:
            if hasattr(self, 'pirate_addons_data'):
                total = sum(1 for a in self.pirate_addons_data if a.get('enabled'))
                counter_text = get_text("addons_counter", total=len(self.pirate_addons_data), enabled=total)
            else:
                counter_text = "0"
        
        # Используем вспомогательную функцию для установки текста
        self.set_counter_text(self.pirate_counter, counter_text, 22)
    
    def set_counter_text(self, counter, text, max_length=25):
        """Устанавливает текст счетчика с обрезанием если он слишком длинный"""
        # Для английского языка используем более короткий лимит
        if hasattr(self, 'current_language') and self.current_language == 'en':
            if max_length == 25:  # Для обычного счетчика
                max_length = 20  # Уменьшаем для английского
            elif max_length == 22:  # Для пиратского счетчика
                max_length = 18  # Уменьшаем для английского
        
        if len(text) > max_length:
            text = text[:max_length-3] + "..."
        counter.setText(text)
    
    def update_header_title(self):
        """Принудительно обновляет заголовок приложения"""
        if hasattr(self, 'header_logo'):
            self.header_logo.setText(get_text("app_title"))
            self.header_logo.adjustSize()
            self.header_logo.updateGeometry()
            self.header_logo.repaint()
    
    def load_config(self):
        """Загрузка конфигурации"""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    if 'game_folder' in config:
                        self.game_folder = Path(config['game_folder'])
                        if hasattr(self, 'path_input'):
                            self.path_input.setText(str(self.game_folder))
                        self.update_paths()
                    # Загружаем время последнего напоминания о донатах
                    if 'last_donate_reminder' in config:
                        self.last_donate_reminder = config['last_donate_reminder']
                    else:
                        self.last_donate_reminder = 0
                    
                    # Загружаем время последнего приглашения в Telegram
                    if 'last_telegram_invitation' in config:
                        self.last_telegram_invitation = config['last_telegram_invitation']
                    else:
                        self.last_telegram_invitation = 0
                    
                    # Загружаем время последнего предупреждения об анимациях
                    if 'last_animation_warning' in config:
                        self.last_animation_warning = config['last_animation_warning']
                    else:
                        self.last_animation_warning = 0
                    
                    # Язык уже загружен в init_localization(), не нужно дублировать
                    # Просто проверяем что он есть в конфиге
                    if 'language' in config:
                        print(f"🌍 load_config: Language in config: {config['language']} (already loaded in init_localization)")
                    else:
                        print(f"🌍 load_config: No language found in config")
            except Exception as e:
                print(f"Ошибка загрузки конфига: {e}")
                self.last_donate_reminder = 0
                self.last_telegram_invitation = 0
                self.last_animation_warning = 0
        else:
            self.last_donate_reminder = 0
            self.last_telegram_invitation = 0
            self.last_animation_warning = 0
    
    def save_config(self):
        """Сохранение конфигурации"""
        config = {}
        if self.game_folder:
            config['game_folder'] = str(self.game_folder)
        
        # Сохраняем время последнего напоминания о донатах
        if hasattr(self, 'last_donate_reminder'):
            config['last_donate_reminder'] = self.last_donate_reminder
        
        # Сохраняем время последнего приглашения в Telegram
        if hasattr(self, 'last_telegram_invitation'):
            config['last_telegram_invitation'] = self.last_telegram_invitation
        
        # Сохраняем время последнего предупреждения об анимациях
        if hasattr(self, 'last_animation_warning'):
            config['last_animation_warning'] = self.last_animation_warning
        
        # Сохраняем текущий язык
        if hasattr(self, 'current_language'):
            print(f"🌍 save_config: Saving language: {self.current_language}")
            config['language'] = self.current_language
        else:
            print(f"🌍 save_config: No current_language attribute")
        
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения конфига: {e}")
    
    def update_paths(self):
        """Обновление путей на основе game_folder"""
        if self.game_folder:
            self.gameinfo_path = self.game_folder / "left4dead2" / "gameinfo.txt"
            self.workshop_path = self.game_folder / "left4dead2" / "addons" / "workshop"
            self.update_status()
    
    def auto_detect_paths(self):
        """Автоопределение путей Steam"""
        possible_paths = [
            Path("C:/Program Files (x86)/Steam/steamapps/common/Left 4 Dead 2"),
            Path("D:/Steam/steamapps/common/Left 4 Dead 2"),
            Path("E:/Steam/steamapps/common/Left 4 Dead 2"),
        ]
        
        for path in possible_paths:
            if path.exists():
                self.game_folder = path
                if hasattr(self, 'path_input'):
                    self.path_input.setText(str(path))
                self.update_paths()
                self.save_config()
                break
    
    def setup_updater(self):
        """Настраивает систему обновлений в стиле CustomInfoDialog"""
        if UPDATER_AVAILABLE:
            self.update_checker = StandardUpdateChecker(self)
            self.update_checker.update_available.connect(self.show_standard_update_dialog)
            
            # Автоматическая проверка обновлений при запуске (через 30 секунд)
            QTimer.singleShot(30000, lambda: self.update_checker.check_for_updates(silent=True))
            
            # Периодическая проверка обновлений каждые 24 часа
            self.update_timer = QTimer()
            self.update_timer.timeout.connect(lambda: self.update_checker.check_for_updates(silent=True))
            self.update_timer.start(24 * 60 * 60 * 1000)  # 24 часа
    
    def check_for_updates(self):
        """Ручная проверка обновлений"""
        if UPDATER_AVAILABLE:
            self.update_checker.check_for_updates(silent=False)
        else:
            # Создаем красивое сообщение об ошибке в стиле приложения
            msg = QMessageBox(self)
            msg.setWindowTitle(get_text("updater_system_title"))
            msg.setText(get_text("updater_unavailable"))
            msg.setInformativeText(
                "Проверьте наличие файлов:\\n"
                "• modern_updater.py\\n"
                "• update_config.py"
            )
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setStyleSheet("""
                QMessageBox {
                    background-color: #2d2d2d;
                    color: white;
                }
                QMessageBox QPushButton {
                    background-color: #3498db;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 4px;
                    min-width: 80px;
                }
                QMessageBox QPushButton:hover {
                    background-color: #5dade2;
                }
            """)
            msg.exec()
    
    def show_standard_update_dialog(self, version_info):
        """Показывает диалог обновления в стиле CustomInfoDialog"""
        if show_update_available_dialog(self, version_info):
            # Пользователь согласился на обновление
            start_update_process(self, version_info)
    
    def open_github_repo(self):
        """Открывает GitHub репозиторий в браузере"""
        try:
            # Получаем URL репозитория из конфигурации обновлений
            if UPDATER_AVAILABLE:
                from update_config import GITHUB_REPO
                github_url = f"https://github.com/{GITHUB_REPO}"
            else:
                # Если система обновлений недоступна, используем стандартный URL
                github_url = "https://github.com/your-username/l4d2-addon-manager"
            
            import webbrowser
            webbrowser.open(github_url)
            
        except Exception as e:
            # Показываем ошибку через CustomInfoDialog
            CustomInfoDialog.information(
                self,
                "Ошибка открытия GitHub",
                f'<div style="text-align: center; color: white;">'
                f'Не удалось открыть GitHub репозиторий.<br><br>'
                f'<b>Ошибка:</b> {str(e)}<br><br>'
                f'Попробуйте открыть ссылку вручную в браузере.'
                f'</div>',
                icon_type="error"
            )

    def apply_dark_styles(self):
        """Применяет темную тему"""
        self.setStyleSheet(DARK_STYLES)
    
    def closeEvent(self, event):
        """При закрытии программы проверяем gameinfo.txt"""
        # Проверяем синхронизацию перед закрытием
        self.check_gameinfo_sync()
        event.accept()


class PirateAddonCard(QFrame):
    """Карточка мода для пиратки с анимациями"""
    
    def __init__(self, addon_data, index, parent=None, two_column_mode=False):
        super().__init__(parent)
        self.addon_data = addon_data
        self.index = index
        self.parent_window = parent
        self.two_column_mode = two_column_mode
        self.setup_ui()
        self.setup_animations()
    
    def setup_ui(self):
        self.setObjectName("modCard")
        # Фиксированный размер только в режиме 2 столбцов
        if self.two_column_mode:
            self.setFixedSize(460, 65)
        else:
            self.setFixedHeight(65)  # В режиме 1 столбца только фиксированная высота
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)
        
        # Иконка файла - с отрицательным margin для компенсации смещения эмодзи
        icon = QLabel("📦")
        icon.setStyleSheet("""
            font-size: 30px; 
            background: transparent; 
            border: none;
            margin-top: -12px;
            margin-left: -4px;
            padding: 0px;
        """)
        icon.setAutoFillBackground(False)
        icon.setFixedSize(45, 45)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)
        
        # Индикатор статуса
        indicator = QLabel("●")
        indicator.setObjectName("statusIndicator")
        indicator.setAutoFillBackground(False)
        indicator.setStyleSheet(f"color: {'#3498db' if self.addon_data['enabled'] else '#95a5a6'}; font-size: 16px; background: transparent; border: none;")
        
        # Информация о файле - с центрированием через stretch
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        info_layout.setContentsMargins(0, 0, 0, 0)
        
        # Добавляем stretch сверху для центрирования
        info_layout.addStretch()
        
        # Заголовок с индикатором
        title_layout = QHBoxLayout()
        title_layout.setSpacing(8)
        title_layout.addWidget(indicator)
        
        name_label = QLabel(self.addon_data['name'])
        name_label.setObjectName("cardTitle")
        
        # ВАЖНО: убираем фон у названия
        name_label.setAutoFillBackground(False)
        name_label.setStyleSheet("background: transparent; border: none;")
        name_label.setWordWrap(False)
        name_label.setTextFormat(Qt.TextFormat.PlainText)
        
        # Обрезаем текст с многоточием только в режиме 2 столбцов
        if self.two_column_mode:
            # Устанавливаем максимальную ширину для текста (учитываем иконку, индикатор, toggle и кнопку удаления)
            # 460 (ширина карточки) - 12*2 (margins) - 45 (icon) - 16 (indicator) - 60 (toggle) - 30 (delete) - 12*4 (spacing) = ~230
            name_label.setMaximumWidth(230)
            
            # Создаем метрику шрифта для обрезки текста
            font_metrics = name_label.fontMetrics()
            elided_text = font_metrics.elidedText(self.addon_data['name'], Qt.TextElideMode.ElideRight, 230)
            name_label.setText(elided_text)
            name_label.setToolTip(self.addon_data['name'])  # Показываем полное название в подсказке
        else:
            # В режиме 1 столбца показываем полное название
            name_label.setText(self.addon_data['name'])
        
        title_layout.addWidget(name_label, 1)
        info_layout.addLayout(title_layout)
        
        # Цвет текста для темной темы
        text_color = "#d0d0d0"
        
        size_mb = self.addon_data['path'].stat().st_size / (1024 * 1024)
        size_label = QLabel()
        size_label.setTextFormat(Qt.TextFormat.RichText)
        
        # ВАЖНО: убираем фон у label
        size_label.setAutoFillBackground(False)
        size_label.setStyleSheet("background: transparent; border: none;")
        
        size_label.setText(f'<span style="color: {text_color}; font-size: 12px;">Размер: {size_mb:.2f} MB</span>')
        info_layout.addWidget(size_label)
        
        # Добавляем stretch снизу для центрирования
        info_layout.addStretch()
        
        layout.addLayout(info_layout, 1)
        
        # Анимированный переключатель
        self.toggle_switch = AnimatedToggle()
        self.toggle_switch.setChecked(self.addon_data['enabled'])
        self.toggle_switch.stateChanged.connect(lambda state: self.parent_window.toggle_pirate_addon(self.addon_data, self.toggle_switch.isChecked()))
        layout.addWidget(self.toggle_switch, 0, Qt.AlignmentFlag.AlignVCenter)
        
        # Кнопка удаления с анимированной иконкой мусорки
        delete_btn = AnimatedTrashButton()
        delete_btn.clicked.connect(lambda checked=False: self.safe_delete_addon())
        layout.addWidget(delete_btn, 0, Qt.AlignmentFlag.AlignVCenter)
    
    def safe_delete_addon(self):
        """Безопасное удаление аддона с обработкой ошибок"""
        try:
            self.parent_window.delete_pirate_addon(self.addon_data['path'])
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"[ERROR] Failed to delete addon: {error_details}")
            try:
                CustomInfoDialog.information(
                    self.parent_window,
                    get_text("error_title"),
                    get_text("delete_mod_error", error=str(e)),
                    icon_type="error"
                )
            except:
                # Если даже диалог не открывается, просто выводим в консоль
                print(f"[ERROR] Could not show error dialog: {e}")
    
    def setup_animations(self):
        """Настройка hover анимации - точно как у AnimatedCard"""
        # Сохраняем оригинальную геометрию
        self.original_geometry = None
        
        # Анимация геометрии для scale эффекта
        self.scale_anim = QPropertyAnimation(self, b"geometry")
        self.scale_anim.setDuration(150)
        self.scale_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    
    def enterEvent(self, event):
        """При наведении - легкое увеличение"""
        super().enterEvent(event)
        
        if self.original_geometry is None:
            self.original_geometry = self.geometry()
        
        # Увеличиваем на 3px со всех сторон для более заметного эффекта
        target = self.original_geometry.adjusted(-3, -3, 3, 3)
        
        self.scale_anim.stop()
        self.scale_anim.setStartValue(self.geometry())
        self.scale_anim.setEndValue(target)
        self.scale_anim.start()
    
    def leaveEvent(self, event):
        """При уходе мыши - возвращаем к оригиналу"""
        super().leaveEvent(event)
        
        if self.original_geometry is None:
            return
        
        self.scale_anim.stop()
        self.scale_anim.setStartValue(self.geometry())
        self.scale_anim.setEndValue(self.original_geometry)
        self.scale_anim.start()


DARK_STYLES = """
QMainWindow {
    background: #0a0a0a;
}

#header {
    background: #0f0f0f;
    border-bottom: 1px solid #1a1a1a;
}

#headerTitle {
    font-size: 18px;
    font-weight: 500;
    color: white;
    letter-spacing: 0.5px;
    width: 350px;
    max-width: 350px;
    min-width: 350px;
    text-overflow: visible;
    overflow: visible;
}

#donateButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #3498db, stop:1 #2980b9);
    border: none;
    border-radius: 20px;
    color: white;
    padding: 6px 12px;
    font-size: 11px;
    font-weight: 600;
}

#donateButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #5dade2, stop:1 #3498db);
}

#donateButton:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #2980b9, stop:1 #21618c);
}

#updateButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #bb86fc, stop:0.5 #9333ea, stop:1 #7c3aed);
    border: none;
    border-radius: 20px;
    color: white;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 600;
}

#updateButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #d1a7ff, stop:0.5 #bb86fc, stop:1 #9333ea);
}

#updateButton:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #9333ea, stop:0.5 #7c3aed, stop:1 #6b21a8);
}

#githubButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #4a5568, stop:0.5 #2d3748, stop:1 #1a202c);
    border: none;
    border-radius: 20px;
    color: white;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 600;
}

#githubButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #718096, stop:0.5 #4a5568, stop:1 #2d3748);
}

#githubButton:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #2d3748, stop:0.5 #1a202c, stop:1 #171923);
}

#telegramButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #0088cc, stop:0.5 #0088cc, stop:1 #006699);
    border: none;
    border-radius: 16px;  /* Круглая кнопка (половина от размера 32px) */
    color: white;
    font-weight: 600;
    font-size: 12px;
}

#telegramButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #33aadd, stop:0.5 #0099dd, stop:1 #0088cc);
}

#telegramButton:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #006699, stop:0.5 #005577, stop:1 #004466);
}

#workshopBtn {
    background: transparent;
    border: 1px solid #9b59b6;
    border-radius: 22px;
    color: #9b59b6;
    font-size: 10px;
    font-weight: 500;
}

#workshopBtn:hover {
    background: #9b59b6;
    color: white;
    border: 1px solid #af7ac5;
}

#reloadBtn {
    background: transparent;
    border: 1px solid #e67e22;
    border-radius: 22px;
    color: #e67e22;
    font-size: 13px;
    font-weight: 500;
}

#reloadBtn:hover {
    background: #e67e22;
    color: white;
    border: 1px solid #f39c12;
}

#reloadBtn:pressed {
    background: #d35400;
    border: 1px solid #e67e22;
}

#tabBtn {
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0px;
    color: #7f8c8d;
    padding: 12px 25px;
    margin: 0 5px;
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 1px;
}

#tabBtn:checked {
    background: transparent;
    border-bottom: 2px solid #3498db;
    color: white;
}

#tabBtn:hover {
    background: transparent;
    color: #bdc3c7;
}

#searchBox {
    background: #2a2a2a;
    border: 2px solid transparent;
    border-radius: 20px;
    padding: 0px 20px;
    color: #d0d0d0;
    font-size: 13px;
    font-weight: 400;
    height: 41px;
    max-height: 41px;
    min-height: 41px;
}

#searchBox:focus {
    border: 2px solid #3498db;
    background: #2d2d2d;
}

#clearSearchBtn {
    background: transparent;
    border: none;
    color: #7f8c8d;
    font-size: 16px;
    font-weight: 300;
    padding: 0px;
    margin: 2px;
}

#clearSearchBtn:hover {
    background: transparent;
}

#clearSearchBtn:pressed {
    background: transparent;
}

#clearSearchBtn:focus {
    outline: none;
    border: none;
}

#sortCombo {
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 10px;
    padding: 10px 15px 10px 45px;
    color: #d0d0d0;
    font-size: 13px;
    font-weight: 500;
}

#sortCombo:hover {
    border: 1px solid #3498db;
    background: #1f1f1f;
}

#sortCombo:focus {
    border: 1px solid #3498db;
    outline: none;
}

#sortCombo::drop-down {
    border: none;
    width: 30px;
    subcontrol-origin: padding;
    subcontrol-position: center right;
    padding-right: 8px;
}

#sortCombo::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 7px solid #7f8c8d;
}

#sortCombo::down-arrow:hover {
    border-top-color: #3498db;
}

#sortCombo QAbstractItemView {
    background: #1a1a1a;
    border: 2px solid #3498db;
    border-radius: 10px;
    selection-background-color: #3498db;
    selection-color: white;
    color: #d0d0d0;
    padding: 8px;
    outline: none;
}

#sortCombo QAbstractItemView::item {
    padding: 12px 20px;
    border-radius: 8px;
    margin: 3px;
    min-height: 30px;
}

#sortCombo QAbstractItemView::item:hover {
    background: rgba(52, 152, 219, 0.2);
    color: white;
}

#sortCombo QAbstractItemView::item:selected {
    background: #3498db;
    color: white;
    font-weight: 600;
}

QMenu#sortMenu {
    background: #1a1a1a;
    border: 2px solid #3498db;
    border-radius: 12px;
    padding: 10px;
}

QMenu#sortMenu::item {
    background: transparent;
    color: #d0d0d0;
    padding: 10px 18px;
    border-radius: 8px;
    margin: 2px 4px;
    font-size: 10px;
}

QMenu#sortMenu::item:selected {
    background: rgba(52, 152, 219, 0.15);
    color: white;
}

QMenu#sortMenu::item:checked {
    background: #3498db;
    color: white;
    font-weight: 500;
}

QMenu#sortMenu::indicator {
    width: 0px;
    height: 0px;
}

QMenu#sortMenu::separator {
    height: 0px;
}

#iconBtn {
    background: transparent;
    border: 1px solid #2a2a2a;
    border-radius: 22px;
    color: #7f8c8d;
    font-size: 20px;
    font-weight: 300;
}

#iconBtn:hover {
    background: #1a1a1a;
    border: 1px solid #3498db;
    color: #3498db;
}

#refreshBtn {
    background: #1a1a1a;
    border: 2px solid #2a2a2a;
    border-radius: 22px;
}

#refreshBtn:hover {
    background: #1a1a1a;
    border: 2px solid #3498db;
}

#addVpkBtn {
    background: transparent;
    border: 1px solid #3498db;
    border-radius: 22px;
    color: #3498db;
    font-size: 10px;
    font-weight: 500;
}

#addVpkBtn:hover {
    background: #3498db;
    color: white;
    border: 1px solid #5dade2;
}

#enableAllBtn {
    background: #3498db;
    border: none;
    border-radius: 22px;
    color: white;
    font-size: 10px;
    font-weight: 600;
}

#enableAllBtn:hover {
    background: #5dade2;
}

#enableAllBtn:pressed {
    background: #2980b9;
}

#disableAllBtn {
    background: #3498db;
    border: none;
    border-radius: 22px;
    color: white;
    font-size: 10px;
    font-weight: 600;
}

#disableAllBtn:hover {
    background: #5dade2;
}

#disableAllBtn:pressed {
    background: #2980b9;
}

#counter {
    background: #191919;
    border-radius: 10px;
    padding: 12px 20px;
    color: #d0d0d0;
    font-size: 13px;
    font-weight: 500;
}

#modCard {
    background: #191919;
    border: 2px solid #252525;
    border-radius: 15px;
    padding: 5px;
}

#modCard:hover {
    border: 2px solid #3498db;
    background: #242424;
}

#addonIcon {
    border-radius: 10px;
    background: #1a1a1a;
    border: 1px solid #3a3a3a;
}

#cardTitle {
    font-size: 14px;
    font-weight: 600;
    color: white;
    padding: 0px;
    margin: 0px;
}

#cardSubtitle {
    font-size: 12px;
    color: #d0d0d0;
    line-height: 1.4;
    font-weight: 400;
}

#cardStatus {
    font-size: 12px;
    color: #27ae60;
    font-weight: 500;
}

#toggleBtn {
    background: transparent;
    border: 1px solid #27ae60;
    border-radius: 8px;
    color: #27ae60;
    font-size: 13px;
    font-weight: 500;
    padding: 8px 15px;
}

#toggleBtn:hover {
    background: #27ae60;
    color: white;
}

#disableBtn {
    background: transparent;
    border: 1px solid #e74c3c;
    border-radius: 8px;
    color: #e74c3c;
    font-size: 13px;
    font-weight: 500;
    padding: 8px 15px;
}

#disableBtn:hover {
    background: #e74c3c;
    color: white;
}

QScrollArea {
    border: none;
    background: #0a0a0a;
}

QScrollArea QWidget {
    background: #0a0a0a;
}

QScrollBar:vertical {
    background: #1a1a1a;
    width: 10px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background: #3498db;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

#sectionTitle {
    font-size: 20px;
    font-weight: 500;
    color: white;
    letter-spacing: 3px;
    margin-bottom: 5px;
    line-height: 24px;
    padding: 0px;
}

#settingsCard {
    background: #191919;
    border: 2px solid #252525;
    border-radius: 15px;
}

#settingsCard:hover {
    border: 2px solid #3498db;
    background: #242424;
}

#settingsInput {
    background: #0f0f0f;
    border: 1px solid #2a2a2a;
    border-radius: 8px;
    padding: 10px 12px;
    color: white;
    font-size: 13px;
    font-weight: 400;
}

#settingsInput:hover {
    border: 1px solid #3a3a3a;
    background: #121212;
}

#settingsInput:focus {
    border: 1px solid #3498db;
    background: #141414;
}

#settingsBtn {
    background: transparent;
    border: 1px solid #3498db;
    border-radius: 8px;
    color: #3498db;
    padding: 10px 18px;
    font-size: 13px;
    font-weight: 500;
    letter-spacing: 1px;
}

#settingsBtn:hover {
    background: #3498db;
    color: white;
    border: 1px solid #5dade2;
}

#settingsBtn:pressed {
    background: #2980b9;
    border: 1px solid #2980b9;
}

#glassBtn {
    background: #0a0a0a;
    border: 2px solid #3498db;
    border-radius: 12px;
    color: #3498db;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 500;
}

#glassBtn:hover {
    background: #0a0a0a;
    border: 2px solid #5dade2;
    color: #5dade2;
}

#glassBtn:pressed {
    background: #0f0f0f;
    border: 2px solid #3498db;
}

#dangerBtn {
    background: transparent;
    border: 1px solid #e74c3c;
    border-radius: 8px;
    color: #e74c3c;
    padding: 10px 18px;
    font-size: 13px;
    font-weight: 500;
    letter-spacing: 1px;
}

#dangerBtn:hover {
    background: #e74c3c;
    color: white;
    border: 1px solid #ec7063;
}

#dangerBtn:pressed {
    background: #c0392b;
    border: 1px solid #c0392b;
}

#statusLabel {
    font-size: 13px;
    font-weight: 500;
    padding: 5px 0;
}

#settingsScroll {
    border: none;
    background: transparent;
}

#languageBtn {
    background: rgba(40, 40, 40, 0.8);
    border: 2px solid rgba(52, 152, 219, 0.3);
    border-radius: 12px;
    color: white;
    padding: 10px 20px;
    font-size: 13px;
    font-weight: 500;
    min-width: 120px;
}

#languageBtn:hover {
    background: rgba(52, 152, 219, 0.2);
    border: 2px solid rgba(52, 152, 219, 0.6);
}

#languageBtn:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #3498db, stop:1 #2980b9);
    border: 2px solid #3498db;
    color: white;
}

#languageBtn:checked:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #5dade2, stop:1 #3498db);
}

#languageHeaderBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #27ae60, stop:0.5 #2ecc71, stop:1 #27ae60);
    border: none;
    border-radius: 20px;
    color: white;
    font-size: 12px;
    font-weight: 600;
    padding: 0 15px;
    min-width: 60px;
}

#languageHeaderBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #2ecc71, stop:0.5 #58d68d, stop:1 #2ecc71);
}

#languageHeaderBtn:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #229954, stop:0.5 #27ae60, stop:1 #229954);
}

#languageCard {
    background: #191919;
    border: 2px solid #252525;
    border-radius: 15px;
}

#languageCard:hover {
    border: 2px solid #3498db;
    background: #242424;
}
"""


if __name__ == "__main__":
    # Включаем сглаживание ДО создания QApplication (для PyQt6 HighDPI включен по умолчанию)
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # Загружаем кастомный шрифт sans.ttf
    font_path = Path(__file__).parent / "sans.ttf"
    if font_path.exists():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        if font_id != -1:
            font_families = QFontDatabase.applicationFontFamilies(font_id)
            if font_families:
                font_family = font_families[0]
                # Устанавливаем шрифт для всего приложения с настройками сглаживания
                app_font = QFont(font_family)
                app_font.setPixelSize(10)  # Базовый размер шрифта (уменьшен с 11 до 10)
                app_font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)  # Отключаем хинтинг для более гладкого вида
                app_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)  # Принудительное сглаживание
                app.setFont(app_font)
                # print(f"Шрифт '{font_family}' успешно загружен с сглаживанием")
            # else:
                # print("Не удалось получить имя семейства шрифта")
        # else:
            # print("Не удалось загрузить шрифт sans.ttf")
    # else:
        # print("Файл sans.ttf не найден")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())

# Дополнительные стили для workshopBtn (добавлены в обе темы через код выше)