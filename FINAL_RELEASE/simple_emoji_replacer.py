#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Простая замена всех PNG иконок на эмодзи
"""

import re
from pathlib import Path

def replace_icons_with_emoji(file_path):
    """Заменяет все PNG иконки на эмодзи"""
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Простые замены - убираем все загрузки PNG и заменяем на эмодзи
    replacements = [
        # Убираем все блоки загрузки PNG иконок
        (r'# Загружаем.*?\.png.*?\n.*?if.*?\.exists\(\):.*?\n.*?pixmap = QPixmap.*?\n.*?if not pixmap\.isNull\(\):.*?\n.*?scaled_pixmap = pixmap\.scaled.*?\n.*?icon_label\.setPixmap\(scaled_pixmap\)', 
         '# Используем эмодзи вместо PNG\n        icon_label.setText("🎮")\n        icon_label.setStyleSheet("font-size: 60px;")'),
        
        # Заменяем конкретные иконки на эмодзи
        (r'Path\(__file__\)\.parent / "logo\.png"', '"🎮"'),
        (r'Path\(__file__\)\.parent / "folder\.png"', '"📁"'),
        (r'Path\(__file__\)\.parent / "info\.png"', '"ℹ️"'),
        (r'Path\(__file__\)\.parent / "settings\.png"', '"⚙️"'),
        (r'Path\(__file__\)\.parent / "git\.png"', '"🐙"'),
        (r'Path\(__file__\)\.parent / "addon\.png"', '"🧩"'),
        (r'Path\(__file__\)\.parent / "add\.png"', '"➕"'),
        (r'Path\(__file__\)\.parent / "link\.png"', '"🔗"'),
        (r'Path\(__file__\)\.parent / "allon\.png"', '"✅"'),
        (r'Path\(__file__\)\.parent / "alloff\.png"', '"❌"'),
        (r'Path\(__file__\)\.parent / "trash\.png"', '"🗑️"'),
        (r'Path\(__file__\)\.parent / "upd\.png"', '"🔄"'),
        (r'Path\(__file__\)\.parent / "sup\.png"', '"💝"'),
        (r'Path\(__file__\)\.parent / "ques\.png"', '"❓"'),
        (r'Path\(__file__\)\.parent / "spravka\.png"', '"❓"'),
        (r'Path\(__file__\)\.parent / "con\.png"', '"📞"'),
        
        # Убираем сложную логику загрузки иконок
        (r'if.*?_path\.exists\(\):.*?\n.*?pixmap = QPixmap.*?\n.*?if not pixmap\.isNull\(\):.*?\n', ''),
        (r'icon_label\.setPixmap\(.*?\)', 'icon_label.setText("🎮"); icon_label.setStyleSheet("font-size: 40px;")'),
    ]
    
    for pattern, replacement in replacements:
        content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    
    # Сохраняем файл
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"✅ Обновлен: {file_path}")

# Обрабатываем файлы
files = [
    Path("../RELEASE_READY/l4d2_pyqt_main.py"),
    Path("../RELEASE_READY/modern_updater.py")
]

for file_path in files:
    if file_path.exists():
        replace_icons_with_emoji(file_path)
    else:
        print(f"❌ Файл не найден: {file_path}")

print("\n🧹 Готово! Теперь можно удалить все PNG файлы.")