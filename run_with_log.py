import sys
import traceback
from datetime import datetime

# Перенаправляем stderr в файл
log_file = open('error_log.txt', 'w', encoding='utf-8')
sys.stderr = log_file

try:
    # Импортируем и запускаем основную программу
    import l4d2_pyqt_main
except Exception as e:
    print(f"\n{'='*60}", file=log_file)
    print(f"ОШИБКА: {datetime.now()}", file=log_file)
    print(f"{'='*60}", file=log_file)
    print(f"\nТип ошибки: {type(e).__name__}", file=log_file)
    print(f"Сообщение: {str(e)}", file=log_file)
    print(f"\nПолный traceback:", file=log_file)
    traceback.print_exc(file=log_file)
    print(f"\n{'='*60}", file=log_file)
finally:
    log_file.close()
