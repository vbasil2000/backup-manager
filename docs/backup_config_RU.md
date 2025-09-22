# 📋 Полное руководство по конфигурации Axiomatic Backup System

## Быстрый старт

### Минимальная рабочая конфигурация
```json
{
  "src": "/home/username",
  "dst": "/mnt/backup",
  "include_dirs": ["Документы", "Изображения", ".config"]
}
```

### Запуск системы
```bash
# Создание бэкапа
python backup.py --config config.json

# Просмотр бэкапов
python backup_tool.py /mnt/backup list

# Поиск файлов
python backup_tool.py /mnt/backup search --mask "*.txt"
```

## Полный пример конфигурации
```json
{
  "src": "/home/user/data",
  "dst": "/mnt/backup/storage",
  "max_workers": 8,
  "directory_priority": "include",

  "include_dirs": [
    ".config",
    ".local/share",
    "Documents",
    "Projects/work",
    "Photos/2024"
  ],

  "track_dirs": [
    "Projects/active",
    "Downloads/important",
    "Documents/*/current"
  ],

  "exclude_dirs": [
    "temp",
    "cache",
    "node_modules",
    "Projects/old"
  ],

  "include_files": [
    ".*",
    ".bash*",
    "*.important",
    "Projects/backup_system/*.py:rec"
  ],

  "track_files": [
    "*.log:rec",
    "report_*.pdf",
    "Projects/*/data.json:rec"
  ],

  "exclude_files": [
    "*.tmp:rec",
    "*.swp:rec",
    "*.cache:rec"
  ],

  "preserved_dirs": [
    ".git",
    ".svn",
    "node_modules"
  ]
}
```

## Детальное описание параметров

### 🔧 Основные параметры
| Параметр          | Тип     | Обязательный | По умолчанию | Описание                                 |
|-------------------|---------|--------------|--------------|-----------------------------------------|
| src               | string  | ✅           | -            | Абсолютный путь к исходным данным       |
| dst               | string  | ✅           | -            | Путь для хранения бэкапов              |
| max_workers       | integer | ❌           | 8            | Количество потоков для обработки       |
| directory_priority| string  | ❌           | "include"    | Приоритет при конфликтах: include/track|

### 📁 Правила для директорий (рекурсивно)
| Правило       | Тип    | Описание                                        |
|---------------|--------|-------------------------------------------------|
| include_dirs  | array  | Директории, которые всегда включаются в бэкап   |
| track_dirs    | array  | Директории для отслеживания изменений           |
| exclude_dirs  | array  | Директории, исключаемые из обработки            |

### 📄 Правила для файлов
| Правило       | Тип    | Описание                                         |
|---------------|--------|--------------------------------------------------|
| include_files | array  | Файлы, которые всегда включаются                 |
| track_files   | array  | Файлы для отслеживания изменений                 |
| exclude_files | array  | Файлы, исключаемые из бэкапа                     |

### ⚙️ Служебные параметры
| Параметр       | Тип    | Описание                                              |
|----------------|--------|-------------------------------------------------------|
| preserved_dirs | array  | Директории, которые не удаляются даже если пустые     |

## Примеры для разных сценариев

### 🏠 Домашний пользователь
```json
{
  "src": "/home/user",
  "dst": "/mnt/backup",
  "include_dirs": ["Документы", "Изображения", "Видео", ".config", ".ssh"],
  "exclude_dirs": ["Загрузки", "Корзина", "tmp"]
}
```

### 💻 Разработчик
```json
{
  "src": "/home/dev",
  "dst": "/mnt/backup",
  "max_workers": 12,
  "directory_priority": "include",
  "include_dirs": [".config", ".ssh", "projects"],
  "track_dirs": ["projects/current", "projects/active"],
  "include_files": [".*", "*.env:rec", "config.json:rec"],
  "exclude_dirs": ["projects/old", "node_modules", "target", "dist"],
  "exclude_files": ["*.log:rec", "*.tmp:rec", "*.cache:rec"]
}
```

### 🖥️ Сервер
```json
{
  "src": "/",
  "dst": "/backup",
  "max_workers": 16,
  "include_dirs": ["/etc", "/home", "/var/log", "/usr/local/etc"],
  "track_dirs": ["/home/users", "/var/www", "/var/db"],
  "exclude_dirs": ["/tmp", "/proc", "/sys", "/dev", "/run"],
  "exclude_files": ["*.tmp:rec", "*.log:rec", "*.pid:rec"]
}
```

### 🎯 Только важные данные
```json
{
  "src": "/home/user",
  "dst": "/mnt/backup",
  "include_files": ["*.important:rec", "passwords.kdbx:rec", "*.kdb:rec", "recovery-codes.txt:rec"],
  "track_files": ["*.docx:rec", "*.xlsx:rec", "projects/*.pptx:rec"]
}
```

## Принципы работы системы

### 🎯 Основные принципы
- Исключение по умолчанию - включается только то, что явно указано
- Приоритет файлов над директориями
- Include > Track - включение имеет приоритет над отслеживанием
- Рекурсивность директорий - директории всегда обрабатываются рекурсивно

### 🔄 Порядок обработки правил
```python
# 1. Развертывание директорий
include_dirs = expand_directories(config.include_dirs)
track_dirs = expand_directories(config.track_dirs)

# 2. Сканирование файлов из директорий
files_from_include_dirs = scan(include_dirs)
files_from_track_dirs = scan(track_dirs)

# 3. Применение приоритета директорий
if directory_priority == "include":
    final_dirs_files = files_from_include_dirs | (files_from_track_dirs - files_from_include_dirs)
else:
    final_dirs_files = files_from_track_dirs | (files_from_include_dirs - files_from_track_dirs)

# 4. Применение файловых правил
include_files = expand_file_patterns(config.include_files)
track_files = expand_file_patterns(config.track_files) - include_files

# 5. Итоговые множества
all_files = final_dirs_files | include_files | track_files
tracked_files = (files_from_track_dirs - files_from_include_dirs) | track_files
```

### 📊 Матрица приоритетов
| Ситуация                               | Результат                             |
|----------------------------------------|---------------------------------------|
| Файл в include_dirs и track_dirs       | Зависит от directory_priority         |
| Файл в include_files и track_dirs      | include (приоритет файлов)            |
| Файл в exclude_dirs но в include_files | include (приоритет файлов)            |
| Файл соответствует exclude_files       | Исключается (кроме include_files)     |

## Лучшие практики

- Начинайте с минимальной конфигурации
```json
{"src": "/home/user", "dst": "/backup", "include_dirs": ["Документы"]}
```
- Добавляйте правила постепенно: сначала директории, затем исключения, потом файловые правила
- Используйте рекурсивные маски для файлов
```json
"include_files": ["*.important:rec"]
```
- Тестируйте конфигурацию
```bash
python backup.py --config config.json --dry-run
python backup_tool.py /backup search --mask "*"
```

### ❌ Частые ошибки
| Ошибка                         | Пример ❌                     | Исправление ✅                       |
|--------------------------------|-------------------------------|-------------------------------------|
| Относительные пути             | {"src": "Documents"}          | {"src": "/home/user/Documents"}  |
| Конфликтующие правила          | include_dirs: ["projects"]    | exclude_dirs: ["projects/important"] - ❌|
| Избыточные правила             | include_dirs: ["documents"]   | include_files: ["documents/*.txt"] - ❌|
| Неправильные маски             | include_files: ["*.txt"]      | include_files: ["*.txt:rec"] ✅    |

## Отладка и устранение ошибок

### 🔍 Инструменты диагностики
- Проверка синтаксиса JSON
```bash
python -m json.tool config.json
```
- Тестовый запуск
```bash
python backup.py --config config.json --dry-run
```
- Анализ покрытия
```bash
python backup_tool.py /backup search --mask "*" --json > coverage.json
python backup_tool.py /backup search --mask "*.tmp" --path "cache"
```
- Подробное логирование
```bash
python backup.py --config config.json --debug
```
- Решение частых проблем (большие файлы, пропущенные файлы, ошибки доступа)

### 📝 Чеклист настройки
- Проверен синтаксис JSON
- Все пути абсолютные
- Директории src и dst существуют
- Нет конфликтующих правил
- Протестирован dry-run
- Проверено покрытие файлов
- Настроены исключения для временных файлов

## Заключение
Axiomatic Backup System предоставляет гибкую и предсказуемую систему конфигурации, основанную на четких математических принципах. Начните с простой конфигурации и постепенно уточняйте правила.

Ключевые преимущества:
- ✅ Предсказуемость и детерминированность
- ✅ Гибкость настройки под любые нужды
- ✅ Эффективное использование ресурсов
- ✅ Простота отладки и диагностики

Для дополнительной помощи:
```bash
python backup.py --help
python backup_tool.py --help
```
