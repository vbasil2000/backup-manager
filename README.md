# Minimalistic Yet Powerful Backup System

This backup system is designed to be simple, reliable, and high-performance. With just \~350 lines of Python code and a tiny JSON config, you can handle complex backup scenarios.

## How it Works

1. **Source → Mirror → Incremental Backups**

   * `src` — your source files
   * `mirror` — live copy of all tracked files
   * `backup_xxx` — incremental copies of changes and deletions

2. **Set-based Mathematics**

   * Pure set operations to determine new, changed, and deleted files
   * No duplicates, no extra scans
   * Predictable and deterministic

3. **Incremental Backups**

   * Only new/changed files + deleted files
   * Hardlinks to mirror save space
   * JSON metadata tracks all operations

## Configuration (Simple JSON)

**Directories:**

```json
{
  "include_dirs": [".config", "Documents"],
  "track_dirs": [],
  "exclude_dirs": ["tmp", "Images"]
}
```

**Files:**

```json
{
  "include_files": [".*", "*.txt:rec"],
  "track_files": [],
  "exclude_files": ["*.tmp", "*.log:rec"]
}
```

**Features:**

* `:rec` → recursive search at any level
* Patterns without `:rec` → only root directory
* Directories are paths relative to `src`
* Files are patterns — easy to control granularity

## Implementation Highlights

### Performance

* Parallel file copying (ThreadPoolExecutor)
* Minimal I/O operations
* Lightning-fast set operations

### Reliability

* Atomic JSON writes → prevents corruption
* Handles all file read/write errors
* Safe removal of empty directories
* Edge cases fully accounted for

### Incrementals

* Files categorized as:

  * **new/changed** → hardlink to mirror + copy to increment
  * **deleted** → hardlink to mirror + record in increment
* Metadata includes: size, mtime, path, operation type, and statistics

## Pattern System

* **Recursive:** `*.txt:rec` → all levels
* **Non-recursive:** `.*` → only root directory
* **Exclusions:** `*.tmp`, `*.log:rec`
* **Advantage:** strict, predictable, no magic

## Set-based Logic

* `new_files` = `current_tracked - old_mirror`
* `deleted_files` = `old_mirror - current_tracked`
* `updated_files` = compare size & mtime
* Fully deterministic — predictable backups

## Atomic & Safe Operations

* Temporary `.tmp` files → atomic JSON replacement
* Hardlinks instead of copies → saves disk space & time
* Parallel processing → faster for thousands of files

## Statistics

After backup, you get:

* Total files in mirror
* Number of tracked files
* Files removed from mirror
* New/changed/deleted files in incremental backup

## Minimal Complexity

* 350 lines of Python → easy to read, modify, and maintain
* 10 lines of config → easy to customize include/exclude rules
* 0 dependencies → pure Python

## Key Advantages

1. No magic — fully explicit and predictable
2. Space-efficient — hardlinks + incremental backups
3. Full control over operations
4. Fast, safe, reliable
5. Suitable for personal or professional use

## Getting Started

1. Create a `config.json` in the root directory of your project.
2. Configure directories and file patterns.
3. Run:

```bash
python3 backup.py --config config.json
```

4. Check `mirror/` for current state and `backup_YYYYMMDD_HHMMSS/` for incremental backups.
5. Enjoy minimalistic, high-performance backups!

---

**Summary:**
350 lines of Python + 10 lines of config → professional backup system, fast, safe, predictable, and flexible.
