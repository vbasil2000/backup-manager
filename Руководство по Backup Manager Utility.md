📖 Полный гайд по утилите управления инкрементальными бэкапами
🚀 Обзор возможностей

Утилита предоставляет полный контроль над инкрементальными бэкапами:

    🔍 Поиск файлов с фильтрами по маскам, размеру, времени

    📊 Просмотр метаданных бэкапов

    🛠️ Восстановление метаданных

    🗑️ Безопасное удаление файлов из бэкапов

    ✅ Валидация целостности бэкапов

    📤 Экспорт результатов в разные форматы

📋 Базовые команды
1. 📋 Просмотр списка бэкапов

Команда: list
bash

# Простой список бэкапов
python backup_manager.py /path/to/backups list

# Детальная информация с проверкой целостности
python backup_manager.py /path/to/backups list --detailed

Пример вывода:
text

Found 5 backups:

backup_20240101:
  Time: 2024-01-01 14:30
  Type: incremental
  Tracked: 150 files
  Deleted: 5 files
  Total operations: 155
  Size: 2.1 GB
  Files: 155
  Integrity: ✅

2. 🔄 Восстановление метаданных

Команда: recreate
bash

# Восстановить метаданные для всех бэкапов
python backup_manager.py /path/to/backups recreate

# Принудительное пересоздание (перезапись существующих)
python backup_manager.py /path/to/backups recreate --force

# Восстановить только для конкретного бэкапа
python backup_manager.py /path/to/backups recreate --backup backup_20240101

🔍 Поиск файлов в бэкапах

Команда: search
📁 Поиск по маскам файлов
bash

# Поиск всех Python файлов
python backup_manager.py /backups search --mask "*.py"

# Поиск по нескольким маскам
python backup_manager.py /backups search --mask "*.py" --mask "*.js" --mask "*.html"

# Поиск файлов содержащих "config" в имени
python backup_manager.py /backups search --mask "*config*"

# Поиск конкретного файла
python backup_manager.py /backups search --mask "settings.py"

📏 Фильтрация по размеру
bash

# Файлы больше 100MB
python backup_manager.py /backups search --mask "*.mp4" --size ">100M"

# Файлы меньше 1KB
python backup_manager.py /backups search --mask "*.txt" --size "<1K"

# Файлы от 500KB до 2MB
python backup_manager.py /backups search --mask "*.jpg" --size "500K-2M"

# Точный размер (1MB)
python backup_manager.py /backups search --mask "*.log" --size "1M"

Поддерживаемые суффиксы: K (килобайты), M (мегабайты), G (гигабайты)
⏰ Фильтрация по времени
bash

# Файлы измененные 15 января 2024
python backup_manager.py /backups search --mask "*.py" --time "2024-01-15"

# Файлы измененные до 10 января 2024
python backup_manager.py /backups search --mask "*.log" --time "<2024-01-10"

# Файлы измененные после 5 января 2024
python backup_manager.py /backups search --mask "*.db" --time ">2024-01-05"

# Файлы измененные в период с 1 по 15 января 2024
python backup_manager.py /backups search --mask "*" --time "2024-01-01..2024-01-15"

📂 Фильтрация по пути
bash

# Файлы в директории src/
python backup_manager.py /backups search --mask "*.py" --path "src/"

# Файлы в поддиректориях config/
python backup_manager.py /backups search --mask "*.json" --path "config/"

🔎 Ограничение поиска по времени бэкапов
bash

# Поиск только в последних 3 бэкапах
python backup_manager.py /backups search --mask "*.tmp" --last-backups 3

# Поиск только в последних 10 бэкапах
python backup_manager.py /backups search --mask "*.log" --last-backups 10

📤 Экспорт результатов поиска
🎨 Форматы вывода
bash

# Стандартный читаемый вывод (по умолчанию)
python backup_manager.py /backups search --mask "*.py"

# JSON вывод
python backup_manager.py /backups search --mask "*.py" --json

# CSV вывод
python backup_manager.py /backups search --mask "*.py" --csv

# Markdown вывод
python backup_manager.py /backups search --mask "*.py" --markdown

💾 Экспорт в файлы
bash

# Экспорт в JSON файл
python backup_manager.py /backups search --mask "*.py" --json --export results.json

# Экспорт в CSV файл
python backup_manager.py /backups search --mask "*.py" --csv --export results.csv

# Экспорт в Markdown файл
python backup_manager.py /backups search --mask "*.py" --markdown --export report.md

Пример CSV вывода:
csv

Backup,Path,Size,Modified,Category,Filename
backup_20240101,src/main.py,15342,2024-01-15,track,main.py
backup_20240101,src/config.py,8921,2024-01-10,track,config.py

🗑️ Удаление файлов из бэкапов

Команда: delete
bash

# Сухой запуск (покажет что будет удалено без изменений)
python backup_manager.py /backups delete backup_20240101 --mask "*.tmp" --dry-run

# Реальное удаление временных файлов
python backup_manager.py /backups delete backup_20240101 --mask "*.tmp"

# Удаление лог-файлов из нескольких бэкапов
python backup_manager.py /backups delete backup_20240101 --mask "*.log"
python backup_manager.py /backups delete backup_20240102 --mask "*.log"

# Удаление по нескольким маскам
python backup_manager.py /backups delete backup_20240101 --mask "*.tmp" --mask "*.log" --mask "cache.*"

⚠️ Важно: Всегда используйте --dry-run сначала для проверки!
✅ Валидация целостности бэкапов

Команда: validate
bash

# Проверка конкретного бэкапа
python backup_manager.py /backups validate backup_20240101

# Проверка всех бэкапов (скриптом)
for backup in $(python backup_manager.py /backups list | grep "backup_" | cut -d: -f1); do
    echo "Checking $backup..."
    python backup_manager.py /backups validate $backup
    echo ""
done

Пример вывода:
text

✅ Backup backup_20240101 is valid
   Checked 155/155 files

Или при проблемах:
text

❌ Backup backup_20240101 has issues:
   Missing files: 3
   Size mismatches: 1
   Timestamp mismatches: 2

Missing files (first 5):
   - src/deleted_file.py
   - config/missing_config.json

🎯 Комплексные примеры использования
🔍 Поиск больших медиафайлов за последнюю неделю
bash

python backup_manager.py /backups search \
    --mask "*.mp4" --mask "*.mov" --mask "*.avi" \
    --size ">500M" \
    --time ">2024-01-10" \
    --last-backups 7 \
    --json --export large_media_files.json

🧹 Очистка временных файлов из старых бэкапов
bash

# Сначала проверяем что будет удалено
python backup_manager.py /backups delete backup_20231201 --mask "*.tmp" --dry-run
python backup_manager.py /backups delete backup_20231215 --mask "*.tmp" --dry-run

# Затем удаляем
python backup_manager.py /backups delete backup_20231201 --mask "*.tmp"
python backup_manager.py /backups delete backup_20231215 --mask "*.tmp"

📊 Анализ изменений конфигурационных файлов
bash

python backup_manager.py /backups search \
    --mask "*.conf" --mask "*.config" --mask "*.json" --mask "*.yaml" --mask "*.yml" \
    --path "config/" \
    --time "2024-01-01..2024-01-31" \
    --csv --export config_changes_january.csv

🔎 Поиск удаленных файлов
bash

# Сначала ищем все файлы
python backup_manager.py /backups search --mask "important_file.txt"

# Затем проверяем в каких бэкапах они были удалены
python backup_manager.py /backups search --mask "important_file.txt" --last-backups 10

⚙️ Полезные скрипты
🔄 Автоматическое восстановление метаданных
bash

#!/bin/bash
# restore_metadata.sh
BACKUP_DIR="/path/to/backups"

echo "Восстановление метаданных для всех бэкапов..."
python backup_manager.py "$BACKUP_DIR" recreate --force

echo "Проверка целостности..."
for backup in $(python backup_manager.py "$BACKUP_DIR" list | grep "backup_" | cut -d: -f1); do
    echo "Проверка $backup..."
    python backup_manager.py "$BACKUP_DIR" validate $backup
done

📋 Ежедневный отчет о бэкапах
bash

#!/bin/bash
# daily_report.sh
BACKUP_DIR="/path/to/backups"
REPORT_FILE="/tmp/backup_report_$(date +%Y%m%d).md"

echo "# Отчет по бэкапам от $(date +%Y-%m-%d)" > $REPORT_FILE
echo "" >> $REPORT_FILE

echo "## Список бэкапов" >> $REPORT_FILE
python backup_manager.py "$BACKUP_DIR" list --detailed >> $REPORT_FILE

echo "" >> $REPORT_FILE
echo "## Последние изменения" >> $REPORT_FILE
python backup_manager.py "$BACKUP_DIR" search \
    --time ">$(date -d '1 day ago' +%Y-%m-%d)" \
    --markdown >> $REPORT_FILE

echo "Отчет сохранен: $REPORT_FILE"

🚨 Советы и лучшие практики

    Всегда используйте --dry-run перед удалением файлов

    Регулярно проверяйте целостность бэкапов командой validate

    Экспортируйте результаты в файлы для дальнейшего анализа

    Используйте фильтры для точного поиска нужных файлов

    Восстанавливайте метаданные после ручного изменения файлов бэкапа

🆘 Получение справки
bash

# Основная справка
python backup_manager.py --help

# Справка по конкретной команде
python backup_manager.py search --help
python backup_manager.py delete --help
python backup_manager.py list --help
