# Руководство по Backup Tool

## Описание

Утилита для работы с инкрементальными бэкапами. Предоставляет управление наборами бэкапов, восстановление метаданных, поиск файлов и удаление с расширенными фильтрами.

## Возможности

* `list` - Просмотр всех бэкапов с краткой или подробной информацией
* `recreate` - Восстановление JSON метаданных для всех или конкретного бэкапа
* `search` - Поиск файлов по маскам, размеру, времени, префиксу пути
* `delete` - Удаление файлов из бэкапа с возможностью dry-run

## Установка

```bash
git clone <your-repo-url>
cd backup_tool
python3 backup_tool.py /path/to/backups <command>
```

## Использование

### Просмотр бэкапов

```bash
python3 backup_tool.py /path/to/backups list
python3 backup_tool.py /path/to/backups list --detailed
```

### Восстановление метаданных

```bash
python3 backup_tool.py /path/to/backups recreate
python3 backup_tool.py /path/to/backups recreate --force
python3 backup_tool.py /path/to/backups recreate --backup backup_20240101
```

### Поиск файлов

```bash
python3 backup_tool.py /path/to/backups search --mask "*.txt"
python3 backup_tool.py /path/to/backups search --mask "*.py" --size ">100K" --time ">2024-01-01"
python3 backup_tool.py /path/to/backups search --mask "*.log" --last-backups 5
python3 backup_tool.py /path/to/backups search --mask "*.json" --json
```

### Удаление файлов

```bash
python3 backup_tool.py /path/to/backups delete backup_20240101 --mask "*.tmp" --dry-run
python3 backup_tool.py /path/to/backups delete backup_20240101 --mask "*.tmp"
```

## Фильтры поиска

* `--mask` - Маски файлов (\*.txt, *.py, file.*)
* `--size` - Фильтры по размеру:

  * `>100M` (больше 100MB)
  * `<1G` (меньше 1GB)
  * `500K-2M` (от 500KB до 2MB)
* `--time` - Фильтры по времени:

  * `2024-01-01` (конкретная дата)
  * `>2024-01-01` (после даты)
  * `<2024-01-15` (до даты)
  * `2024-01-01..2024-01-15` (диапазон дат)
* `--path` - Префикс пути (src/, config/)
* `--last-backups` - Только последние N бэкапов

## Форматы вывода

* **Читаемый для человека (по умолчанию)**:

  * Группировка по директориям
  * Цветовая подсветка статуса
  * Форматированные размеры файлов
  * Чистое оформление таблиц
* **JSON (`--json`)**:

  * Машиночитаемый вывод
  * Полные метаданные файлов
  * Подходит для скриптов

## Пример вывода

```
📦 backup_20240101 (2024-01-01 14:30)

  📁 src/
     Имя файла                   Размер      Дата    Статус
     --------------------------  ---------  ----------  ------
     main.py                      1.2 KB     2024-01-01  ✅
     utils.py                     0.8 KB     2024-01-01  ✅

  📁 config/
     settings.json                0.5 KB     2024-01-01  ✅
     old_config.json              ❌         2023-12-15  ❌

Результаты поиска:
   Бэкапов: 1
   Файлов: 4
   Размер: 2.5 KB
   Tracked: 3, Deleted: 1
```

## Частые сценарии использования

### Найти недавно изменённые конфиги

```bash
python3 backup_tool.py /backups search \
  --mask "*.json" --mask "*.yaml" --mask "*.conf" \
  --time ">2024-01-01" \
  --last-backups 7
```

### Очистка временных файлов

```bash
# Сначала проверить, что будет удалено
python3 backup_tool.py /backups delete backup_20240101 \
  --mask "*.tmp" --mask "*.log" --mask "*.cache" \
  --dry-run

# Затем удалить реально
python3 backup_tool.py /backups delete backup_20240101 \
  --mask "*.tmp" --mask "*.log" --mask "*.cache"
```

### Экспорт результатов поиска

```bash
python3 backup_tool.py /backups search \
  --mask "*.py" --size ">100K" \
  --json > large_python_files.json
```
