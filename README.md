# Backup + Backup Tool: Minimalistic Yet Powerful Backup System

## 📋 Description

A complete backup system combining two complementary tools:

* **Backup** — creates efficient, incremental backups
* **Backup Tool** — provides full control, search, and analytics

This combination delivers **speed, simplicity, reliability, and flexibility** in one package.

---

## ⚡ Key Advantages

* **Lightning Fast**: search 100k+ files in seconds, parallel processing, minimal I/O
* **Space Efficient**: hardlinks instead of copies, incremental backups store only changes
* **Full Control**: filters by size, time, masks, paths; dry-run support for safe deletion
* **Reliable**: atomic metadata operations, complete error handling, corruption protection
* **Minimal Complexity**: \~500 lines of Python + \~10 lines of JSON config, zero dependencies

---

## 🛠 Backup

### How It Works

```
Source → Mirror → Incremental Backups
src — source files
mirror — live copy of all tracked files
backup_YYYYMMDD_HHMMSS — incremental copy of changes & deletions
```

* **Set-based Logic**: pure set operations determine new, changed, and deleted files
* **Incremental Backups**: only new/changed files + deleted files; hardlinks save space
* **Metadata**: JSON tracks size, mtime, path, operation type, and statistics

---

### 🔧 Configuration (Simple JSON)

#### Directories

```json
{
  "include_dirs": [".config", "Documents"],
  "track_dirs": [],
  "exclude_dirs": []
}
```

> Only specify `exclude_dirs` if you want to remove some branches. By default, all non-included directories are excluded.

#### Files

```json
{
  "include_files": [".*", "*.txt:rec"],
  "track_files": [],
  "exclude_files": []
}
```

* `:rec` → recursive search at any level
* No `:rec` → only root directory
* Directories are paths relative to `src`
* Files are glob patterns for precise control

---

### 🔍 Path Masks (Directory & File Patterns)

* **Directories** (`include_dirs`, `track_dirs`, `exclude_dirs`)

  * Supports **wildcards**: `*`, `?`, `[abc]`
  * **Recursive patterns** expanded automatically **before backup**
  * Examples:

    ```json
    "include_dirs": ["Documents/*", "Projects/pyt*"]
    "exclude_dirs": ["Documents/tmp", "Projects/*/build"]
    ```

* **Files** (`include_files`, `track_files`, `exclude_files`)

  * Supports **glob patterns** with optional `:rec` suffix

    * `*.py:rec` → recursively include all `.py` files
    * `README.md` → include only at root of specified directory
  * Patterns are evaluated **during scanning**, not in config
  * Examples:

    ```json
    "include_files": ["*.py:rec", "README.md"]
    "exclude_files": ["*.tmp:rec", "*.log:rec"]
    ```

> ✅ **Benefit**: Use concise masks in config; backup system resolves directories before scanning and file patterns at scan-time, keeping config clean.

---

### Backup Run Example

```bash
python3 backup.py --config config.json
```

After running:

* `mirror/` contains the current live copy
* `backup_YYYYMMDD_HHMMSS/` contains only changes and deletions

---

## 🔍 Backup Tool

### List Backups

```bash
python3 backup_tool.py /path/to/backups list
python3 backup_tool.py /path/to/backups list --detailed
```

### Recreate Metadata

```bash
python3 backup_tool.py /path/to/backups recreate
python3 backup_tool.py /path/to/backups recreate --force
python3 backup_tool.py /path/to/backups recreate --backup backup_20240101
```

### Search Files

```bash
python3 backup_tool.py /path/to/backups search --mask "*.py" --size ">100K" --time ">2024-01-01"
python3 backup_tool.py /path/to/backups search --mask "*.json" --json
```

### Delete Files

```bash
# Dry-run first
python3 backup_tool.py /path/to/backups delete backup_20240101 --mask "*.tmp" --dry-run

# Then delete
python3 backup_tool.py /path/to/backups delete backup_20240101 --mask "*.tmp"
```

---

## 📊 Common Use Cases

* **Analyze recent changes**

```bash
python3 backup_tool.py /backups search --mask "*.py" --mask "*.js" --time ">2024-01-15" --last-backups 7
```

* **Clean temporary files**

```bash
python3 backup_tool.py /backups delete backup_20231201 --mask "*.tmp" --mask "*.log"
```

* **Export project statistics**

```bash
python3 backup_tool.py /backups search --mask "src/*.py:rec" --json > project_stats.json
```

---

## 🛡 Reliability & Safety

* **Atomic Operations**: JSON writes replace temp files atomically
* **Hardlinks**: save disk space and time
* **Parallel Processing**: speeds up thousands of files
* **Safe Removal**: empty directories cleaned safely

---

## 🚀 Getting Started

1. Create `config.json` at project root.
2. Configure directories, files, and masks.
3. Run first backup:

```bash
python3 backup.py --config config.json
```

4. Explore backups and monitor:

```bash
python3 backup_tool.py /backup/storage list --detailed
```

---

## 🌟 Summary

Backup + Backup Tool = **Professional, fast, safe, predictable, and flexible backup system**.
Minimal Python code, minimal config, zero dependencies — perfect for developers, sysadmins, analysts, or anyone who values time and data integrity.
