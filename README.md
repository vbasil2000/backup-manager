# 📦 Axiomatic Backup System + Backup Explorer

A complete backup solution combining efficient mirror/incremental backups with powerful search and analysis capabilities.

## ✨ Features

- **Efficient Storage:** Uses hardlinks to avoid duplicate file storage
- **Incremental Backups:** Only stores changed files in each backup
- **Powerful Search:** Find files by masks, size, date, and path patterns
- **Flexible Configuration:** JSON-based configuration with include/exclude patterns
- **Safe Operations:** Read-only by default with explicit restoration scripts
- **Colorful UI:** Easy-to-read terminal output with color coding
- **Metadata Management:** Automatic JSON metadata generation and recreation

## 🏗 Architecture

The system consists of two complementary components:

- **Axiomatic Backup System (backup.py)** - Creates efficient mirror and incremental backups
- **Backup Explorer (backup_tool.py)** - Provides search, analysis and management capabilities

## 📋 Configuration

Create a `config.json` file to define your backup strategy:

```json
{
  "src": "/path/to/source",
  "dst": "/path/to/backups",
  "max_workers": 8,
  "directory_priority": "include",
  "include_dirs": [".config", "Documents", "Projects"],
  "exclude_dirs": ["temp", "cache", "node_modules"],
  "include_files": [".*", "*.txt:rec", "*.pdf"],
  "exclude_files": ["*.tmp", "*.log", "*.swp"],
  "track_dirs": ["Important"],
  "track_files": ["*.important:rec"],
  "preserved_dirs": [".git"]
}
```

### Pattern Syntax

- `:rec` suffix enables recursive matching
- Standard wildcards: `*`, `?`, `[]`
- Directory patterns are always recursive
- File patterns can be recursive or top-level only

## 🚀 Usage

### Creating Backups
```bash
python backup.py --config config.json
```

### Listing Available Backups
```bash
python backup_tool.py /backup/storage list
python backup_tool.py /backup/storage list --detailed
```

### Searching Files
```bash
# Find large PDF files
python backup_tool.py /backup/storage search --mask "*.pdf" --size ">10M"

# Find files modified in date range
python backup_tool.py /backup/storage search --mask "*" --time "2024-01-01..2024-01-31"

# Search in specific path
python backup_tool.py /backup/storage search --mask "*.py" --path "src/"

# Limit to recent backups
python backup_tool.py /backup/storage search --mask "*.log" --last-backups 5

# JSON output for scripting
python backup_tool.py /backup/storage search --mask "*.json" --json
```

### Managing Backups
```bash
# Recreate metadata (if corrupted)
python backup_tool.py /backup/storage recreate
python backup_tool.py /backup/storage recreate --force

# Generate restore script
python backup_tool.py /backup/storage search --mask "*.txt" --generate-script restore_script.sh

# Execute restore script
bash restore_script.sh /path/to/restore/location
```

## 🎯 Practical Examples

### Find and Clean Temporary Files
```bash
# Find temporary files
python backup_tool.py /backup/storage search --mask "*.tmp" --mask "*.temp" --mask "*.cache"

# Generate cleanup script
python backup_tool.py /backup/storage search --mask "*.tmp" --generate-script cleanup.sh

# Review then execute cleanup
bash cleanup.sh /tmp/cleanup
```

### Monitor Project Changes
```bash
# Track source code changes over time
python backup_tool.py /backup/storage search --mask "*.py" --mask "*.js" --time ">2024-01-01" --last-backups 7
```

### Archive Large Files
```bash
# Find large media files
python backup_tool.py /backup/storage search --mask "*.mp4" --mask "*.mov" --size ">100M" --full-paths
```

## 🔧 Advanced Features

### Size Filters
- `>100M` - Larger than 100MB
- `<1G` - Smaller than 1GB
- `10K-100K` - Between 10KB and 100KB

### Time Filters
- `2024-01-15` - On specific date
- `>2024-01-01` - After date
- `<2024-01-31` - Before date
- `2024-01-01..2024-01-15` - Date range

### Path Filters
- `documents/` - Specific directory
- `projects/*/src` - Pattern matching

## 🛡 Safety Features

- Dry-run option for deletion operations
- Explicit confirmation for destructive operations
- Metadata validation before operations
- Atomic writes for all metadata changes
- Error recovery and detailed logging

## 📊 Output Examples

The tool provides color-coded, organized output:
```text
📦 backup_20240101_120000 (2024-01-01 12:00)

  📁 documents/
     file.txt         1.2 MB  2024-01-01  ✅
     report.pdf       2.5 MB  2024-01-01  ✅

  📁 projects/
     code.py          15 KB   2024-01-01  ✅
     data.json        45 KB   2024-01-01  ✅

Search results:
   Backups: 1
   Files: 4
   Size: 3.8 MB
   Tracked: 4, Deleted: 0
```

## 🔄 Workflow

1. Configure your backup strategy in `config.json`
2. Run regular backups with `backup.py`
3. Analyze backups with `backup_tool.py`
4. Find and restore files as needed
5. Clean up old or unnecessary backups

## 📝 Requirements

- Python 3.6+
- No external dependencies

## 📄 License

MIT License - feel free to use and modify as needed.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

**Axiomatic Backup System + Backup Explorer** - Because your data deserves predictable, reliable, and flexible protection.
