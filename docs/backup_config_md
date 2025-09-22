# 📋 Complete Configuration Guide for Axiomatic Backup System

## Quick Start

### Minimal Working Configuration
```json
{
  "src": "/home/username",
  "dst": "/mnt/backup",
  "include_dirs": ["Documents", "Pictures", ".config"]
}
```

Run the system:
```bash
# Create a backup
python backup.py --config config.json

# List backups
python backup_tool.py /mnt/backup list

# Search files
python backup_tool.py /mnt/backup search --mask "*.txt"
```

### Full Configuration Example
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

## Detailed Parameters

### 🔧 Core Parameters

| Parameter           | Type    | Required | Default   | Description                                                        |
|-------------------_-|---------|----------|-----------|--------------------------------------------|
| src                 | string  | ✅       | -         | Absolute path to source data               |
| dst                 | string  | ✅       | -         | Path for storing backups                   |
| max_workers         | integer | ❌       | 8         | Number of threads for processing           |
| directory_priority  | string  | ❌       | "include" | Conflict resolution: "include" or "track"  |

### 📁 Directory Rules (Always Recursive)

| Rule          | Type   | Description                                    |
|---------------|--------|------------------------------------------------|
| include_dirs  | array  | Directories always included in the backup      |
| track_dirs    | array  | Directories tracked for incremental changes    |
| exclude_dirs  | array  | Directories excluded from processing           |

### 📄 File Rules (Recursive Control)

| Rule           | Type   | Description                                  |
|----------------|--------|----------------------------------------------|
| include_files  | array  | Files always included in the backup          |
| track_files    | array  | Files tracked for incremental changes        |
| exclude_files  | array  | Files excluded from backup                   |

### ⚙️ Service Parameters

| Parameter       | Type  | Description                                         |
|-----------------|-------|-----------------------------------------------------|
| preserved_dirs  | array | Directories preserved even if empty                 |

## Examples for Different Scenarios

### 🏠 Home User
```json
{
  "src": "/home/user",
  "dst": "/mnt/backup",
  "include_dirs": [
    "Documents",
    "Pictures",
    "Videos",
    ".config",
    ".ssh"
  ],
  "exclude_dirs": [
    "Downloads",
    "Trash",
    "tmp"
  ]
}
```

### 💻 Developer
```json
{
  "src": "/home/dev",
  "dst": "/mnt/backup",
  "max_workers": 12,
  "directory_priority": "include",
  
  "include_dirs": [
    ".config",
    ".ssh",
    "projects"
  ],
  
  "track_dirs": [
    "projects/current",
    "projects/active"
  ],
  
  "include_files": [
    ".*",
    "*.env:rec",
    "config.json:rec"
  ],
  
  "exclude_dirs": [
    "projects/old",
    "node_modules",
    "target",
    "dist"
  ],
  
  "exclude_files": [
    "*.log:rec",
    "*.tmp:rec",
    "*.cache:rec"
  ]
}
```

### 🖥️ Server
```json
{
  "src": "/",
  "dst": "/backup",
  "max_workers": 16,
  
  "include_dirs": [
    "/etc",
    "/home",
    "/var/log",
    "/usr/local/etc"
  ],
  
  "track_dirs": [
    "/home/users",
    "/var/www",
    "/var/db"
  ],
  
  "exclude_dirs": [
    "/tmp",
    "/proc",
    "/sys",
    "/dev",
    "/run"
  ],
  
  "exclude_files": [
    "*.tmp:rec",
    "*.log:rec",
    "*.pid:rec"
  ]
}
```

### 🎯 Important Data Only
```json
{
  "src": "/home/user",
  "dst": "/mnt/backup",
  
  "include_files": [
    "*.important:rec",
    "passwords.kdbx:rec",
    "*.kdb:rec",
    "recovery-codes.txt:rec"
  ],
  
  "track_files": [
    "*.docx:rec",
    "*.xlsx:rec",
    "projects/*.pptx:rec"
  ]
}
```

## System Principles

### 🎯 Core Principles

- Default exclusion: only explicitly included items are backed up  
- File priority over directories: file rules have higher priority  
- Include > Track: include overrides track  
- Directories are always processed recursively

### 🔄 Rule Processing Order
```python
# 1. Expand directories
include_dirs = expand_directories(config.include_dirs)
track_dirs = expand_directories(config.track_dirs)

# 2. Scan files from directories
files_from_include_dirs = scan(include_dirs)
files_from_track_dirs = scan(track_dirs)

# 3. Apply directory priority
if directory_priority == "include":
    final_dirs_files = files_from_include_dirs | (files_from_track_dirs - files_from_include_dirs)
else:
    final_dirs_files = files_from_track_dirs | (files_from_include_dirs - files_from_track_dirs)

# 4. Apply file rules
include_files = expand_file_patterns(config.include_files)
track_files = expand_file_patterns(config.track_files) - include_files

# 5. Final sets
all_files = final_dirs_files | include_files | track_files
tracked_files = (files_from_track_dirs - files_from_include_dirs) | track_files
```

### 📊 Priority Matrix

| Situation                                 | Result                                      |
|-------------------------------------------|---------------------------------------------|
| File in include_dirs and track_dirs       | Depends on `directory_priority`             |
| File in include_files and track_dirs      | include (file priority)                     |
| File in exclude_dirs but in include_files | include (file priority)                     |
| File matches exclude_files                | Excluded (except include_files)             |

## Best Practices

- Start with a minimal configuration  
```json
{"src": "/home/user", "dst": "/backup", "include_dirs": ["Documents"]}
```
- Add rules gradually: directories → exclusions → file rules  
- Use recursive file patterns  
```json
"include_files": ["*.important:rec"]
```
- Test configuration:
```bash
python backup.py --config config.json --dry-run
python backup_tool.py /backup search --mask "*"
```

### ❌ Common Errors

| Error Type  -             | Example                                        | Fix                                           |
|---------------------------|------------------------------------------------|-----------------------------------------------|
| Relative paths            | {"src": "Documents"}                           | Use absolute: {"src": "/home/user/Documents"} |
| Conflicting rules         | {"include_dirs":["projects"], "exclude_dirs":["projects/important"]} | Remove conflicts       |
| Redundant rules           | {"include_dirs":["documents"], "include_files":["documents/*.txt"]} | Only use necessary rule |
| Incorrect patterns        | {"include_files":["*.txt"]}                    | Use :rec for recursive: "*.txt:rec"            |

## Debugging & Troubleshooting

### 🔍 Diagnostic Tools
```bash
python -m json.tool config.json
python backup.py --config config.json --dry-run
python backup_tool.py /backup search --mask "*" --json > coverage.json
```

### Detailed Logging
```bash
python backup.py --config config.json --debug
```

### Common Problems

- **Backup takes too much space**
```bash
python backup_tool.py /backup search --size ">100M" --full-paths
python backup_tool.py /backup search --mask "*.tmp" --mask "*.cache"
```

- **Some files not included**
```bash
python backup_tool.py /backup search --mask "problem_file"
python backup_tool.py /backup search --mask "*" --path "file_directory"
```

- **Backup errors**
```bash
python backup.py --config config.json --debug 2> error.log
ls -la /path/to/problem_file
```

### 📝 Configuration Checklist

- JSON syntax validated  
- All paths absolute  
- `src` and `dst` exist  
- No conflicting rules  
- Dry-run tested  
- File coverage checked  
- Temporary files excluded
