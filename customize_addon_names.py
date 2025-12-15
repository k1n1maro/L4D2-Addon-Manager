#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Интерактивная настройка названий аддонов
"""

import json
from pathlib import Path

def load_cache():
    """Загружает кэш"""
    cache_file = Path.home() / ".l4d2_addon_names_cache.json"
    
    if not cache_file.exists():
        print("❌ Кэш не найден")
        return None, None
    
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache = json.load(f)
        return cache, cache_file
    except Exception as e:
        print(f"❌ Ошибка загрузки кэша: {e}")
        return None, None

def save_cache(cache, cache_file):
    """Сохраняет кэш"""
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения: {e}")
        return False

def show_addons_by_category(cache):
    """Показывает аддоны по категориям"""
    categories = {}
    
    for addon_id, data in cache.items():
        name = data['name']
        
        # Определяем категорию
        if "Оружие мод" in name:
            category = "🔫 Оружие"
        elif "Карты мод" in name:
            category = "🗺️ Карты"
        elif "Звуки мод" in name:
            category = "🔊 Звуки"
        elif "Персонажи мод" in name:
            category = "👤 Персонажи"
        elif "Интерфейс мод" in name:
            category = "🖥️ Интерфейс"
        elif "Эффекты мод" in name:
            category = "✨ Эффекты"
        elif "Модели мод" in name:
            category = "🎭 Модели"
        elif "Текстуры мод" in name:
            category = "🎨 Текстуры"
        elif "Геймплей мод" in name:
            category = "🎮 Геймплей"
        elif "Разное мод" in name:
            category = "📦 Разное"
        else:
            category = "✅ Загруженные"
        
        if category not in categories:
            categories[category] = []
        categories[category].append((addon_id, name))
    
    # Показываем по категориям
    for category, addons in sorted(categories.items()):
        print(f"\n{category} ({len(addons)}):")
        for i, (addon_id, name) in enumerate(addons, 1):
            print(f"  {i:2d}. {name} (ID: {addon_id})")

def interactive_rename(cache, cache_file):
    """Интерактивное переименование"""
    while True:
        print("\n" + "="*60)
        print("🏷️ Интерактивное переименование аддонов")
        print("="*60)
        
        show_addons_by_category(cache)
        
        print(f"\n📋 Команды:")
        print("• Введите ID аддона для переименования")
        print("• 'list' - показать список снова")
        print("• 'save' - сохранить и выйти")
        print("• 'exit' - выйти без сохранения")
        
        choice = input("\n➤ Ваш выбор: ").strip()
        
        if choice.lower() == 'exit':
            print("👋 Выход без сохранения")
            break
        elif choice.lower() == 'save':
            if save_cache(cache, cache_file):
                print("✅ Кэш сохранен!")
            break
        elif choice.lower() == 'list':
            continue
        elif choice.isdigit() and choice in cache:
            # Переименование аддона
            addon_id = choice
            current_name = cache[addon_id]['name']
            
            print(f"\n📝 Переименование аддона {addon_id}")
            print(f"Текущее название: {current_name}")
            
            new_name = input("Введите новое название (Enter для отмены): ").strip()
            
            if new_name:
                cache[addon_id]['name'] = new_name
                cache[addon_id]['original_name'] = current_name
                print(f"✅ Переименовано: {current_name} → {new_name}")
            else:
                print("❌ Отменено")
        else:
            print("❌ Неверный выбор. Введите ID аддона или команду.")

def quick_setup():
    """Быстрая настройка популярных категорий"""
    cache, cache_file = load_cache()
    if not cache:
        return
    
    print("🚀 Быстрая настройка названий")
    print("=" * 40)
    
    # Предлагаем быстрые варианты
    quick_names = {
        "Оружие мод": [
            "AK-47 модификация",
            "M4A1 кастом",
            "Снайперская винтовка",
            "Дробовик улучшенный",
            "Пистолет модифицированный"
        ],
        "Карты мод": [
            "Новая кампания",
            "Выживание карта",
            "Мультиплеер арена",
            "Кооп миссия",
            "Хоррор карта"
        ],
        "Звуки мод": [
            "Новые звуки оружия",
            "Музыка замена",
            "Голоса персонажей",
            "Звуки окружения",
            "Эффекты звуков"
        ]
    }
    
    updated = 0
    for addon_id, data in cache.items():
        current_name = data['name']
        
        for category, suggestions in quick_names.items():
            if category in current_name:
                print(f"\n📝 {addon_id}: {current_name}")
                print("Предложения:")
                for i, suggestion in enumerate(suggestions, 1):
                    print(f"  {i}. {suggestion}")
                print("  0. Пропустить")
                
                try:
                    choice = int(input("Выберите (0-5): "))
                    if 1 <= choice <= len(suggestions):
                        new_name = suggestions[choice - 1]
                        data['name'] = new_name
                        data['original_name'] = current_name
                        updated += 1
                        print(f"✅ Обновлено: {new_name}")
                except (ValueError, IndexError):
                    print("⏭️ Пропущено")
                break
    
    if updated > 0:
        if save_cache(cache, cache_file):
            print(f"\n✅ Обновлено {updated} названий и сохранено!")
    else:
        print("\n📋 Изменений не было")

def main():
    """Основная функция"""
    print("🏷️ Настройка названий аддонов")
    print("=" * 40)
    
    cache, cache_file = load_cache()
    if not cache:
        return
    
    print("Выберите режим:")
    print("1. Интерактивное переименование")
    print("2. Быстрая настройка")
    print("3. Просто показать список")
    
    choice = input("\nВаш выбор (1-3): ").strip()
    
    if choice == "1":
        interactive_rename(cache, cache_file)
    elif choice == "2":
        quick_setup()
    elif choice == "3":
        show_addons_by_category(cache)
    else:
        print("❌ Неверный выбор")
    
    print("\n📋 После изменений перезапустите L4D2 Addon Manager")

if __name__ == "__main__":
    main()