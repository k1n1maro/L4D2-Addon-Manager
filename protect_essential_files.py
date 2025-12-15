#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Система защиты важных файлов проекта
Предотвращает случайное удаление критически важных файлов
"""

import os
import shutil
from pathlib import Path
from datetime import datetime

# Список критически важных файлов, которые НЕЛЬЗЯ удалять
ESSENTIAL_FILES = {
    # Основные системные файлы
    'core': [
        'l4d2_pyqt_main.py',  # Главная программа
        'requirements.txt',   # Зависимости
        'LICENSE',           # Лицензия
        '.gitignore',        # Git настройки
    ],
    
    # Система обновлений (КРИТИЧНО!)
    'updater': [
        'modern_updater.py',  # Система обновлений
        'update_config.py',   # Конфигурация обновлений
    ],
    
    # Локализация и интерфейс
    'localization': [
        'localization.py',
        'language_dialog.py',
    ],
    
    # Основные ресурсы
    'resources': [
        'icon.ico',
        'logo.png', 
        'sans.ttf',
    ],
    
    # Полезные утилиты
    'utilities': [
        'fetch_real_names.py',
        'customize_addon_names.py',
        'precache_images.py',
        'create_cache_for_unprocessed.py',
    ],
    
    # Сборка
    'build': [
        'L4D2_Addon_Manager.spec',
        'install_and_run.bat',
    ],
    
    # Документация
    'docs': [
        'README.md',
        'CHANGELOG.md', 
        'INSTALL.md',
        'PROJECT_STRUCTURE.md',
        'ESSENTIAL_FILES.md',
    ],
    
    # Основные иконки интерфейса
    'icons': [
        'add.png', 'addon.png', 'alloff.png', 'allon.png',
        'settings.png', 'info.png', 'tg.png', 'heart.png',
        'upd.png', 'ref.png', 'folder.png', 'con.png',
        'git.png', 'link.png', 'sort.png', 'trash.png',
        'x.png', 'ques.png', 'lang.png', 'noadd.png',
        'spravka.png', 'sup.png',
    ]
}

# Папки, которые нужно сохранять
ESSENTIAL_FOLDERS = [
    'screenshots',  # Скриншоты для документации
    '.git',        # Git репозиторий
]

def get_all_essential_files():
    """Возвращает полный список всех важных файлов"""
    all_files = []
    for category, files in ESSENTIAL_FILES.items():
        all_files.extend(files)
    return all_files

def check_essential_files():
    """Проверяет наличие всех важных файлов"""
    print("🔍 Проверка важных файлов...")
    
    missing_files = []
    present_files = []
    
    for category, files in ESSENTIAL_FILES.items():
        print(f"\n📂 Категория: {category}")
        
        for file_name in files:
            file_path = Path(file_name)
            if file_path.exists():
                print(f"  ✅ {file_name}")
                present_files.append(file_name)
            else:
                print(f"  ❌ {file_name} - ОТСУТСТВУЕТ!")
                missing_files.append(file_name)
    
    print(f"\n📊 Статистика:")
    print(f"  ✅ Найдено: {len(present_files)} файлов")
    print(f"  ❌ Отсутствует: {len(missing_files)} файлов")
    
    if missing_files:
        print(f"\n⚠️ ВНИМАНИЕ! Отсутствуют важные файлы:")
        for file_name in missing_files:
            print(f"  • {file_name}")
        print(f"\n💡 Попробуйте восстановить из Git: git checkout HEAD -- <имя_файла>")
    
    return missing_files

def create_backup():
    """Создает резервную копию всех важных файлов"""
    backup_dir = Path("backups") / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"💾 Создание резервной копии в {backup_dir}...")
    
    backed_up = 0
    for file_name in get_all_essential_files():
        file_path = Path(file_name)
        if file_path.exists():
            try:
                backup_path = backup_dir / file_name
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_path, backup_path)
                backed_up += 1
            except Exception as e:
                print(f"  ❌ Ошибка копирования {file_name}: {e}")
        else:
            print(f"  ⚠️ Файл {file_name} не найден для резервного копирования")
    
    print(f"✅ Создана резервная копия {backed_up} файлов")
    return backup_dir

def is_safe_to_delete(file_path):
    """Проверяет, безопасно ли удалять файл"""
    file_name = Path(file_path).name
    
    # Проверяем, не является ли файл важным
    if file_name in get_all_essential_files():
        return False, f"❌ КРИТИЧЕСКИЙ ФАЙЛ! {file_name} нельзя удалять!"
    
    # Проверяем паттерны безопасных для удаления файлов
    safe_patterns = [
        'debug_', 'test_', 'temp_', 'tmp_',
        '_GUIDE.md', '_FIX.md', '_SOLUTION.md', 
        'QUICK_', 'GAMEBANANA_', 'STEAM_POST_',
    ]
    
    for pattern in safe_patterns:
        if pattern in file_name:
            return True, f"✅ Безопасно удалить: {file_name} (паттерн: {pattern})"
    
    return None, f"⚠️ Неизвестный файл: {file_name} - проверьте вручную!"

def scan_for_deletable_files():
    """Сканирует проект и показывает, какие файлы можно удалить"""
    print("🔍 Сканирование файлов для потенциального удаления...")
    
    safe_to_delete = []
    check_manually = []
    protected = []
    
    for file_path in Path('.').glob('*.py'):
        if file_path.name == __file__.split('/')[-1]:  # Пропускаем этот скрипт
            continue
            
        is_safe, reason = is_safe_to_delete(file_path)
        
        if is_safe is True:
            safe_to_delete.append((file_path, reason))
        elif is_safe is False:
            protected.append((file_path, reason))
        else:
            check_manually.append((file_path, reason))
    
    # Проверяем .md файлы
    for file_path in Path('.').glob('*.md'):
        is_safe, reason = is_safe_to_delete(file_path)
        
        if is_safe is True:
            safe_to_delete.append((file_path, reason))
        elif is_safe is False:
            protected.append((file_path, reason))
        else:
            check_manually.append((file_path, reason))
    
    print(f"\n🛡️ Защищенные файлы ({len(protected)}):")
    for file_path, reason in protected:
        print(f"  {reason}")
    
    print(f"\n✅ Безопасно удалить ({len(safe_to_delete)}):")
    for file_path, reason in safe_to_delete:
        print(f"  {reason}")
    
    print(f"\n⚠️ Требуют ручной проверки ({len(check_manually)}):")
    for file_path, reason in check_manually:
        print(f"  {reason}")
    
    return safe_to_delete, check_manually, protected

def interactive_cleanup():
    """Интерактивная очистка с подтверждением"""
    print("🧹 Интерактивная очистка проекта")
    print("=" * 50)
    
    # Сначала создаем резервную копию
    backup_dir = create_backup()
    print(f"💾 Резервная копия создана: {backup_dir}")
    
    # Сканируем файлы
    safe_to_delete, check_manually, protected = scan_for_deletable_files()
    
    if safe_to_delete:
        print(f"\n🗑️ Найдено {len(safe_to_delete)} файлов для безопасного удаления:")
        for file_path, reason in safe_to_delete:
            print(f"  • {file_path.name}")
        
        response = input(f"\nУдалить эти {len(safe_to_delete)} файлов? (y/N): ")
        if response.lower() in ['y', 'yes', 'да']:
            deleted = 0
            for file_path, reason in safe_to_delete:
                try:
                    file_path.unlink()
                    print(f"  ✅ Удален: {file_path.name}")
                    deleted += 1
                except Exception as e:
                    print(f"  ❌ Ошибка удаления {file_path.name}: {e}")
            print(f"\n🎉 Удалено {deleted} файлов")
        else:
            print("❌ Удаление отменено")
    
    if check_manually:
        print(f"\n⚠️ Файлы для ручной проверки ({len(check_manually)}):")
        for file_path, reason in check_manually:
            print(f"  • {file_path.name} - {reason}")
        print("💡 Проверьте эти файлы вручную перед удалением")

def main():
    """Главная функция"""
    print("🛡️ Система защиты важных файлов L4D2 Addon Manager")
    print("=" * 60)
    
    while True:
        print("\nВыберите действие:")
        print("1. 🔍 Проверить наличие важных файлов")
        print("2. 💾 Создать резервную копию")
        print("3. 🔍 Сканировать файлы для удаления")
        print("4. 🧹 Интерактивная очистка")
        print("5. 📋 Показать список важных файлов")
        print("0. ❌ Выход")
        
        choice = input("\nВведите номер (0-5): ").strip()
        
        if choice == '1':
            missing = check_essential_files()
            if not missing:
                print("🎉 Все важные файлы на месте!")
        
        elif choice == '2':
            backup_dir = create_backup()
            print(f"✅ Резервная копия создана: {backup_dir}")
        
        elif choice == '3':
            scan_for_deletable_files()
        
        elif choice == '4':
            interactive_cleanup()
        
        elif choice == '5':
            print("\n📋 Список важных файлов:")
            for category, files in ESSENTIAL_FILES.items():
                print(f"\n📂 {category.upper()}:")
                for file_name in files:
                    status = "✅" if Path(file_name).exists() else "❌"
                    print(f"  {status} {file_name}")
        
        elif choice == '0':
            print("👋 До свидания!")
            break
        
        else:
            print("❌ Неверный выбор!")

if __name__ == "__main__":
    main()