@echo off
echo ========================================
echo  L4D2 Addon Manager v1.3.0 - Установка
echo ========================================
echo.

echo Проверяем Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python не найден! Установите Python 3.8+ с python.org
    pause
    exit /b 1
)

echo ✅ Python найден
echo.

echo Устанавливаем зависимости...
pip install PyQt6 requests
if errorlevel 1 (
    echo ❌ Ошибка установки зависимостей
    pause
    exit /b 1
)

echo ✅ Зависимости установлены
echo.

echo Запускаем L4D2 Addon Manager...
python l4d2_pyqt_main.py

pause