# Backup Tool Guide - English

## Description

Utility for working with incremental backups. Provides management of backup sets, metadata recreation, file search, and deletion with advanced filters.

## Features

* `list` - List all backups with summary or detailed info
* `recreate` - Recreate JSON metadata for all or specific backup
* `search` - Search files with masks, size/time filters, path prefix
* `delete` - Delete files from backup with dry-run support

## Installation

```bash
git clone <your-repo-url>
cd backup_tool
python3 backup_tool.py /path/to/backups <command>
```

## Usage

### List backups

```bash
python3 backup_tool.py /path/to/backups list
python3 backup_tool.py /path/to/backups list --detailed
```

### Recreate metadata

```bash
python3 backup_tool.py /path/to/backups recreate
python3 backup_tool.py /path/to/backups recreate --force
python3 backup_tool.py /path/to/backups recreate --backup backup_20240101
```

### Search files

```bash
python3 backup_tool.py /path/to/backups search --mask "*.txt"
python3 backup_tool.py /path/to/backups search --mask "*.py" --size ">100K" --time ">2024-01-01"
python3 backup_tool.py /path/to/backups search --mask "*.log" --last-backups 5
python3 backup_tool.py /path/to/backups search --mask "*.json" --json
```

Filters: `--mask`, `--size`, `--time`, `--path`, `--last-backups`

### Delete files

```bash
python3 backup_tool.py /path/to/backups delete backup_20240101 --mask "*.tmp" --dry-run
python3 backup_tool.py /path/to/backups delete backup_20240101 --mask "*.tmp"
```

### Visual Features

* Grouped by directories
* Color-coded status (green: tracked, red: deleted)
* Stats: files, size, status
* Human-readable timestamps

### Sample Output

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
