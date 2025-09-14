# Утилита для инкрементальных бэкапов

## Описание

Утилита для работы с инкрементальными бэкапами. Позволяет управлять резервными копиями, восстанавливать метаданные, искать и удалять файлы с гибкими фильтрами.

## Основные возможности

* `list` — список всех бэкапов с краткой или детальной информацией
* `recreate` — восстановление JSON-метаданных для всех или конкретного бэкапа
* `search` — поиск файлов с масками, фильтрами по размеру, времени и префиксу пути
* `delete` — удаление файлов из бэкапа с dry-run

## Установка

```bash
git clone <your-repo-url>
cd backup_manager
python3 backup_manager.py /path/to/backups <command>
```

## Использование

### Просмотр бэкапов

```bash
python3 backup_manager.py /path/to/backups list
python3 backup_manager.py /path/to/backups list --detailed
```

### Восстановление метаданных

```bash
python3 backup_manager.py /path/to/backups recreate
python3 backup_manager.py /path/to/backups recreate --force
python3 backup_manager.py /path/to/backups recreate --backup backup_20240101
```

### Поиск файлов

```bash
python3 backup_manager.py /path/to/backups search --mask "*.txt"
python3 backup_manager.py /path/to/backups search --mask "*.py" --size ">100K" --time ">2024-01-01"
python3 backup_manager.py /path/to/backups search --mask "*.log" --last-backups 5
python3 backup_manager.py /path/to/backups search --mask "*.json" --json
```

Фильтры: `--mask`, `--size`, `--time`, `--path`, `--last-backups`

### Удаление файлов

```bash
python3 backup_manager.py /path/to/backups delete backup_20240101 --mask "*.tmp" --dry-run
python3 backup_manager.py /path/to/backups delete backup_20240101 --mask "*.tmp"
```

### Визуальные особенности

* Группировка по директориям
* Цветовая подсветка (зелёный: tracked, красный: deleted)
* Статистика: файлы, размер, статус
* Читаемые даты и время

### Пример вывода

```
📦 backup_20240101 (2024-01-01 14:30)
  📁 src/
     File name                    Size       Date    Status
     --------------------------   ---------  ----------  ------
     main.py                      1.2 KB     2024-01-01  ✅
     utils.py                     0.8 KB     2024-01-01  ✅
  📁 config/
     settings.json                0.5 KB     2024-01-01  ✅
     old_config.json              ❌         2023-12-15  ❌
```
