#!/usr/bin/env python3
"""
Backup Manager - Efficient incremental backup system using set operations and hardlinks
With improved reliability and Unicode path handling
"""

import os
import shutil
import json
import time
import sys
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import fnmatch
from typing import Dict, Set, Tuple, List, Optional
from functools import lru_cache
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    #format='%(asctime)s - %(levelname)s - %(message)s',
    format='%(message)s',
    handlers=[
        logging.FileHandler("backup.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def get_relative_path(path: Path, base: Path) -> Path:
    """Get relative path from base directory, fallback to filename if outside base"""
    try:
        return path.relative_to(base)
    except ValueError:
        return Path(path.name) if path.parent == base else path

def parse_pattern(pattern: str) -> Tuple[str, bool]:
    """Parse file patterns: ':rec' suffix indicates recursive search"""
    return (pattern[:-4], True) if pattern.endswith(":rec") else (pattern, False)

def expand_directory_patterns(base_path: Path, patterns: list[str]) -> Set[Path]:
    """Expand directory patterns to absolute paths (NO :rec support for dirs)"""
    expanded = set()
    base_path = base_path.resolve()
    
    for pattern in patterns:
        try:
            matches = list(base_path.glob(pattern))
            for match in matches:
                if match.is_dir() and match.exists():
                    expanded.add(match.resolve())
        except Exception:
            continue
    
    return expanded

def expand_file_patterns(base_path: Path, patterns: list[str]) -> Set[Path]:
    """Expand file patterns with optional recursive search (:rec suffix)"""
    expanded = set()
    base_path = base_path.resolve()

    for pattern in patterns:
        pat, is_rec = parse_pattern(pattern)

        try:
            if '/' in pat:
                if '*' in pat.split('/')[0] or '?' in pat.split('/')[0]:
                    logger.warning(f"Skip: mask in path - {pattern}")
                    continue
                    
                dir_part, file_part = pat.rsplit('/', 1)
                dir_path = base_path / dir_part
                
                if dir_path.exists() and dir_path.is_dir():
                    if is_rec:
                        matches = dir_path.rglob(file_part)
                    else:
                        matches = dir_path.glob(file_part)
                else:
                    matches = []
            else:
                if is_rec:
                    matches = base_path.rglob(pat)
                else:
                    matches = base_path.glob(pat)

            for match in matches:
                if match.is_file() and match.exists():
                    expanded.add(match.resolve())
                    
        except Exception as e:
            logger.error(f"Error: {pattern}: {e}")

    return expanded

def is_file_excluded(file_path: Path, exclude_patterns: list[str], src_path: Path) -> bool:
    """Check if file matches any exclusion pattern"""
    try:
        rel_path = get_relative_path(file_path, src_path)
        for pattern in exclude_patterns:
            pat, is_rec = parse_pattern(pattern)
            if is_rec:
                if fnmatch.fnmatch(str(rel_path), pat):
                    return True
            else:
                if fnmatch.fnmatch(rel_path.name, pat):
                    return True
    except ValueError:
        pass
    return False

def is_dir_excluded(dir_path: Path, exclude_dirs: Set[Path]) -> bool:
    """Check if directory or any parent is excluded"""
    return any(exclude_dir in dir_path.parents or exclude_dir == dir_path for exclude_dir in exclude_dirs)

def scan_source_with_exclusion(src_path: Path, cfg: dict) -> Tuple[Set[Path], Set[Path]]:
    """Scan source directory applying all inclusion/exclusion rules"""
    src_path = src_path.resolve()
    
    include_dirs = expand_directory_patterns(src_path, cfg["include_dirs"])
    track_dirs = expand_directory_patterns(src_path, cfg["track_dirs"])
    exclude_dirs = expand_directory_patterns(src_path, cfg["exclude_dirs"])
    
    all_files = set()
    tracked_files = set()
    
    for dir_path in include_dirs | track_dirs:
        if is_dir_excluded(dir_path, exclude_dirs):
            continue
            
        try:
            for root, dirs, files in os.walk(dir_path):
                current_dir = Path(root)
                dirs[:] = [d for d in dirs if not is_dir_excluded(current_dir / d, exclude_dirs)]
                
                for file in files:
                    file_path = current_dir / file
                    if file_path.is_file():
                        all_files.add(file_path)
        except (PermissionError, OSError) as e:
            logger.warning(f"Can't scan directory {dir_path}: {e}")
            continue
    
    include_files = expand_file_patterns(src_path, cfg["include_files"])
    track_files = expand_file_patterns(src_path, cfg["track_files"])
    all_files |= include_files | track_files
    
    if cfg["exclude_files"]:
        all_files = {f for f in all_files if not is_file_excluded(f, cfg["exclude_files"], src_path)}
    
    track_dirs_rel = {str(get_relative_path(d, src_path)) for d in track_dirs}
    for file_path in all_files:
        try:
            rel_path = get_relative_path(file_path, src_path)
            rel_str = str(rel_path)
            
            if any(rel_str.startswith(d + os.sep) or rel_str == d for d in track_dirs_rel):
                tracked_files.add(file_path)
                continue
                
            for pattern in cfg["track_files"]:
                pat, is_rec = parse_pattern(pattern)
                if is_rec:
                    if fnmatch.fnmatch(rel_str, pat):
                        tracked_files.add(file_path)
                        break
                else:
                    if fnmatch.fnmatch(rel_path.name, pat):
                        tracked_files.add(file_path)
                        break
        except ValueError:
            continue
    
    return all_files, tracked_files

def get_file_metadata(file_path: Path) -> Tuple[int, float]:
    """Get file metadata (size and modification time) for change detection"""
    stat = file_path.stat()
    return (stat.st_size, stat.st_mtime)

def load_mirror_json(dst_path: Path) -> Dict[Path, Tuple[Tuple[int, float], bool]]:
    """Load mirror state from JSON file"""
    mirror_json = dst_path / "mirror.json"
    if not mirror_json.exists():
        return {}
    
    try:
        with open(mirror_json, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Error loading mirror.json: {e}")
        return {}
    
    mirror_files = {}
    for rel_path_str, file_data in data.get("files", {}).items():
        if isinstance(file_data, dict) and "meta" in file_data:
            mirror_files[Path(rel_path_str)] = (tuple(file_data["meta"]), file_data.get("tracked", False))
        else:
            mirror_files[Path(rel_path_str)] = (tuple(file_data), False)
    
    return mirror_files

def save_mirror_json_atomic(dst_path: Path, source_files: Set[Path], tracked_files: Set[Path], src_path: Path):
    """Atomic save of mirror state to JSON file"""
    files_data = {}
    for file_path in source_files:
        try:
            rel_path = get_relative_path(file_path, src_path)
            files_data[str(rel_path)] = {
                "meta": list(get_file_metadata(file_path)),
                "tracked": file_path in tracked_files
            }
        except ValueError:
            continue
    
    data = {"files": files_data}
    temp_file = dst_path / "mirror.json.tmp"
    try:
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        temp_file.replace(dst_path / "mirror.json")
        logger.info("Mirror state saved atomically")
    except Exception as e:
        logger.error(f"Error saving mirror state: {e}")
        if temp_file.exists():
            temp_file.unlink()

def save_expanded_config(dst_path: Path, cfg: dict, src_path: Path):
    """Save expanded configuration for debugging"""
    expanded_config = cfg.copy()
    
    expanded_config["include_dirs"] = [str(get_relative_path(d, src_path)) for d in expand_directory_patterns(src_path, cfg["include_dirs"])]
    expanded_config["track_dirs"] = [str(get_relative_path(d, src_path)) for d in expand_directory_patterns(src_path, cfg["track_dirs"])]
    expanded_config["exclude_dirs"] = [str(get_relative_path(d, src_path)) for d in expand_directory_patterns(src_path, cfg["exclude_dirs"])]
    
    expanded_config["include_files"] = cfg["include_files"]
    expanded_config["track_files"] = cfg["track_files"]
    expanded_config["exclude_files":] = cfg["exclude_files"]
    
    try:
        with open(dst_path / "config_expanded.json", 'w', encoding='utf-8') as f:
            json.dump(expanded_config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error saving expanded config: {e}")

def create_increment_metadata(increment_path: Path, files_info: list):
    """Create metadata file for increment backup"""
    metadata = {
        "version": "1.0",
        "backup_type": "incremental",
        "backup_timestamp": datetime.now().isoformat(),
        "backup_name": increment_path.name,
        "backup_path": str(increment_path),
        "file_catalog": {},
        "summary": {
            "new_or_changed_tracked": 0,
            "deleted_tracked": 0,
            "total_operations": len(files_info)
        },
        "statistics": {
            "total_files": len(files_info),
            "total_size": sum(info['size'] for info in files_info)
        }
    }

    for info in files_info:
        rel_path = info['path']
        metadata["file_catalog"][rel_path] = {
            "size": info['size'],
            "mtime": info['mtime'],
            "mtime_iso": datetime.fromtimestamp(info['mtime']).isoformat(),
            "category": info['category'],
            "backup_path": f"{info['category']}/{rel_path}"
        }
        
        if info['category'] == 'track':
            metadata["summary"]["new_or_changed_tracked"] += 1
        else:
            metadata["summary"]["deleted_tracked"] += 1

    metadata_file = increment_path / f"{increment_path.name}.json"
    try:
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        logger.info(f"Metadata created for {increment_path.name}")
    except Exception as e:
        logger.error(f"Error saving metadata: {e}")

def safe_copy(src: Path, dst: Path) -> bool:
    """Improved file copying using Path methods for directory creation"""
    try:
        if not src.exists():
            logger.error(f"Source file does not exist: {src}")
            return False
            
        # Create parent directories using Path method
        dst.parent.mkdir(parents=True, exist_ok=True)
        
        shutil.copy2(str(src), str(dst))
        return True
        
    except Exception as e:
        logger.error(f"Copy failed: {src} -> {dst}: {e}")
        return False

def safe_hardlink(src: Path, dst: Path) -> bool:
    """Create hardlink with improved directory creation using Path methods"""
    try:
        # Check if source file exists
        if not src.exists():
            logger.error(f"Source file does not exist: {src}")
            return False
            
        # Create parent directories using Path method (more reliable)
        dst.parent.mkdir(parents=True, exist_ok=True)
        
        # Remove destination file if it exists
        if dst.exists():
            dst.unlink()
            
        # Create hardlink
        os.link(str(src), str(dst))
        return True
        
    except (OSError, FileNotFoundError) as e:
        logger.warning(f"Hardlink failed for {src} -> {dst}: {e}")
        return safe_copy(src, dst)

def safe_remove(path: Path) -> bool:
    """Safely remove file"""
    try:
        if path.exists():
            path.unlink()
            return True
    except Exception as e:
        logger.error(f"Remove failed: {path}: {e}")
    return False

def remove_empty_parents(root_path: Path, removed_file: Path, preserved_dirs: Set[str]):
    """Recursively remove empty parent directories after file deletion, preserving specified dirs"""
    current_dir = removed_file.parent
    
    while current_dir != root_path:
        try:
            if any(preserved_dir in current_dir.parts for preserved_dir in preserved_dirs):
                break
                
            if not any(current_dir.iterdir()):
                current_dir.rmdir()
                logger.info(f"Removed empty directory: {current_dir}")
                current_dir = current_dir.parent
            else:
                break
        except (OSError, PermissionError) as e:
            logger.warning(f"Can't remove directory {current_dir}: {e}")
            break

def load_config(config_file: Path) -> dict:
    """Load and validate configuration file"""
    if not config_file.exists():
        default_config = {
            "src": "/path/to/source",
            "dist": "/path/to/backup",
            "include_dirs": ["Documents"],
            "track_dirs": ["Projects/*"],
            "exclude_dirs": ["Temp"],
            "include_files": ["*.txt"],
            "track_files": ["*.log"],
            "exclude_files": ["*.tmp"],
            "max_workers": 8,
            "preserved_dirs": [".git", "node_modules", "vendor", "__pycache__"],
            "log_level": "INFO",
            "atomic_operations": True
        }
        with open(config_file, 'w') as f:
            json.dump(default_config, f, indent=2)
        logger.info(f"Created default config: {config_file}")
        sys.exit(1)
    
    with open(config_file, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    
    defaults = {
        "max_workers": 8,
        "use_mirror_json": True,
        "preserved_dirs": [".git", "node_modules", "vendor", "__pycache__"],
        "log_level": "INFO",
        "atomic_operations": True
    }
    
    for key, value in defaults.items():
        if key not in cfg:
            cfg[key] = value
    
    log_level = getattr(logging, cfg["log_level"].upper(), logging.INFO)
    logging.getLogger().setLevel(log_level)
    
    return cfg

def backup(config_file: Path):
    """Main backup function with improved reliability"""
    start_time = time.time()
    
    try:
        cfg = load_config(config_file)
        src_path = Path(cfg["src"]).expanduser().resolve()
        dst_path = Path(cfg["dist"]).expanduser().resolve()
        
        if not src_path.exists():
            raise FileNotFoundError(f"Source path does not exist: {src_path}")
    except Exception as e:
        logger.error(f"Config error: {e}")
        sys.exit(1)
    
    mirror_path = dst_path / "mirror"
    mirror_path.mkdir(parents=True, exist_ok=True)
    
    logger.info("Scanning source directory with metadata...")
    source_files, tracked_files = scan_source_with_exclusion(src_path, cfg)
    
    logger.info("Scanning mirror directory with metadata...")
    old_mirror = load_mirror_json(dst_path)
    
    source_paths = set()
    for f in source_files:
        try:
            source_paths.add(get_relative_path(f, src_path))
        except ValueError:
            continue
    
    tracked_paths = set()
    for f in tracked_files:
        try:
            tracked_paths.add(get_relative_path(f, src_path))
        except ValueError:
            continue
    
    old_mirror_paths = set(old_mirror.keys())
    old_tracked_paths = {p for p, (meta, tracked) in old_mirror.items() if tracked}
    
    mirror_new = source_paths - old_mirror_paths
    mirror_changed = set()
    mirror_deleted = old_mirror_paths - source_paths
    
    for path in source_paths & old_mirror_paths:
        current_meta = get_file_metadata(src_path / path)
        if current_meta != old_mirror[path][0]:
            mirror_changed.add(path)
    
    increment_new = tracked_paths - old_mirror_paths
    increment_changed = set()
    increment_deleted = old_tracked_paths - source_paths
    
    for path in tracked_paths & old_tracked_paths:
        current_meta = get_file_metadata(src_path / path)
        if current_meta != old_mirror[path][0]:
            increment_changed.add(path)
    
    increment_created = False
    files_info = []
    
    if increment_new or increment_changed or increment_deleted:
        ts = time.strftime("%Y%m%d_%H%M%S")
        increment_path = dst_path / f"backup_{ts}"
        increment_path.mkdir(parents=True, exist_ok=True)
        
        for rel_path in increment_deleted:
            mirror_file = mirror_path / rel_path
            if mirror_file.exists():
                stat = mirror_file.stat()
                files_info.append({
                    'path': str(rel_path),
                    'size': stat.st_size,
                    'mtime': stat.st_mtime,
                    'category': 'deleted'
                })
                increment_file = increment_path / "deleted" / rel_path
                safe_hardlink(mirror_file, increment_file)
            else:
                logger.warning(f"File not found in mirror: {mirror_file}")
    
    mirror_update = mirror_new | mirror_changed
    
    for rel_path in mirror_update:
        src_file = src_path / rel_path
        dst_file = mirror_path / rel_path
        safe_copy(src_file, dst_file)
    
    if increment_new or increment_changed:
        for rel_path in increment_new | increment_changed:
            mirror_file = mirror_path / rel_path
            if mirror_file.exists():
                stat = mirror_file.stat()
                files_info.append({
                    'path': str(rel_path),
                    'size': stat.st_size,
                    'mtime': stat.st_mtime,
                    'category': 'track'
                })
                increment_file = increment_path / "track" / rel_path
                safe_hardlink(mirror_file, increment_file)
            else:
                logger.warning(f"File not found in mirror: {mirror_file}")
    
    if increment_new or increment_changed or increment_deleted:
        create_increment_metadata(increment_path, files_info)
        increment_created = True
    
    preserved_dirs = set(cfg.get("preserved_dirs", []))
    for rel_path in mirror_deleted:
        old_file = mirror_path / rel_path
        if safe_remove(old_file):
            remove_empty_parents(mirror_path, old_file, preserved_dirs)
    
    if cfg.get("atomic_operations", True):
        save_mirror_json_atomic(dst_path, source_files, tracked_files, src_path)
    else:
        try:
            save_mirror_json_atomic(dst_path, source_files, tracked_files, src_path)
        except Exception as e:
            logger.error(f"Failed to save mirror state: {e}")
    
    save_expanded_config(dst_path, cfg, src_path)
    
    total_time = time.time() - start_time
    logger.info(f"Source files: {len(source_files)}, Tracked files: {len(tracked_files)}")
    logger.info(f"Mirror files: {len(old_mirror)}, Updated: {len(mirror_update)}, Removed: {len(mirror_deleted)}")
    
    if increment_created:
        new_changed_count = len(increment_new) + len(increment_changed)
        deleted_count = len(increment_deleted)
        logger.info(f"Increment created: {new_changed_count} new/changed, {deleted_count} deleted")
    else:
        logger.info("No changes - increment not created")
    
    logger.info(f"Total time: {total_time:.2f}s")

if __name__ == "__main__":
    config_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("config.json")
    backup(config_file)
