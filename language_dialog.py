#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Диалог выбора языка для L4D2 Addon Manager в стиле CustomInfoDialog
"""

import sys
from pathlib import Path
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *

# Импортируем функцию локализации
try:
    from localization import get_text
except ImportError:
    def get_text(key, **kwargs):
        return key

# Импортируем AnimatedActionButton из основного файла
try:
    from l4d2_pyqt_main import AnimatedActionButton
except ImportError:
    # Если не удается импортировать, создаем простую замену
    class AnimatedActionButton(QPushButton):
        def __init__(self, text, color):
            super().__init__(text)
            self.setStyleSheet(f"""
                QPushButton {{
                    background: {color};
                    border: none;
                    border-radius: 25px;
                    color: white;
                    font-size: 14px;
                    font-weight: 600;
                    padding: 10px 20px;
                }}
                QPushButton:hover {{
                    background: {color};
                    opacity: 0.8;
                }}
            """)

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
    """Диалог выбора языка в стиле CustomInfoDialog"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_widget = parent
        self.selected_language = "ru"  # По умолчанию русский
        
        # Настройка окна
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        
        # Применяем блюр к родительскому окну (если есть)
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
        
        self.setup_ui()
        
        # Анимация появления
        self.setWindowOpacity(0)
        self.opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_anim.setDuration(300)
        self.opacity_anim.setStartValue(0)
        self.opacity_anim.setEndValue(1)
        self.opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
    def setup_ui(self):
        """Создает интерфейс в стиле CustomInfoDialog"""
        self.setFixedSize(700, 520)
        
        # Основной layout - всегда центрируем по вертикали
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)  # Равные отступы со всех сторон
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(20)
        container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Иконка приложения - ЕДИНЫЙ СТАНДАРТ 120x120 как в CustomInfoDialog
        icon_label = QLabel()
        icon_path = get_resource_path("logo.png")
        if icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                # ЕДИНЫЙ СТАНДАРТ: 120x120
                scaled_pixmap = pixmap.scaled(120, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                icon_label.setPixmap(scaled_pixmap)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(icon_label)
        
        # Заголовок - ЕДИНЫЙ СТАНДАРТ как в CustomInfoDialog
        title_label = QLabel("Выбор языка")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 20px; font-weight: 600; color: white;")
        container_layout.addWidget(title_label)
        
        # Сообщение - меньший шрифт как в CustomInfoDialog
        message_label = QLabel(
            'Please select your preferred interface language:\n'
            'Пожалуйста, выберите предпочитаемый язык интерфейса:\n\n'
            'This setting can be changed later in Settings.\n'
            'Эту настройку можно изменить позже в Настройках.'
        )
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setWordWrap(True)
        message_label.setMaximumWidth(600)  # Ограничиваем ширину для лучшей читаемости
        message_label.setStyleSheet("font-size: 13px; color: white; line-height: 1.5;")
        container_layout.addWidget(message_label, 0, Qt.AlignmentFlag.AlignCenter)
        
        # Кнопки выбора языка в стиле CustomInfoDialog
        languages_layout = QVBoxLayout()
        languages_layout.setSpacing(15)
        
        # Русский язык
        self.russian_btn = self.create_language_button("Русский", "ru", True)
        languages_layout.addWidget(self.russian_btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        # Английский язык  
        self.english_btn = self.create_language_button("English", "en", False)
        languages_layout.addWidget(self.english_btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        container_layout.addLayout(languages_layout)
        
        layout.addWidget(container)
    
    def create_language_button(self, text, language_code, is_default=False):
        """Создает кнопку выбора языка в стиле AnimatedActionButton"""
        # Используем AnimatedActionButton для единого стиля
        if is_default:
            btn = AnimatedActionButton(text, "#3498db")  # Выбранная кнопка синяя
        else:
            btn = AnimatedActionButton(text, "#7f8c8d")  # Невыбранная кнопка серая
        
        btn.setFixedSize(250, 50)
        btn.setCheckable(True)
        btn.setChecked(is_default)
        
        # Подключаем обработчик
        btn.clicked.connect(lambda: self.on_language_selected(language_code, btn))
        
        if is_default:
            self.selected_language = language_code
        
        return btn
    
    def on_language_selected(self, language_code, clicked_btn):
        """Обработчик выбора языка"""
        self.selected_language = language_code
        
        # Обновляем стили кнопок - выбранная синяя, остальные серые
        for btn in [self.russian_btn, self.english_btn]:
            if btn == clicked_btn:
                btn.setChecked(True)
                # Меняем цвет на синий для выбранной кнопки
                btn.setStyleSheet(btn.styleSheet().replace("#7f8c8d", "#3498db"))
            else:
                btn.setChecked(False)
                # Меняем цвет на серый для невыбранных кнопок
                btn.setStyleSheet(btn.styleSheet().replace("#3498db", "#7f8c8d"))
        
        print(f"🌍 Selected language: {language_code}")
        
        # Сразу закрываем диалог после выбора языка
        QTimer.singleShot(200, self.close_with_animation)  # Небольшая задержка для визуального эффекта
    
    def show_with_animation(self):
        """Показывает диалог с анимацией"""
        self.show()
        self.opacity_anim.start()
        if hasattr(self, 'blur_anim') and self.blur_anim:
            self.blur_anim.start()
    
    def get_selected_language(self):
        """Возвращает выбранный язык"""
        return self.selected_language
    
    def close_with_animation(self):
        """Закрывает диалог с анимацией"""
        # Анимация исчезновения
        self.opacity_anim.setStartValue(1)
        self.opacity_anim.setEndValue(0)
        self.opacity_anim.finished.connect(lambda: super(LanguageSelectionDialog, self).accept())
        self.opacity_anim.start()
        
        # Убираем блюр
        if hasattr(self, 'blur_anim') and self.blur_anim:
            self.blur_anim.setStartValue(15)
            self.blur_anim.setEndValue(0)
            self.blur_anim.start()
    
    def accept(self):
        """Переопределяем accept для анимации"""
        if not hasattr(self, '_closing'):
            self._closing = True
            self.close_with_animation()
    
    def closeEvent(self, event):
        """При закрытии убираем blur"""
        try:
            if self.parent_widget:
                self.parent_widget.setGraphicsEffect(None)
        except Exception as e:
            print(f"Error removing blur effect: {e}")
        super().closeEvent(event)

def show_language_selection_dialog(parent=None):
    """Показывает диалог выбора языка и возвращает выбранный язык"""
    dialog = LanguageSelectionDialog(parent)
    dialog.show_with_animation()
    
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.get_selected_language()
    
    return "ru"  # По умолчанию русский