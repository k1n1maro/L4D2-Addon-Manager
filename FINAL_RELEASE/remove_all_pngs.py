#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Удаляет все PNG зависимости из кода и заменяет на эмодзи
"""

import re
from pathlib import Path

def clean_file(file_path):
    """Очищает файл от PNG зависимостей"""
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Заменяем все сложные блоки загрузки иконок на простые эмодзи
    patterns = [
        # Убираем все блоки с загрузкой PNG
        (r'# Загружаем.*?\.png.*?\n.*?if.*?\.exists\(\):.*?\n.*?pixmap = QPixmap.*?\n.*?if not pixmap\.isNull\(\):.*?\n.*?scaled_pixmap = pixmap\.scaled.*?\n.*?icon_label\.setPixmap\(scaled_pixmap\)', 
         'icon_label.setText("🎮")\n        icon_label.setStyleSheet("font-size: 60px;")'),
        
        # Убираем все Path(__file__).parent / "*.png"
        (r'Path\(__file__\)\.parent / "[^"]*\.png"', 'None'),
        
        # Убираем проверки существования файлов
        (r'if [^_]*_path\.exists\(\):.*?\n', ''),
        (r'if [^_]*path\.exists\(\):.*?\n', ''),
        
        # Убираем загрузку QPixmap
        (r'pixmap = QPixmap\(str\([^)]*\)\).*?\n', ''),
        (r'if not pixmap\.isNull\(\):.*?\n', ''),
        
        # Заменяем setPixmap на setText с эмодзи
        (r'icon_label\.setPixmap\([^)]*\)', 'icon_label.setText("🎮"); icon_label.setStyleSheet("font-size: 40px;")'),
        
        # Убираем сложную логику перекраски
        (r'# Перекрашиваем.*?\n.*?colored_pixmap = QPixmap.*?\n.*?colored_pixmap\.fill.*?\n.*?painter = QPainter.*?\n.*?painter\.setCompositionMode.*?\n.*?painter\.drawPixmap.*?\n.*?painter\.setCompositionMode.*?\n.*?painter\.fillRect.*?\n.*?painter\.end\(\).*?\n', ''),
        
        # Убираем масштабирование
        (r'scaled_pixmap = pixmap\.scaled.*?\n', ''),
        
        # Заменяем конкретные иконки в AnimatedActionButton
        (r'"allon\.png"', '"✅"'),
        (r'"alloff\.png"', '"❌"'),
        (r'"add\.png"', '"➕"'),
        (r'"link\.png"', '"🔗"'),
        
        # Заменяем иконки в tabs_data
        (r'"addon\.png"', '"🧩"'),
        (r'"settings\.png"', '"⚙️"'),
        (r'"spravka\.png"', '"❓"'),
        (r'"con\.png"', '"📞"'),
    ]
    
    for pattern, replacement in patterns:
        content = re.sub(pattern, replacement, content, flags=re.DOTALL | re.MULTILINE)
    
    # Сохраняем файл
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"✅ Очищен: {file_path}")

# Обрабатываем файлы
files = [
    Path("../RELEASE_READY/l4d2_pyqt_main.py"),
    Path("../RELEASE_READY/modern_updater.py")
]

print("🧹 Удаляем все PNG зависимости...")

for file_path in files:
    if file_path.exists():
        clean_file(file_path)
    else:
        print(f"❌ Файл не найден: {file_path}")

print("\n✅ Готово! Все PNG зависимости удалены, используются только эмодзи.")