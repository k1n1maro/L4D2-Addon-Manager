#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Предварительное кэширование изображений аддонов
"""

import json
import hashlib
import time
from pathlib import Path
from urllib.request import urlopen
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_cache_path(url):
    """Получает путь к кэшированному изображению"""
    try:
        url_hash = hashlib.md5(url.encode()).hexdigest()
        cache_dir = Path.home() / ".l4d2_icon_cache"
        cache_dir.mkdir(exist_ok=True)
        return cache_dir / f"{url_hash}.jpg"
    except:
        return None

def download_image(url, cache_path):
    """Загружает и кэширует одно изображение"""
    try:
        if cache_path.exists():
            return f"✅ Уже в кэше: {url[-20:]}"
        
        data = urlopen(url, timeout=3).read()
        
        # Сохраняем в кэш
        with open(cache_path, 'wb') as f:
            f.write(data)
        
        return f"✅ Загружено: {url[-20:]}"
        
    except Exception as e:
        return f"❌ Ошибка: {url[-20:]} - {e}"

def precache_all_images():
    """Предварительно кэширует все изображения"""
    # Загружаем кэш названий
    cache_file = Path.home() / ".l4d2_addon_names_cache.json"
    
    if not cache_file.exists():
        print("❌ Кэш названий не найден")
        return False
    
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache = json.load(f)
    except Exception as e:
        print(f"❌ Ошибка загрузки кэша: {e}")
        return False
    
    # Собираем URL изображений (здесь нужно будет добавить реальные URL)
    # Для примера создаем список с Steam URL
    image_urls = []
    
    # Добавляем известные URL из Steam (примерные)
    steam_base = "https://images.steamusercontent.com/ugc/"
    
    # Здесь можно добавить реальные URL из вашего лога
    known_urls = [
        "https://images.steamusercontent.com/ugc/554262075760483400/C2505BCDD10FB02EFF570ABA2593B605DB07429C/",
        "https://images.steamusercontent.com/ugc/1811012788052006782/CE2DD837659FE567807C6AC7F2B5DB086B27ADC7/",
        "https://images.steamusercontent.com/ugc/1811012634060256238/22CF6D75258485ACC8960581AD0437078F3FEA08/",
        "https://images.steamusercontent.com/ugc/2113934296254140063/80F19D072EC347094857AB006BE30606AF1AC722/",
        "https://images.steamusercontent.com/ugc/10998723519974956819/CC063FEC14CF981DD66DAE0654541A675E6FFF87/"
    ]
    
    image_urls.extend(known_urls)
    
    if not image_urls:
        print("⚠️ Нет URL для кэширования")
        return True
    
    print(f"🔄 Начинаем кэширование {len(image_urls)} изображений...")
    print("-" * 60)
    
    # Создаем задачи для загрузки
    tasks = []
    for url in image_urls:
        cache_path = get_cache_path(url)
        if cache_path:
            tasks.append((url, cache_path))
    
    # Загружаем параллельно (до 5 потоков)
    success_count = 0
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_url = {
            executor.submit(download_image, url, cache_path): url 
            for url, cache_path in tasks
        }
        
        for future in as_completed(future_to_url):
            result = future.result()
            print(result)
            if "✅" in result:
                success_count += 1
    
    print(f"\n📊 Результат:")
    print(f"   ✅ Успешно: {success_count}")
    print(f"   ❌ Ошибок: {len(tasks) - success_count}")
    print(f"   📁 Папка кэша: {Path.home() / '.l4d2_icon_cache'}")
    
    return True

def clear_cache():
    """Очищает кэш изображений"""
    cache_dir = Path.home() / ".l4d2_icon_cache"
    
    if not cache_dir.exists():
        print("📁 Кэш не найден")
        return
    
    try:
        import shutil
        shutil.rmtree(cache_dir)
        print("🗑️ Кэш изображений очищен")
    except Exception as e:
        print(f"❌ Ошибка очистки: {e}")

def show_cache_info():
    """Показывает информацию о кэше"""
    cache_dir = Path.home() / ".l4d2_icon_cache"
    
    if not cache_dir.exists():
        print("📁 Кэш не найден")
        return
    
    try:
        files = list(cache_dir.glob("*.jpg"))
        total_size = sum(f.stat().st_size for f in files)
        
        print(f"📊 Информация о кэше:")
        print(f"   📁 Папка: {cache_dir}")
        print(f"   🖼️ Файлов: {len(files)}")
        print(f"   💾 Размер: {total_size / 1024 / 1024:.1f} МБ")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")

def main():
    """Основная функция"""
    print("🖼️ Управление кэшем изображений L4D2 Addon Manager")
    print("=" * 60)
    
    while True:
        print("\nВыберите действие:")
        print("1. Предварительно кэшировать изображения")
        print("2. Показать информацию о кэше")
        print("3. Очистить кэш")
        print("4. Выход")
        
        choice = input("\nВаш выбор (1-4): ").strip()
        
        if choice == "1":
            precache_all_images()
        elif choice == "2":
            show_cache_info()
        elif choice == "3":
            clear_cache()
        elif choice == "4":
            print("👋 До свидания!")
            break
        else:
            print("❌ Неверный выбор")

if __name__ == "__main__":
    main()