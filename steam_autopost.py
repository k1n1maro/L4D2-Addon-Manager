#!/usr/bin/env python3
"""
Steam Community Auto-Poster for GitHub Releases
Публикует новые релизы в Steam Discussions для Left 4 Dead 2
"""

import os
import sys
import time
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException


class SteamPoster:
    def __init__(self, login, password, version):
        self.login = login
        self.password = password
        self.version = version
        self.driver = None
        self.posted_versions_file = Path("posted_versions.txt")
        
    def is_already_posted(self):
        """Проверяет, был ли уже опубликован этот релиз"""
        if not self.posted_versions_file.exists():
            return False
        
        with open(self.posted_versions_file, 'r') as f:
            posted = f.read().splitlines()
        
        return self.version in posted
    
    def mark_as_posted(self):
        """Добавляет версию в список опубликованных"""
        with open(self.posted_versions_file, 'a') as f:
            f.write(f"{self.version}\n")
        print(f"✓ Версия {self.version} добавлена в posted_versions.txt")
    
    def setup_driver(self):
        """Настройка Chrome WebDriver"""
        chrome_options = Options()
        
        # Для GitHub Actions
        if os.getenv('CI'):
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
        
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        
        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.maximize_window()
        print("✓ WebDriver запущен")
    
    def login_steam(self):
        """Авторизация в Steam"""
        print("→ Переход на страницу логина Steam...")
        self.driver.get("https://steamcommunity.com/login/home/")
        
        wait = WebDriverWait(self.driver, 20)
        
        # Ввод логина
        print("→ Ввод логина...")
        username_field = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text']"))
        )
        username_field.clear()
        username_field.send_keys(self.login)
        time.sleep(1)
        
        # Ввод пароля
        print("→ Ввод пароля...")
        password_field = self.driver.find_element(By.CSS_SELECTOR, "input[type='password']")
        password_field.clear()
        password_field.send_keys(self.password)
        time.sleep(1)
        
        # Нажатие кнопки входа
        print("→ Нажатие кнопки Sign In...")
        sign_in_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        sign_in_button.click()
        
        # Ожидание Steam Guard (если требуется)
        print("\n⚠ ВНИМАНИЕ: Если требуется Steam Guard код, введите его вручную!")
        print("⏳ Ожидание завершения авторизации (до 120 секунд)...\n")
        
        try:
            # Ждём, пока не окажемся на главной странице сообщества
            wait = WebDriverWait(self.driver, 120)
            wait.until(lambda d: "steamcommunity.com" in d.current_url and "/login" not in d.current_url)
            print("✓ Авторизация успешна!")
            time.sleep(2)
            return True
        except TimeoutException:
            print("✗ Таймаут авторизации")
            return False
    
    def navigate_to_discussions(self):
        """Переход в раздел обсуждений L4D2"""
        print("→ Переход в L4D2 Discussions...")
        self.driver.get("https://steamcommunity.com/app/550/discussions/")
        time.sleep(3)
        print("✓ Открыт раздел обсуждений")
    
    def create_post(self):
        """Создание нового поста"""
        wait = WebDriverWait(self.driver, 15)
        
        # Нажатие кнопки "Start a New Discussion"
        print("→ Поиск кнопки создания темы...")
        try:
            new_topic_button = wait.until(
                EC.element_to_be_clickable((By.LINK_TEXT, "Start a New Discussion"))
            )
            new_topic_button.click()
            time.sleep(2)
            print("✓ Форма создания темы открыта")
        except:
            print("✗ Не удалось найти кнопку создания темы")
            return False
        
        # Заполнение заголовка
        title = f"L4D2 Addon Manager {self.version} — simple addon control tool"
        print(f"→ Заполнение заголовка: {title}")
        
        title_field = wait.until(
            EC.presence_of_element_located((By.ID, "topic"))
        )
        title_field.clear()
        title_field.send_keys(title)
        time.sleep(1)
        
        # Заполнение текста поста
        body = f"""I released a new version of my L4D2 addon manager.

Features:
• Enable / disable addons in one click
• No manual folder editing
• Works with Workshop addons

Free & open-source:
https://github.com/k1n1maro/L4D2-Addon-Manager/releases/tag/{self.version}

Feedback is welcome 👍"""
        
        print("→ Заполнение текста поста...")
        body_field = self.driver.find_element(By.ID, "text")
        body_field.clear()
        body_field.send_keys(body)
        time.sleep(1)
        
        # Публикация
        print("→ Публикация поста...")
        submit_button = self.driver.find_element(By.ID, "submit")
        submit_button.click()
        
        time.sleep(5)
        print("✓ Пост опубликован!")
        return True
    
    def run(self):
        """Основной процесс"""
        try:
            # Проверка на дубликат
            if self.is_already_posted():
                print(f"⚠ Версия {self.version} уже была опубликована. Пропуск.")
                return True
            
            print(f"\n{'='*60}")
            print(f"Steam Auto-Poster для L4D2 Addon Manager {self.version}")
            print(f"{'='*60}\n")
            
            self.setup_driver()
            
            if not self.login_steam():
                return False
            
            self.navigate_to_discussions()
            
            if not self.create_post():
                return False
            
            # Отмечаем как опубликованное
            self.mark_as_posted()
            
            print(f"\n{'='*60}")
            print("✓ УСПЕШНО! Релиз опубликован в Steam Community")
            print(f"{'='*60}\n")
            
            return True
            
        except Exception as e:
            print(f"\n✗ ОШИБКА: {e}")
            import traceback
            traceback.print_exc()
            return False
            
        finally:
            if self.driver:
                time.sleep(3)
                self.driver.quit()
                print("✓ WebDriver закрыт")


def main():
    # Получение данных из переменных окружения
    login = os.getenv('STEAM_LOGIN')
    password = os.getenv('STEAM_PASSWORD')
    version = os.getenv('RELEASE_VERSION')
    
    if not all([login, password, version]):
        print("✗ ОШИБКА: Не заданы переменные окружения!")
        print("Требуются: STEAM_LOGIN, STEAM_PASSWORD, RELEASE_VERSION")
        sys.exit(1)
    
    poster = SteamPoster(login, password, version)
    success = poster.run()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
