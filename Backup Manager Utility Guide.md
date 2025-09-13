# Backup Manager Utility Guide

## 🚀 Overview

This utility provides full control over incremental backups:

- 🔍 Search files with filters by masks, size, and modification time
- 📊 View backup metadata
- 🛠️ Restore metadata
- 🗑️ Safely delete files from backups
- ✅ Validate backup integrity
- 📤 Export results in various formats

## 📋 Basic Commands

### 1. View Backups

**Command:** `list`

```bash
# Simple backup list
python backup_manager.py /path/to/backups list

# Detailed info with integrity check
python backup_manager.py /path/to/backups list --detailed
```

**Example output:**

```
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
```

### 2. Restore Metadata

**Command:** `recreate`

```bash
# Restore metadata for all backups
python backup_manager.py /path/to/backups recreate

# Force recreate metadata (overwrite existing)
python backup_manager.py /path/to/backups recreate --force

# Restore metadata for specific backup
python backup_manager.py /path/to/backups recreate --backup backup_20240101
```

### 3. Search Files in Backups

**Command:** `search`

#### 📁 By filename mask

```bash
# All Python files
python backup_manager.py /backups search --mask "*.py"

# Multiple masks
python backup_manager.py /backups search --mask "*.py" --mask "*.js" --mask "*.html"

# Files containing 'config'
python backup_manager.py /backups search --mask "*config*"
```

#### 📏 By size

```bash
# Files larger than 100MB
python backup_manager.py /backups search --mask "*.mp4" --size ">100M"

# Files smaller than 1KB
python backup_manager.py /backups search --mask "*.txt" --size "<1K"

# Files between 500KB and 2MB
python backup_manager.py /backups search --mask "*.jpg" --size "500K-2M"

# Exact size 1MB
python backup_manager.py /backups search --mask "*.log" --size "1M"
```

Supported suffixes: K (KB), M (MB), G (GB)

#### ⏰ By modification time

```bash
# Modified on Jan 15, 2024
python backup_manager.py /backups search --mask "*.py" --time "2024-01-15"

# Modified before Jan 10, 2024
python backup_manager.py /backups search --mask "*.log" --time "<2024-01-10"

# Modified after Jan 5, 2024
python backup_manager.py /backups search --mask "*.db" --time ">2024-01-05"

# Modified between Jan 1 and Jan 15, 2024
python backup_manager.py /backups search --mask "*" --time "2024-01-01..2024-01-15"
```

#### 📂 By path

```bash
# Files in src/ directory
python backup_manager.py /backups search --mask "*.py" --path "src/"

# Files in config/ subdirectories
python backup_manager.py /backups search --mask "*.json" --path "config/"
```

#### 🔎 Limit search by recent backups

```bash
# Only last 3 backups
python backup_manager.py /backups search --mask "*.tmp" --last-backups 3

# Only last 10 backups
python backup_manager.py /backups search --mask "*.log" --last-backups 10
```

#### 📤 Export search results

**Formats:** readable (default), JSON, CSV, Markdown

```bash
# JSON output
python backup_manager.py /backups search --mask "*.py" --json

# CSV output
python backup_manager.py /backups search --mask "*.py" --csv

# Markdown output
python backup_manager.py /backups search --mask "*.py" --markdown
```

**Export to file:**

```bash
# JSON
python backup_manager.py /backups search --mask "*.py" --json --export results.json

# CSV
python backup_manager.py /backups search --mask "*.py" --csv --export results.csv

# Markdown
python backup_manager.py /backups search --mask "*.py" --markdown --export report.md
```

**Example CSV output:**

```
Backup,Path,Size,Modified,Category,Filename
backup_20240101,src/main.py,15342,2024-01-15,track,main.py
backup_20240101,src/config.py,8921,2024-01-10,track,config.py
```

### 4. Delete Files from Backups

**Command:** `delete`

```bash
# Dry run (preview deletions)
python backup_manager.py /backups delete backup_20240101 --mask "*.tmp" --dry-run

# Actual deletion
python backup_manager.py /backups delete backup_20240101 --mask "*.tmp"

# Delete log files from multiple backups
python backup_manager.py /backups delete backup_20240101 --mask "*.log"
python backup_manager.py /backups delete backup_20240102 --mask "*.log"

# Delete multiple masks
python backup_manager.py /backups delete backup_20240101 --mask "*.tmp" --mask "*.log" --mask "cache.*"
```

⚠️ Always use `--dry-run` first!

### 5. Validate Backups

**Command:** `validate`

```bash
# Validate a specific backup
python backup_manager.py /backups validate backup_20240101

# Validate all backups
for backup in $(python backup_manager.py /backups list | grep "backup_" | cut -d: -f1); do
    python backup_manager.py /backups validate $backup
done
```

**Example output:**

```
✅ Backup backup_20240101 is valid
   Checked 155/155 files
```

Or with issues:

```
❌ Backup backup_20240101 has issues:
   Missing files: 3
   Size mismatches: 1
   Timestamp mismatches: 2
```

## 🎯 Example Workflows

### Search large media files from last week

```bash
python backup_manager.py /backups search \
    --mask "*.mp4" --mask "*.mov" --mask "*.avi" \
    --size ">500M" \
    --time ">2024-01-10" \
    --last-backups 7 \
    --json --export large_media_files.json
```

### Clean temporary files from old backups

```bash
# Dry run first
python backup_manager.py /backups delete backup_20231201 --mask "*.tmp" --dry-run
python backup_manager.py /backups delete backup_20231215 --mask "*.tmp" --dry-run

# Actual deletion
python backup_manager.py /backups delete backup_20231201 --mask "*.tmp"
python backup_manager.py /backups delete backup_20231215 --mask "*.tmp"
```

### Analyze configuration file changes

```bash
python backup_manager.py /backups search \
    --mask "*.conf" --mask "*.config" --mask "*.json" --mask "*.yaml" --mask "*.yml" \
    --path "config/" \
    --time "2024-01-01..2024-01-31" \
    --csv --export config_changes_january.csv
```

### Find deleted files

```bash
# Find all files
python backup_manager.py /backups search --mask "important_file.txt"

# Check in which backups they were deleted
python backup_manager.py /backups search --mask "important_file.txt" --last-backups 10
```

## ⚙️ Helpful Scripts

### Restore Metadata

```bash
#!/bin/bash
BACKUP_DIR="/path/to/backups"

python backup_manager.py "$BACKUP_DIR" recreate --force

for backup in $(python backup_manager.py "$BACKUP_DIR" list | grep "backup_" | cut -d: -f1); do
    python backup_manager.py "$BACKUP_DIR" validate $backup
done
```

### Daily Backup Report

```bash
#!/bin/bash
BACKUP_DIR="/path/to/backups"
REPORT_FILE="/tmp/backup_report_$(date +%Y%m%d).md"

echo "# Backup Report $(date +%Y-%m-%d)" > $REPORT_FILE
python backup_manager.py "$BACKUP_DIR" list --detailed >> $REPORT_FILE
python backup_manager.py "$BACKUP_DIR" search --time ">$(date -d '1 day ago' +%Y-%m-%d)" --markdown >> $REPORT_FILE
```

## 🚨 Tips & Best Practices

- Always use `--dry-run` before deleting files
- Regularly validate backups with `validate`
- Export search results for further analysis
- Use filters to pinpoint specific files
- Recreate metadata after manual changes to backups

## 🆘 Help

### General Help
```bash
python backup_manager.py --help

Command-specific Help

python backup_manager.py search --help
python backup_manager.py delete --help
python backup_manager.py list --help



