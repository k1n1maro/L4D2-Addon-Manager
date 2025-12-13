#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Диалог выбора языка для L4D2 Addon Manager
"""

import sys
from pathlib import Path
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *

def get_resource_path(filename):
    """Получает правильный путь к ресурсу"""
    if getattr(sys, 'frozen', False):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).parent
    
    resource_path = base_path / filename
    if resource_path.exists():
        return resource_path
    
    return base_path / filename

class LanguageSelectionDialog(QDialog):
    """Диалог выбора языка при первом запуске"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_language = "ru"  # По умолчанию русский
        self.setup_ui()
        
    def setup_ui(self):
        """Создает интерфейс диалога"""
        self.setWindowTitle("Language Selection / Выбор языка")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setFixedSize(500, 400)
        
        # Основной layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Контейнер с фоном
        container = QWidget()
        container.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(30, 30, 30, 0.95),
                    stop:1 rgba(20, 20, 20, 0.95));
                border-radius: 20px;
                border: 2px solid rgba(52, 152, 219, 0.3);
            }
        """)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(40, 40, 40, 40)
        container_layout.setSpacing(25)
        container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Иконка приложения
        icon_label = QLabel()
        icon_path = get_resource_path("logo.png")
        if icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                icon_label.setPixmap(scaled_pixmap)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(icon_label)
        
        # Заголовок
        title_label = QLabel("L4D2 Addon Manager")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 24px; font-weight: 600; color: white; margin-bottom: 10px;")
        container_layout.addWidget(title_label)
        
        # Описание (двуязычное)
        description_label = QLabel(
            "<div style='text-align: center; color: #bdc3c7; line-height: 1.6;'>"
            "<b>Please select your preferred language:</b><br>"
            "<b>Пожалуйста, выберите предпочитаемый язык:</b>"
            "</div>"
        )
        description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description_label.setStyleSheet("font-size: 14px; margin-bottom: 20px;")
        description_label.setWordWrap(True)
        container_layout.addWidget(description_label)
        
        # Кнопки выбора языка
        languages_layout = QVBoxLayout()
        languages_layout.setSpacing(15)
        
        # Русский язык
        self.russian_btn = self.create_language_button(
            "🇷🇺 Русский", 
            "Русский интерфейс", 
            "ru"
        )
        self.russian_btn.setChecked(True)  # По умолчанию выбран
        languages_layout.addWidget(self.russian_btn)
        
        # Английский язык
        self.english_btn = self.create_language_button(
            "🇺🇸 English", 
            "English interface", 
            "en"
        )
        languages_layout.addWidget(self.english_btn)
        
        container_layout.addLayout(languages_layout)
        
        # Кнопка продолжить
        continue_btn = QPushButton("Continue / Продолжить")
        continue_btn.setFixedSize(200, 45)
        continue_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3498db, stop:1 #2980b9);
                border: none;
                border-radius: 22px;
                color: white;
                font-size: 14px;
                font-weight: 600;
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
        continue_btn.clicked.connect(self.accept)
        container_layout.addWidget(continue_btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        layout.addWidget(container)
        
        # Анимация появления
        self.setWindowOpacity(0)
        self.opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_anim.setDuration(300)
        self.opacity_anim.setStartValue(0)
        self.opacity_anim.setEndValue(1)
        self.opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    
    def create_language_button(self, title, description, language_code):
        """Создает кнопку выбора языка"""
        btn = QRadioButton()
        btn.setFixedSize(350, 60)
        btn.setStyleSheet("""
            QRadioButton {
                background: rgba(40, 40, 40, 0.8);
                border: 2px solid rgba(52, 152, 219, 0.3);
                border-radius: 15px;
                padding: 10px 15px;
                color: white;
                font-size: 14px;
            }
            QRadioButton:hover {
                background: rgba(50, 50, 50, 0.9);
                border: 2px solid rgba(52, 152, 219, 0.6);
            }
            QRadioButton:checked {
                background: rgba(52, 152, 219, 0.2);
                border: 2px solid #3498db;
            }
            QRadioButton::indicator {
                width: 20px;
                height: 20px;
                margin-right: 10px;
            }
            QRadioButton::indicator:unchecked {
                border: 2px solid #7f8c8d;
                border-radius: 10px;
                background: transparent;
            }
            QRadioButton::indicator:checked {
                border: 2px solid #3498db;
                border-radius: 10px;
                background: #3498db;
            }
        """)
        
        # Создаем кастомный текст
        btn.setText(f"{title}\n{description}")
        
        # Подключаем обработчик
        btn.toggled.connect(lambda checked, lang=language_code: self.on_language_selected(lang) if checked else None)
        
        return btn
    
    def on_language_selected(self, language_code):
        """Обработчик выбора языка"""
        self.selected_language = language_code
        print(f"Selected language: {language_code}")
    
    def show_with_animation(self):
        """Показывает диалог с анимацией"""
        self.show()
        self.opacity_anim.start()
    
    def get_selected_language(self):
        """Возвращает выбранный язык"""
        return self.selected_language

def show_language_selection_dialog(parent=None):
    """Показывает диалог выбора языка и возвращает выбранный язык"""
    dialog = LanguageSelectionDialog(parent)
    dialog.show_with_animation()
    
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.get_selected_language()
    
    return "ru"  # По умолчанию русский