#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Быстрая проверка файла перед удалением
Использование: python check_before_delete.py имя_файла.py
"""

import sys
import subprocess
from pathlib import Path

# Импортируем список важных файлов
try:
    from protect_essential_files import get_all_essential_files, is_safe_to_delete
except ImportError:
    print("❌ Не найден файл protect_essential_files.py")
    sys.exit(1)

def check_file_usage(file_name):
    """Проверяет, используется ли файл в коде"""
    print(f"🔍 Проверка использования файла '{file_name}' в коде...")
    
    # Убираем расширение для поиска импортов
    module_name = Path(file_name).stem
    
    # Паттерны для поиска
    patterns = [
        f"import {module_name}",
        f"from {module_name}",
        f'"{file_name}"',
        f"'{file_name}'",
        module_name,
    ]
    
    found_usage = []
    
    for pattern in patterns:
        try:
            # Используем grep для поиска (работает в Git Bash на Windows)
            result = subprocess.run(
                ['grep', '-r', '-n', pattern, '.', '--include=*.py'],
                capture_output=True, text=True, shell=True
            )
            
            if result.returncode == 0 and result.stdout.strip():
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    if file_name not in line.split(':')[0]:  # Исключаем сам файл
                        found_usage.append(f"  📍 {line}")
        except:
            # Если grep не работает, используем Python поиск
            for py_file in Path('.').glob('*.py'):
                if py_file.name == file_name:
                    continue
                try:
                    with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        if pattern in content:
                            found_usage.append(f"  📍 {py_file.name}: содержит '{pattern}'")
                except:
                    continue
    
    return found_usage

def main():
    if len(sys.argv) != 2:
        print("Использование: python check_before_delete.py имя_файла.py")
        print("Пример: python check_before_delete.py debug_addon_loading.py")
        sys.exit(1)
    
    file_name = sys.argv[1]
    file_path = Path(file_name)
    
    print("🛡️ Проверка безопасности удаления файла")
    print("=" * 50)
    print(f"📁 Файл: {file_name}")
    
    # Проверяем, существует ли файл
    if not file_path.exists():
        print(f"⚠️ Файл {file_name} не найден в текущей папке")
        return
    
    # Проверяем, является ли файл важным
    is_safe, reason = is_safe_to_delete(file_path)
    
    print(f"\n🔍 Результат проверки:")
    print(f"  {reason}")
    
    if is_safe is False:
        print(f"\n❌ СТОП! Этот файл НЕЛЬЗЯ удалять!")
        print(f"💡 Он критически важен для работы программы")
        return
    
    # Проверяем использование в коде
    usage = check_file_usage(file_name)
    
    if usage:
        print(f"\n⚠️ ВНИМАНИЕ! Файл используется в коде:")
        for use in usage[:10]:  # Показываем первые 10 использований
            print(use)
        if len(usage) > 10:
            print(f"  ... и еще {len(usage) - 10} использований")
        
        print(f"\n❌ НЕ РЕКОМЕНДУЕТСЯ удалять этот файл!")
        print(f"💡 Сначала удалите все ссылки на него из кода")
    else:
        print(f"\n✅ Файл не используется в коде")
        
        if is_safe is True:
            print(f"🎉 БЕЗОПАСНО удалять этот файл!")
        else:
            print(f"⚠️ Требуется ручная проверка")
            print(f"💡 Убедитесь, что файл действительно не нужен")

if __name__ == "__main__":
    main()