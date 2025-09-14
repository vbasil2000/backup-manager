# Backup Tool Guide

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

### Delete files

```bash
python3 backup_tool.py /path/to/backups delete backup_20240101 --mask "*.tmp" --dry-run
python3 backup_tool.py /path/to/backups delete backup_20240101 --mask "*.tmp"
```

## Search Filters

* `--mask` - File patterns (\*.txt, *.py, file.*)
* `--size` - Size filters:

  * `>100M` (larger than 100MB)
  * `<1G` (smaller than 1GB)
  * `500K-2M` (between 500KB and 2MB)
* `--time` - Time filters:

  * `2024-01-01` (specific date)
  * `>2024-01-01` (after date)
  * `<2024-01-15` (before date)
  * `2024-01-01..2024-01-15` (date range)
* `--path` - Path prefix (src/, config/)
* `--last-backups` - Last N backups only

## Output Formats

* **Human-readable (default)**:

  * Grouped by directories
  * Color-coded status indicators
  * Formatted file sizes
  * Clean table layout
* **JSON format (`--json`)**:

  * Machine-readable output
  * Full file metadata
  * Suitable for scripting

## Sample Output

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

Search results:
   Backups: 1
   Files: 4
   Size: 2.5 KB
   Tracked: 3, Deleted: 1
```

## Common Use Cases

### Find recently changed config files

```bash
python3 backup_tool.py /backups search \
  --mask "*.json" --mask "*.yaml" --mask "*.conf" \
  --time ">2024-01-01" \
  --last-backups 7
```

### Clean up temporary files

```bash
# First check what will be deleted
python3 backup_tool.py /backups delete backup_20240101 \
  --mask "*.tmp" --mask "*.log" --mask "*.cache" \
  --dry-run

# Then actually delete
python3 backup_tool.py /backups delete backup_20240101 \
  --mask "*.tmp" --mask "*.log" --mask "*.cache"
```

### Export search results

```bash
python3 backup_tool.py /backups search \
  --mask "*.py" --size ">100K" \
  --json > large_python_files.json
```
