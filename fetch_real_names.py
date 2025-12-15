#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Загрузка точных названий из Steam Workshop для всех аддонов
"""

import json
import time
import urllib.parse
from pathlib import Path
from urllib.request import urlopen

def get_addon_info_from_steam(addon_id):
    """Получает информацию об аддоне из Steam API"""
    try:
        # Формируем запрос для одного аддона
        post_data = {
            'itemcount': 1,
            'publishedfileids[0]': addon_id
        }
        
        data = urllib.parse.urlencode(post_data).encode('utf-8')
        response = urlopen(
            "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/", 
            data=data, 
            timeout=10
        )
        result = json.loads(response.read().decode('utf-8'))
        
        if result.get('response', {}).get('publishedfiledetails'):
            detail = result['response']['publishedfiledetails'][0]
            result_code = detail.get('result', 0)
            
            if result_code == 1:  # Success
                return {
                    'success': True,
                    'title': detail.get('title', f'Аддон {addon_id}'),
                    'description': detail.get('description', ''),
                    'preview_url': detail.get('preview_url', ''),
                    'status': 'available'
                }
            elif result_code == 9:
                return {
                    'success': False,
                    'reason': 'Аддон не найден или удален',
                    'status': 'not_found'
                }
            elif result_code == 17:
                return {
                    'success': False,
                    'reason': 'Аддон приватный',
                    'status': 'private'
                }
            else:
                return {
                    'success': False,
                    'reason': f'Ошибка Steam API (код: {result_code})',
                    'status': 'error'
                }
        
        return {
            'success': False,
            'reason': 'Нет данных от Steam API',
            'status': 'no_data'
        }
        
    except Exception as e:
        return {
            'success': False,
            'reason': f'Ошибка запроса: {e}',
            'status': 'request_error'
        }

def load_current_cache():
    """Загружает текущий кэш"""
    cache_file = Path.home() / ".l4d2_addon_names_cache.json"
    
    if cache_file.exists():
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f), cache_file
        except Exception as e:
            print(f"❌ Ошибка загрузки кэша: {e}")
    
    return {}, cache_file

def save_cache(cache, cache_file):
    """Сохраняет кэш"""
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения: {e}")
        return False

def fetch_real_names():
    """Загружает реальные названия для всех аддонов"""
    cache, cache_file = load_current_cache()
    
    # Находим аддоны, которые нужно обновить
    addons_to_update = []
    
    for addon_id, data in cache.items():
        name = data.get('name', '')
        status = data.get('status', 'unknown')
        
        # Обновляем аддоны с автоматически сгенерированными названиями
        if any(x in name for x in ['мод #', 'Неизвестный аддон', 'Недоступный аддон']) or status == 'unprocessed':
            addons_to_update.append(addon_id)
    
    if not addons_to_update:
        print("✅ Все аддоны уже имеют правильные названия!")
        return True
    
    print(f"🔍 Найдено {len(addons_to_update)} аддонов для обновления")
    print("🌐 Загружаем точные названия из Steam Workshop...")
    print("-" * 60)
    
    updated_count = 0
    failed_count = 0
    
    for i, addon_id in enumerate(addons_to_update, 1):
        current_name = cache[addon_id].get('name', f'Аддон {addon_id}')
        
        print(f"[{i:2d}/{len(addons_to_update)}] 🔍 {addon_id}: {current_name}")
        
        # Получаем информацию из Steam
        steam_info = get_addon_info_from_steam(addon_id)
        
        if steam_info['success']:
            # Успешно получили название
            old_name = cache[addon_id]['name']
            cache[addon_id]['name'] = steam_info['title']
            cache[addon_id]['original_name'] = old_name
            cache[addon_id]['status'] = 'available'
            cache[addon_id]['timestamp'] = int(time.time())
            
            updated_count += 1
            print(f"         ✅ {steam_info['title']}")
        else:
            # Не удалось получить название
            failed_count += 1
            status = steam_info['status']
            reason = steam_info['reason']
            
            # Обновляем статус в кэше
            cache[addon_id]['status'] = status
            
            if status == 'not_found':
                cache[addon_id]['name'] = f"Удаленный аддон {addon_id}"
            elif status == 'private':
                cache[addon_id]['name'] = f"Приватный аддон {addon_id}"
            else:
                cache[addon_id]['name'] = f"Недоступный аддон {addon_id}"
            
            print(f"         ❌ {reason}")
        
        # Пауза между запросами чтобы не перегружать Steam API
        if i < len(addons_to_update):
            time.sleep(0.8)  # 800ms между запросами
    
    # Сохраняем обновленный кэш
    if save_cache(cache, cache_file):
        print(f"\n✅ Кэш обновлен и сохранен!")
        print(f"📊 Статистика:")
        print(f"   ✅ Успешно обновлено: {updated_count}")
        print(f"   ❌ Не удалось обновить: {failed_count}")
        print(f"   📁 Всего в кэше: {len(cache)}")
        
        # Показываем статистику по статусам
        statuses = {}
        for data in cache.values():
            status = data.get('status', 'unknown')
            statuses[status] = statuses.get(status, 0) + 1
        
        print(f"\n📈 Распределение по статусам:")
        for status, count in statuses.items():
            status_emoji = {
                'available': '✅',
                'not_found': '❌',
                'private': '🔒',
                'error': '⚠️',
                'unprocessed': '❓'
            }.get(status, '❓')
            print(f"   {status_emoji} {status}: {count}")
        
        return True
    else:
        print(f"\n❌ Ошибка сохранения кэша")
        return False

def show_sample_results():
    """Показывает примеры результатов"""
    cache, _ = load_current_cache()
    
    print(f"\n📋 Примеры обновленных названий:")
    print("-" * 50)
    
    count = 0
    for addon_id, data in cache.items():
        if count >= 10:  # Показываем только первые 10
            break
            
        name = data['name']
        status = data.get('status', 'unknown')
        
        status_emoji = {
            'available': '✅',
            'not_found': '❌',
            'private': '🔒',
            'error': '⚠️'
        }.get(status, '❓')
        
        print(f"{status_emoji} {addon_id}: {name}")
        count += 1
    
    if len(cache) > 10:
        print(f"... и еще {len(cache) - 10} аддонов")

def main():
    """Основная функция"""
    print("🌐 Загрузка точных названий из Steam Workshop")
    print("=" * 60)
    
    print("Этот скрипт:")
    print("• Проверит каждый аддон индивидуально через Steam API")
    print("• Загрузит точные названия из Steam Workshop")
    print("• Обновит кэш с правильными названиями")
    print("• Займет несколько минут (пауза между запросами)")
    print()
    
    choice = input("Продолжить загрузку? (y/n): ").lower().strip()
    
    if choice == 'y':
        if fetch_real_names():
            show_sample_results()
            print(f"\n🎉 Готово!")
            print(f"\n📋 Следующие шаги:")
            print("1. Полностью перезапустите L4D2 Addon Manager")
            print("2. Теперь аддоны будут показывать точные названия из Steam")
            print("3. Аддоны, которые недоступны, будут помечены соответственно")
        else:
            print(f"\n❌ Произошла ошибка")
    else:
        print("👋 Отменено пользователем")

if __name__ == "__main__":
    main()