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
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

def hardlink_file(src, dst):
    """Create hardlink or copy if cross-filesystem"""
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

def matches_any(path_str, patterns):
    """Check if path matches any pattern"""
    return any(fnmatch.fnmatch(path_str, pat) for pat in patterns)

def build_mirror_set(src_path, include_dirs, track_dirs, include_files, track_files, exclude_dirs, exclude_files):
    """
    Build mirror_set according to the algorithm:
    1. Scan include_dirs + track_dirs (raw sets)
    2. Apply exclude_dirs (but protect explicit files)
    3. Add explicit files from include_files + track_files
    4. Apply exclude_files (explicit files remain protected)
    """
    src_path = src_path.resolve()
    all_files = {}
    explicit_files = set()
    
    # --- Step 1: Scan directories (include_dirs + track_dirs) ---
    for d in include_dirs + track_dirs:
        is_tracked = d in track_dirs
        path = src_path / d
        if not path.exists():
            continue
            
        try:
            # Always scan recursively
            for f in path.rglob("*"):
                if f.is_file() and f.is_relative_to(src_path):
                    all_files[f] = is_tracked
        except (PermissionError, OSError) as e:
            log.warning(f"Permission denied scanning {path}: {e}")
    
    # --- Step 2: Apply exclude_dirs ---
    excluded_by_dirs = set()
    for file_path in all_files.keys():
        try:
            rel_path = file_path.relative_to(src_path)
            # Check if file is in any excluded directory
            for exclude_dir in exclude_dirs:
                exclude_parts = Path(exclude_dir).parts
                if rel_path.parts[:len(exclude_parts)] == exclude_parts:
                    excluded_by_dirs.add(file_path)
                    break
        except ValueError:
            excluded_by_dirs.add(file_path)
    
    # Remove files excluded by directories
    for file_path in excluded_by_dirs:
        if file_path in all_files:
            del all_files[file_path]
    
    # --- Step 3: Add explicit files (include_files + track_files) ---
    for pattern in include_files + track_files:
        is_tracked = pattern in track_files
        
        try:
            # Handle both exact paths and glob patterns
            if any(char in pattern for char in ['*', '?', '[']):
                matches = list(src_path.rglob(pattern))
            else:
                matches = [src_path / pattern]
                
            for matched_file in matches:
                if matched_file.is_file() and matched_file.is_relative_to(src_path):
                    all_files[matched_file] = is_tracked
                    explicit_files.add(matched_file)
        except (PermissionError, OSError) as e:
            log.warning(f"Permission denied processing pattern {pattern}: {e}")
    
    # --- Step 4: Apply exclude_files (non-explicit files only) ---
    files_to_remove = set()
    for file_path, is_tracked in all_files.items():
        if file_path in explicit_files:
            continue  # Explicit files are protected
            
        try:
            rel_path = file_path.relative_to(src_path)
            if matches_any(str(rel_path), exclude_files) or matches_any(rel_path.name, exclude_files):
                files_to_remove.add(file_path)
        except ValueError:
            files_to_remove.add(file_path)
    
    for file_path in files_to_remove:
        del all_files[file_path]
    
    return all_files

def create_increment_metadata(increment_path, new_changed_files, deleted_files, src_path):
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
            "new_changed": [],
            "deleted": list(deleted_files)
        }
    }

    for f in new_changed_files:
        try:
            rel_path = str(f.relative_to(src_path))
            metadata["files"]["new_changed"].append({
                "path": rel_path,
                "size": f.stat().st_size,
                "mtime": f.stat().st_mtime,
                "backup_location": f"track/{rel_path}"
            })
        except (OSError, ValueError) as e:
            log.warning(f"Could not get info for file {f}: {e}")

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    return metadata_path

def backup(config_file: Path):
    """Main backup routine following the exact algorithm"""
    cfg = load_config(config_file)
    src_path = Path(cfg["src"]).expanduser().resolve()
    dst_path = Path(cfg["dist"]).expanduser().resolve()
    mirror_path = dst_path / "mirror"
    mirror_path.mkdir(parents=True, exist_ok=True)

    log.info("Building mirror set according to algorithm...")
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

    # --- Load previous mirror state ---
    mirror_json_path = mirror_path / "mirror.json"
    old_mirror = {}
    if mirror_json_path.exists():
        with open(mirror_json_path, "r", encoding="utf-8") as f:
            old_mirror = json.load(f)

    # --- Classify tracked files ---
    new_or_changed_tracked = set()
    deleted_tracked = set()
    current_tracked_rel = {str(f.relative_to(src_path)) for f in tracked_set}

    # Check for new/changed tracked files
    for f in tracked_set:
        rel = str(f.relative_to(src_path))
        old_info = old_mirror.get(rel)
        if (not old_info or
            old_info["size"] != f.stat().st_size or
            abs(old_info["mtime"] - f.stat().st_mtime) > 1):
            new_or_changed_tracked.add(f)

    # Check for deleted tracked files
    for rel, info in old_mirror.items():
        if info.get("tracked", False) and rel not in current_tracked_rel:
            deleted_tracked.add(rel)

    increment_created = False
    metadata_path = None

    # --- Check if we need to create increment ---
    has_files_for_increment = False
    
    # Check deleted files exist in mirror
    for rel in deleted_tracked:
        mirror_file = mirror_path / rel
        if mirror_file.exists():
            has_files_for_increment = True
            break
    
    # Check new/changed files exist in source
    if not has_files_for_increment:
        for f in new_or_changed_tracked:
            if f.exists():
                has_files_for_increment = True
                break

    # --- Create increment if needed ---
    if has_files_for_increment:
        ts = time.strftime("%Y%m%d_%H%M%S")
        increment_path = dst_path / f"backup_{ts}"
        log.info(f"Creating increment: {increment_path.name}")
        increment_path.mkdir(parents=True, exist_ok=True)

        files_added_to_increment = False

        # --- 1. Process DELETED tracked files FIRST ---
        deleted_count = 0
        for rel in deleted_tracked:
            src_mirror_file = mirror_path / rel
            if src_mirror_file.exists():
                increment_deleted = increment_path / "deleted"
                increment_deleted.mkdir(parents=True, exist_ok=True)
                dst_file = increment_deleted / rel
                hardlink_file(src_mirror_file, dst_file)
                deleted_count += 1
                files_added_to_increment = True

        # --- 2. Process NEW/CHANGED tracked files ---
        track_count = 0
        for f in new_or_changed_tracked:
            if f.exists():
                rel = str(f.relative_to(src_path))
                increment_track = increment_path / "track"
                increment_track.mkdir(parents=True, exist_ok=True)
                dst_file = increment_track / rel
                src_mirror_file = mirror_path / rel
                
                # Update mirror first
                hardlink_file(f, src_mirror_file)
                # Then create increment
                hardlink_file(src_mirror_file, dst_file)
                
                track_count += 1
                files_added_to_increment = True

        if files_added_to_increment:
            metadata_path = create_increment_metadata(
                increment_path, new_or_changed_tracked, deleted_tracked, src_path
            )
            increment_created = True
            log.info(f"  Added {deleted_count} deleted and {track_count} new/changed files to increment")
        else:
            # No files were actually added - remove empty increment
            shutil.rmtree(increment_path)
            log.info("No files to backup - increment removed")

    # --- 3. Update mirror with ALL files ---
    log.info("Updating mirror directory...")
    with ThreadPoolExecutor(max_workers=cfg["max_workers"]) as exe:
        futures = {}
        for f, tracked in mirror_set.items():
            try:
                rel = str(f.relative_to(src_path))
                dst_file = mirror_path / rel
                need_copy = (not dst_file.exists() or
                             dst_file.stat().st_size != f.stat().st_size or
                             abs(dst_file.stat().st_mtime - f.stat().st_mtime) > 1)
                if need_copy:
                    futures[exe.submit(copy_file, f, dst_file)] = f
            except (OSError, ValueError) as e:
                log.warning(f"Skipping file {f}: {e}")

        for i, future in enumerate(as_completed(futures), 1):
            try:
                future.result()
            except Exception as e:
                log.error(f"Failed to copy file: {e}")

    # --- 4. Clean up mirror: remove files not in current mirror_set ---
    current_mirror_rel = {str(f.relative_to(src_path)) for f in mirror_set}
    files_removed = 0
    
    for mirror_file in mirror_path.rglob("*"):
        if mirror_file.is_file() and mirror_file != mirror_json_path:
            try:
                rel = str(mirror_file.relative_to(mirror_path))
                if rel not in current_mirror_rel:
                    mirror_file.unlink()
                    files_removed += 1
            except (ValueError, OSError) as e:
                log.warning(f"Could not remove {mirror_file}: {e}")
                continue
    
    remove_empty_dirs(mirror_path)

    # --- 5. Save new mirror state ---
    mirror_data = {}
    for f, tracked in mirror_set.items():
        try:
            rel = str(f.relative_to(src_path))
            mirror_data[rel] = {
                "size": f.stat().st_size,
                "mtime": f.stat().st_mtime,
                "tracked": tracked
            }
        except (OSError, ValueError) as e:
            log.warning(f"Skipping file in mirror.json: {f} - {e}")

    # Atomic write to avoid corruption
    temp_mirror_json = mirror_json_path.with_suffix('.tmp')
    with open(temp_mirror_json, "w", encoding="utf-8") as f:
        json.dump(mirror_data, f, indent=2, ensure_ascii=False)
    temp_mirror_json.replace(mirror_json_path)

    # --- Statistics ---
    log.info("-"*50)
    log.info(f"Total files in source: {len(mirror_set)}")
    log.info(f"Tracked files: {len(tracked_set)}")
    log.info(f"Files removed from mirror: {files_removed}")
    
    if increment_created:
        log.info(f"Increment created: {increment_path.name}")
        log.info(f"Tracked new/changed: {len(new_or_changed_tracked)}")
        log.info(f"Tracked deleted: {len(deleted_tracked)}")
        log.info(f"Metadata: {metadata_path.name}")
    else:
        log.info("No tracked file changes - no increment needed")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backup script with mirror + incremental")
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
