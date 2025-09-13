
# Backup System Utility

## Overview

This project contains two Python scripts for a flexible backup system:

1. **backup.py** – performs incremental backups using a mirror-based approach.
2. **backup_tool.py** – a utility to inspect, explore, and manage backups.

### Key Features

- **Mirror + Incremental Approach**: The mirror directory reflects the source; increments store hard links, avoiding duplication.
- **Independent Increments**: Each backup increment is self-contained; you can remove, copy, or move them without affecting others.
- **Standard Python Libraries**: No external dependencies required.
- **Dynamic Configurations**: Easily modify include/exclude lists, tracked directories, etc.
- **Multiple Profiles**: You can define multiple configuration files, e.g., one for USB drives, one for another disk.
- **Cross-Platform**: Works on Linux, macOS, Windows.
- **Efficient Handling**: Deleted tracked files are correctly managed in increments without cluttering the mirror.

---

## Scripts Description

### 1. `backup.py`

**Purpose**: Incremental backup script with mirror management.

**Workflow**:

1. **Scan Source**: Recursively scans `src` directories/files using include/exclude rules.
2. **Classification**: Separates tracked vs. non-tracked files.
3. **Comparison**: Compares with current mirror state.
4. **Increment Creation**: Creates hard links for new or changed tracked files.
5. **Mirror Update**: Copies new/changed files into the mirror.
6. **Cleanup**: Removes files from mirror that no longer exist in source.
7. **Metadata**: Generates JSON metadata for increments.

**Config File**: `config.json` by default, can be overridden via CLI parameter. Example:

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

**Notes**:

- `track_dirs` and `track_files` are mirrored in increments.
- Deleted tracked files create links in `deleted` folder inside increment.
- Mirror keeps only current files; increments maintain all history.
- Increment metadata is stored as `backup_YYYYMMDD_HHMMSS.json`.

---

### 2. `backup_tool.py`

**Purpose**: Utility to explore and inspect backups.

**Key Features**:

- Browse backup increments and mirror contents.
- Search files across increments.
- Check metadata for each increment.
- Safe viewing without modifying backup data.
- Supports multiple backup profiles via config files.

---

## Usage

**Backup**:

```bash
python3 backup.py                             # Uses default config.json
python3 backup.py --config my_config.json     # Uses alternate config
```

**Backup Tool**:

```bash
python3 backup_tool.py recreate --force
python3 backup_tool.py /path/backup search --mask "*.py" --mask "*.pdf" --mask "*.md"
```

---

## Best Practices

- Configure separate backup profiles for USB drives, external disks, or different projects.
- Use increments to store history; mirror only keeps the latest state.
- You can move increments between drives without breaking links.
- Deleted tracked files remain accessible via increments.

---

## License

MIT License. Free to use and modify.
