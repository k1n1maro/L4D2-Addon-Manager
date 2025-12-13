#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Создает чистую версию приложения с минимальными PNG зависимостями
"""

import shutil
from pathlib import Path

def create_clean_version():
    """Создает чистую версию без лишних PNG файлов"""
    
    print("🧹 Создание чистой версии приложения...")
    
    # Создаем папку для чистой версии
    clean_dir = Path("../CLEAN_VERSION")
    if clean_dir.exists():
        shutil.rmtree(clean_dir)
    clean_dir.mkdir()
    
    # Копируем основные файлы
    files_to_copy = [
        "../RELEASE_READY/l4d2_pyqt_main.py",
        "../RELEASE_READY/modern_updater.py", 
        "../RELEASE_READY/update_config.py",
        "../RELEASE_READY/README.md",
        "../RELEASE_READY/LICENSE",
        "../RELEASE_READY/requirements.txt",
        "../RELEASE_READY/.gitignore"
    ]
    
    for file_path in files_to_copy:
        src = Path(file_path)
        if src.exists():
            dst = clean_dir / src.name
            shutil.copy2(src, dst)
            print(f"✅ Скопирован: {src.name}")
    
    # Копируем только самые важные иконки
    assets_dir = clean_dir / "assets"
    assets_dir.mkdir()
    
    essential_icons = [
        "../RELEASE_READY/assets/logo.png",
        "../RELEASE_READY/assets/folder.png", 
        "../RELEASE_READY/assets/info.png",
        "../RELEASE_READY/assets/settings.png",
        "../RELEASE_READY/assets/git.png"
    ]
    
    for icon_path in essential_icons:
        src = Path(icon_path)
        if src.exists():
            dst = assets_dir / src.name
            shutil.copy2(src, dst)
            print(f"✅ Скопирована иконка: {src.name}")
    
    # Создаем .gitignore для исключения лишних файлов
    gitignore_content = """# Исключаем лишние PNG файлы
*.png
!assets/logo.png
!assets/folder.png
!assets/info.png
!assets/settings.png
!assets/git.png

# Python
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db
"""
    
    with open(clean_dir / ".gitignore", "w", encoding="utf-8") as f:
        f.write(gitignore_content)
    
    print(f"\n✅ Чистая версия создана в папке: {clean_dir}")
    print("📁 Содержимое:")
    for item in sorted(clean_dir.rglob("*")):
        if item.is_file():
            print(f"  📄 {item.relative_to(clean_dir)}")
    
    return clean_dir

if __name__ == "__main__":
    create_clean_version()