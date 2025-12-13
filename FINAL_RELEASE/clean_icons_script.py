#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для замены PNG иконок на эмодзи в коде
"""

import re
from pathlib import Path

# Словарь замен PNG файлов на эмодзи
REPLACEMENTS = {
    # Основные иконки
    r'Path\(__file__\)\.parent / "logo\.png"': 'None  # Используем эмодзи 🎮',
    r'Path\(__file__\)\.parent / "folder\.png"': 'None  # Используем эмодзи 📁',
    r'Path\(__file__\)\.parent / "info\.png"': 'None  # Используем эмодзи ℹ️',
    r'Path\(__file__\)\.parent / "settings\.png"': 'None  # Используем эмодзи ⚙️',
    r'Path\(__file__\)\.parent / "git\.png"': 'None  # Используем эмодзи 🐙',
    
    # Иконки кнопок
    r'Path\(__file__\)\.parent / "addon\.png"': 'None  # Используем эмодзи 🧩',
    r'Path\(__file__\)\.parent / "add\.png"': 'None  # Используем эмодзи ➕',
    r'Path\(__file__\)\.parent / "link\.png"': 'None  # Используем эмодзи 🔗',
    r'Path\(__file__\)\.parent / "allon\.png"': 'None  # Используем эмодзи ✅',
    r'Path\(__file__\)\.parent / "alloff\.png"': 'None  # Используем эмодзи ❌',
    r'Path\(__file__\)\.parent / "trash\.png"': 'None  # Используем эмодзи 🗑️',
    
    # Остальные иконки
    r'Path\(__file__\)\.parent / "sort\.png"': 'None  # Используем эмодзи 🔄',
    r'Path\(__file__\)\.parent / "ref\.png"': 'None  # Используем эмодзи 🔄',
    r'Path\(__file__\)\.parent / "upd\.png"': 'None  # Используем эмодзи 🔄',
    r'Path\(__file__\)\.parent / "sup\.png"': 'None  # Используем эмодзи 💝',
    r'Path\(__file__\)\.parent / "x\.png"': 'None  # Используем эмодзи ❌',
    r'Path\(__file__\)\.parent / "ques\.png"': 'None  # Используем эмодзи ❓',
    r'Path\(__file__\)\.parent / "spravka\.png"': 'None  # Используем эмодзи ❓',
    r'Path\(__file__\)\.parent / "con\.png"': 'None  # Используем эмодзи 📞',
    r'Path\(__file__\)\.parent / "steam\.png"': 'None  # Используем эмодзи 🎮',
    r'Path\(__file__\)\.parent / "steamg\.png"': 'None  # Используем эмодзи 🎮',
    r'Path\(__file__\)\.parent / "tg\.png"': 'None  # Используем эмодзи 📱',
    r'Path\(__file__\)\.parent / "noadd\.png"': 'None  # Используем эмодзи ❌',
    r'Path\(__file__\)\.parent / "wall\.jpg"': 'None  # Убираем фон',
}

def clean_icons_in_file(file_path):
    """Заменяет PNG иконки на эмодзи в файле"""
    print(f"Обрабатываем файл: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    
    # Применяем замены
    for pattern, replacement in REPLACEMENTS.items():
        content = re.sub(pattern, replacement, content)
    
    # Если были изменения, сохраняем файл
    if content != original_content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✅ Файл обновлен: {file_path}")
        return True
    else:
        print(f"ℹ️ Изменений не требуется: {file_path}")
        return False

def main():
    """Основная функция"""
    print("🧹 Очистка PNG иконок и замена на эмодзи...")
    
    # Файлы для обработки
    files_to_process = [
        Path("../RELEASE_READY/l4d2_pyqt_main.py"),
        Path("../RELEASE_READY/modern_updater.py")
    ]
    
    updated_files = 0
    
    for file_path in files_to_process:
        if file_path.exists():
            if clean_icons_in_file(file_path):
                updated_files += 1
        else:
            print(f"❌ Файл не найден: {file_path}")
    
    print(f"\n✅ Готово! Обновлено файлов: {updated_files}")
    print("📝 Теперь можно удалить все PNG файлы кроме тех что в папке assets")

if __name__ == "__main__":
    main()