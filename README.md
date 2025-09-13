# Backup System Utility

**Python incremental backup system** with mirror-based storage and independent increments.

## Features

* Mirror + Incremental: mirror reflects source; increments store hard links.
* Self-contained increments: safe to delete, move, or copy.
* No external dependencies.
* Configurable include/exclude rules.
* Multiple backup profiles.
* Cross-platform: Linux, macOS, Windows.
* Properly handles deleted tracked files.

## Scripts

* **backup.py** – performs incremental backups.
* **backup\_tool.py** – browse, search, and manage backups.

## Quick Start

**Backup:**

```bash
python3 backup.py                     # default config.json
python3 backup.py --config my_config.json
```

**Explore Backups:**

```bash
python3 backup_tool.py recreate --force
python3 backup_tool.py /path/backup search --mask "*.py" --mask "*.pdf"
```

## Config Example

```json
{
  "src": "~/Documents",
  "dist": "~/Backups",
  "include_dirs": ["projects", "notes"],
  "track_dirs": ["projects"],
  "include_files": ["*.txt", "*.md"],
  "track_files": ["important.docx"],
  "exclude_dirs": ["tmp", "cache"],
  "exclude_files": ["*.log"],
  "max_workers": 8
}
```

## Best Practices

* Use separate profiles per drive/project.
* Store history in increments; mirror keeps latest state.
* Deleted tracked files remain accessible via increments.
