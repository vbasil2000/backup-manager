#!/usr/bin/env python3
import os
import shutil
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import logging
import fnmatch
import argparse

# --- Logging setup ---
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("backup")

def load_config(config_file: Path):
    """Load backup configuration from JSON with defaults"""
    with open(config_file, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("max_workers", 8)
    cfg.setdefault("include_dirs", [])
    cfg.setdefault("track_dirs", [])
    cfg.setdefault("include_files", [])
    cfg.setdefault("track_files", [])
    cfg.setdefault("exclude_dirs", [])
    cfg.setdefault("exclude_files", [])
    return cfg

def copy_file(src, dst):
    """Copy file with parent directory creation"""
    if not src.is_file():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

def hardlink_file(src, dst):
    """Create hardlink or copy if cross-filesystem"""
    if not src.is_file():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except (OSError, PermissionError):
        shutil.copy2(src, dst)

def remove_empty_dirs(path):
    """Recursively remove empty directories"""
    for root, dirs, _ in os.walk(path, topdown=False):
        for d in dirs:
            p = Path(root) / d
            try:
                if not any(p.iterdir()):
                    p.rmdir()
            except (PermissionError, OSError):
                continue

def _matches_pattern(file_path: Path, pattern: str, src_path: Path) -> bool:
    """Ultra-simple pattern matcher: only *.txt and *.txt:rec"""
    if not file_path.is_file():
        return False
        
    try:
        rel_path = file_path.relative_to(src_path)
        
        if pattern.endswith(':rec'):
            # Recursive: match any level - "*.txt:rec"
            return fnmatch.fnmatch(str(rel_path), pattern[:-4])
        else:
            # Non-recursive: only root - "*.txt"
            return (str(rel_path.parent) == '.' and 
                    fnmatch.fnmatch(rel_path.name, pattern))
    except ValueError:
        return False

def apply_patterns(files_set: set, patterns: list, src_path: Path) -> set:
    """Apply patterns to file set - pure filtering"""
    result = set()
    for file_path in files_set:
        for pattern in patterns:
            if _matches_pattern(file_path, pattern, src_path):
                result.add(file_path)
                break
    return result

def _in_excluded_dir(file_path: Path, exclude_dir: str, src_path: Path) -> bool:
    """Check if file is in excluded directory"""
    try:
        rel_path = file_path.relative_to(src_path)
        return str(rel_path).startswith(exclude_dir + '/')
    except ValueError:
        return False

def build_mirror_set(src_path: Path, include_dirs: list, track_dirs: list, 
                    include_files: list, track_files: list, exclude_dirs: list, exclude_files: list) -> dict:
    """
    Pure set mathematics:
    1. Scan all directories
    2. Add root files from patterns  
    3. Remove excluded directories
    4. Remove excluded files
    5. Mark tracked files
    """
    src_path = src_path.resolve()
    
    # 1. Scan all directories (include + track)
    all_files = set()
    for dir_path in include_dirs + track_dirs:
        full_dir = src_path / dir_path
        if full_dir.exists() and full_dir.is_dir():
            try:
                all_files.update(
                    f for f in full_dir.rglob('*') 
                    if f.is_file() and f.is_relative_to(src_path)
                )
            except (PermissionError, OSError):
                continue
    
    # 2. Add root files for non-recursive patterns
    root_files = set()
    for pattern in include_files + track_files:
        if not pattern.endswith(':rec'):
            try:
                for file_path in src_path.glob(pattern):
                    if file_path.is_file() and file_path.is_relative_to(src_path):
                        root_files.add(file_path)
            except (PermissionError, OSError):
                continue
    
    all_files.update(root_files)
    
    # 3. Remove excluded directories
    excluded_dirs_set = set()
    for file_path in all_files:
        for exclude_dir in exclude_dirs:
            if _in_excluded_dir(file_path, exclude_dir, src_path):
                excluded_dirs_set.add(file_path)
                break
    all_files -= excluded_dirs_set
    
    # 4. Remove excluded files
    excluded_files_set = apply_patterns(all_files, exclude_files, src_path)
    all_files -= excluded_files_set
    
    # 5. Mark tracked files
    tracked_patterns = []
    for dir_path in track_dirs:
        tracked_patterns.append(f"{dir_path}/*:rec")
    tracked_patterns.extend(track_files)
    
    tracked_set = apply_patterns(all_files, tracked_patterns, src_path)
    
    return {f: (f in tracked_set) for f in all_files}

def create_increment_metadata(increment_path: Path, new_changed_files: set, deleted_files: set, src_path: Path) -> Path:
    """Create JSON metadata for incremental backup"""
    metadata_path = increment_path / f"{increment_path.name}.json"

    metadata = {
        "backup_info": {
            "name": increment_path.name,
            "timestamp": time.strftime("%Y%m%d_%H%M%S"),
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "unix_timestamp": time.time(),
            "type": "incremental"
        },
        "statistics": {
            "new_changed_files": len(new_changed_files),
            "deleted_files": len(deleted_files),
            "total_operations": len(new_changed_files) + len(deleted_files)
        },
        "files": {
            "new_changed": [{
                "path": str(f.relative_to(src_path)),
                "size": f.stat().st_size,
                "mtime": f.stat().st_mtime,
                "backup_location": f"track/{f.relative_to(src_path)}"
            } for f in new_changed_files if f.is_file()],
            "deleted": list(deleted_files)
        }
    }

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    return metadata_path

def backup(config_file: Path):
    """Main backup routine with pure set operations"""
    cfg = load_config(config_file)
    src_path = Path(cfg["src"]).expanduser().resolve()
    dst_path = Path(cfg["dist"]).expanduser().resolve()
    mirror_path = dst_path / "mirror"
    mirror_path.mkdir(parents=True, exist_ok=True)

    log.info("Building mirror set using pure set mathematics...")
    mirror_set = build_mirror_set(
        src_path,
        cfg["include_dirs"],
        cfg["track_dirs"],
        cfg["include_files"],
        cfg["track_files"],
        cfg["exclude_dirs"],
        cfg["exclude_files"]
    )

    tracked_set = {f for f, t in mirror_set.items() if t}

    # Load previous mirror state
    mirror_json_path = mirror_path / "mirror.json"
    old_mirror = {}
    if mirror_json_path.exists():
        with open(mirror_json_path, "r", encoding="utf-8") as f:
            old_mirror = json.load(f)

    # Classify tracked files
    current_tracked_rel = {str(f.relative_to(src_path)) for f in tracked_set if f.is_file()}
    
    new_or_changed_tracked = {
        f for f in tracked_set 
        if f.is_file() and (
            str(f.relative_to(src_path)) not in old_mirror or
            old_mirror[str(f.relative_to(src_path))]["size"] != f.stat().st_size or
            abs(old_mirror[str(f.relative_to(src_path))]["mtime"] - f.stat().st_mtime) > 1
        )
    }

    deleted_tracked = {
        rel for rel, info in old_mirror.items() 
        if info.get("tracked", False) and rel not in current_tracked_rel
    }

    # Create increment if needed
    has_files_for_increment = (
        any((mirror_path / rel).exists() and (mirror_path / rel).is_file() for rel in deleted_tracked) or
        any(f.exists() and f.is_file() for f in new_or_changed_tracked)
    )

    if has_files_for_increment:
        ts = time.strftime("%Y%m%d_%H%M%S")
        increment_path = dst_path / f"backup_{ts}"
        log.info(f"Creating increment: {increment_path}")
        increment_path.mkdir(parents=True, exist_ok=True)

        # Process deleted files
        deleted_count = 0
        for rel in deleted_tracked:
            src_mirror_file = mirror_path / rel
            if src_mirror_file.exists() and src_mirror_file.is_file():
                dst_file = increment_path / "deleted" / rel
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                hardlink_file(src_mirror_file, dst_file)
                deleted_count += 1

        # Process new/changed files
        track_count = 0
        for f in new_or_changed_tracked:
            if f.exists() and f.is_file():
                rel = str(f.relative_to(src_path))
                src_mirror_file = mirror_path / rel
                dst_file = increment_path / "track" / rel
                
                hardlink_file(f, src_mirror_file)
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                hardlink_file(src_mirror_file, dst_file)
                track_count += 1

        if deleted_count or track_count:
            metadata_path = create_increment_metadata(increment_path, new_or_changed_tracked, deleted_tracked, src_path)
            log.info(f"Added {deleted_count} deleted and {track_count} new/changed files")
        else:
            shutil.rmtree(increment_path)
            log.info("No files to backup - increment removed")

    # Update mirror
    log.info("Updating mirror directory...")
    with ThreadPoolExecutor(max_workers=cfg["max_workers"]) as exe:
        futures = {}
        for f in mirror_set.keys():
            if not f.is_file():
                continue
            try:
                rel = str(f.relative_to(src_path))
                dst_file = mirror_path / rel
                if not dst_file.exists() or not dst_file.is_file() or dst_file.stat().st_size != f.stat().st_size:
                    futures[exe.submit(copy_file, f, dst_file)] = f
            except (OSError, ValueError):
                continue

        for i, future in enumerate(as_completed(futures), 1):
            try:
                future.result()
                if i % 100 == 0:
                    log.info(f"Copied {i}/{len(futures)} files to mirror")
            except Exception as e:
                log.error(f"Failed to copy file: {e}")

    # Clean up mirror
    current_mirror_rel = {str(f.relative_to(src_path)) for f in mirror_set.keys() if f.is_file()}
    files_removed = 0
    
    for mirror_file in mirror_path.rglob("*"):
        if mirror_file.is_file() and mirror_file != mirror_json_path:
            try:
                rel = str(mirror_file.relative_to(mirror_path))
                if rel not in current_mirror_rel:
                    mirror_file.unlink()
                    files_removed += 1
            except (OSError, ValueError):
                continue
    
    remove_empty_dirs(mirror_path)

    # Save new mirror state
    mirror_data = {}
    for f, tracked in mirror_set.items():
        if not f.is_file():
            continue
        try:
            rel = str(f.relative_to(src_path))
            mirror_data[rel] = {
                "size": f.stat().st_size,
                "mtime": f.stat().st_mtime,
                "tracked": tracked
            }
        except (OSError, ValueError):
            continue

    # Atomic write
    temp_mirror_json = mirror_json_path.with_suffix('.tmp')
    with open(temp_mirror_json, "w", encoding="utf-8") as f:
        json.dump(mirror_data, f, indent=2, ensure_ascii=False)
    temp_mirror_json.replace(mirror_json_path)

    # Statistics
    log.info("="*50)
    log.info(f"Total files: {len(mirror_set)}")
    log.info(f"Tracked files: {len(tracked_set)}")
    log.info(f"Files removed from mirror: {files_removed}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backup script with pure set mathematics")
    parser.add_argument("--config", type=str, default="config.json", help="Path to config file")
    args = parser.parse_args()
    config_file = Path(args.config).resolve()
    
    if not config_file.exists():
        log.error(f"Config file not found: {config_file}")
        exit(1)
        
    try:
        backup(config_file)
    except Exception as e:
        log.error(f"Backup failed: {e}")
        raise
        
