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
    """
    Load backup configuration from a JSON file.
    Sets default values if keys are missing.
    """
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
    """
    Copy a file from src to dst. Create parent directories if needed.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

def hardlink_file(src, dst):
    """
    Create a hard link from src to dst. If fails, fallback to copy.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except Exception:
        shutil.copy2(src, dst)

def remove_empty_dirs(path):
    """
    Recursively remove empty directories under path.
    """
    for root, dirs, _ in os.walk(path, topdown=False):
        for d in dirs:
            p = Path(root) / d
            try:
                if not any(p.iterdir()):
                    p.rmdir()
            except (PermissionError, OSError):
                continue

def matches_any(path_str, patterns):
    """
    Check if path_str matches any pattern in patterns list.
    """
    return any(fnmatch.fnmatch(path_str, pat) for pat in patterns)

def is_excluded_dir(file_path, src_path, exclude_dirs):
    """
    Check if file_path belongs to any excluded directory.
    """
    try:
        rel_path = file_path.relative_to(src_path)
        for exclude_pattern in exclude_dirs:
            exclude_parts = Path(exclude_pattern).parts
            if rel_path.parts[:len(exclude_parts)] == exclude_parts:
                return True
    except ValueError:
        return True
    return False

def scan_dirs_files(src_path, dirs, files_patterns, tracked_dirs, tracked_files, exclude_dirs, exclude_files):
    """
    Scan directories and files according to include/exclude and tracked rules.
    Returns a dict mapping Path -> tracked status (True/False).
    """
    result = {}
    src_path = src_path.resolve()

    # --- Scan directories ---
    for d in dirs:
        is_tracked_dir = d in tracked_dirs
        path = src_path / d
        if not path.exists():
            log.warning(f"Directory does not exist: {path}")
            continue
        try:
            for f in path.rglob("*"):
                if f.is_file():
                    try:
                        if is_excluded_dir(f, src_path, exclude_dirs):
                            continue
                        rel = f.relative_to(src_path)
                        if matches_any(str(rel), exclude_files):
                            continue
                        result[f] = is_tracked_dir
                    except ValueError:
                        continue
        except (PermissionError, OSError) as e:
            log.warning(f"Permission denied scanning {path}: {e}")

    # --- Explicit files ---
    for f_pattern in files_patterns:
        is_tracked_file = f_pattern in tracked_files
        try:
            if any(char in f_pattern for char in ['*', '?', '[']):
                for matched_file in src_path.rglob(f_pattern):
                    if matched_file.is_file():
                        try:
                            if (is_excluded_dir(matched_file, src_path, exclude_dirs) or
                                matches_any(str(matched_file.relative_to(src_path)), exclude_files)):
                                continue
                            result[matched_file] = is_tracked_file
                        except ValueError:
                            continue
            else:
                file_path = src_path / f_pattern
                if file_path.exists() and file_path.is_file():
                    try:
                        if (is_excluded_dir(file_path, src_path, exclude_dirs) or
                            matches_any(str(file_path.relative_to(src_path)), exclude_files)):
                            continue
                        result[file_path] = is_tracked_file
                    except ValueError:
                        continue
        except (PermissionError, OSError) as e:
            log.warning(f"Permission denied processing pattern {f_pattern}: {e}")

    return result

def create_increment_metadata(increment_path, new_changed_files, deleted_files, src_path):
    """
    Create JSON metadata for an incremental backup.
    Filename format: increment_name_timestamp.json
    """
    ts_json = time.strftime("%Y%m%d_%H%M%S")
    metadata_file_name = f"{increment_path.name}_{ts_json}.json"
    metadata_path = increment_path / metadata_file_name

    metadata = {
        "backup_info": {
            "name": increment_path.name,
            "timestamp": ts_json,
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
    """
    Main backup routine:
    - Scan source directories/files
    - Create increments for new/changed/deleted tracked files
    - Update mirror directory with new/changed files
    - Clean mirror of deleted files
    - Save mirror.json and metadata
    """
    cfg = load_config(config_file)
    src_path = Path(cfg["src"]).expanduser().resolve()
    dst_path = Path(cfg["dist"]).expanduser().resolve()
    mirror_path = dst_path / "mirror"
    mirror_path.mkdir(parents=True, exist_ok=True)

    log.info("Scanning source directories and files...")
    mirror_set = scan_dirs_files(
        src_path,
        dirs=cfg["include_dirs"] + cfg["track_dirs"],
        files_patterns=cfg["include_files"] + cfg["track_files"],
        tracked_dirs=set(cfg["track_dirs"]),
        tracked_files=set(cfg["track_files"]),
        exclude_dirs=cfg["exclude_dirs"],
        exclude_files=cfg["exclude_files"]
    )

    tracked_set = {f for f, t in mirror_set.items() if t}

    # --- Load previous mirror.json ---
    mirror_json_path = mirror_path / "mirror.json"
    old_mirror = {}
    if mirror_json_path.exists():
        with open(mirror_json_path, "r", encoding="utf-8") as f:
            old_mirror = json.load(f)

    new_or_changed_tracked = set()
    deleted_tracked = set()
    current_tracked_rel = {str(f.relative_to(src_path)) for f in tracked_set}

    for f in tracked_set:
        rel = str(f.relative_to(src_path))
        old_info = old_mirror.get(rel)
        if (not old_info or
            old_info["size"] != f.stat().st_size or
            abs(old_info["mtime"] - f.stat().st_mtime) > 1):
            new_or_changed_tracked.add(f)

    for rel, info in old_mirror.items():
        if info.get("tracked", False) and rel not in current_tracked_rel:
            deleted_tracked.add(rel)

    increment_created = False
    metadata_path = None

    if new_or_changed_tracked or deleted_tracked:
        ts = time.strftime("%Y%m%d_%H%M%S")
        increment_path = dst_path / f"backup_{ts}"
        log.info(f"Creating increment: {increment_path}")
        increment_path.mkdir(parents=True, exist_ok=True)

        # --- Deleted tracked files ---
        if deleted_tracked:
            increment_deleted = increment_path / "deleted"
            increment_deleted.mkdir(parents=True, exist_ok=True)
            for rel in deleted_tracked:
                src_mirror_file = mirror_path / rel
                if src_mirror_file.exists():
                    dst_file = increment_deleted / rel
                    hardlink_file(src_mirror_file, dst_file)
                    # Remove tracked file from mirror
                    src_mirror_file.unlink()

        # --- New or changed tracked files ---
        if new_or_changed_tracked:
            increment_track = increment_path / "track"
            increment_track.mkdir(parents=True, exist_ok=True)
            for f in new_or_changed_tracked:
                rel = str(f.relative_to(src_path))
                dst_file = increment_track / rel
                src_mirror_file = mirror_path / rel
                hardlink_file(f, src_mirror_file)
                hardlink_file(src_mirror_file, dst_file)

        metadata_path = create_increment_metadata(
            increment_path, new_or_changed_tracked, deleted_tracked, src_path
        )
        increment_created = True

    # --- Update mirror directory ---
    log.info("Updating mirror directory...")
    with ThreadPoolExecutor(max_workers=cfg["max_workers"]) as exe:
        futures = {}
        for f in mirror_set:
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
                if i % 100 == 0:
                    log.info(f"Copied {i}/{len(futures)} files")
            except Exception as e:
                log.error(f"Failed to copy file: {e}")

    remove_empty_dirs(mirror_path)

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

    with open(mirror_json_path, "w", encoding="utf-8") as f:
        json.dump(mirror_data, f, indent=2, ensure_ascii=False)

    log.info("="*50)
    log.info(f"Mirror files total: {len(mirror_set)}")
    log.info(f"Tracked files: {len(tracked_set)}")
    if increment_created:
        log.info(f"Increment created: {increment_path}")
        log.info(f"Tracked new/changed: {len(new_or_changed_tracked)}")
        log.info(f"Tracked deleted: {len(deleted_tracked)}")
        log.info(f"Metadata: {metadata_path}")
        if increment_path.exists():
            log.info("Increment structure:")
            for item in increment_path.iterdir():
                if item.is_dir():
                    file_count = len(list(item.rglob("*")))
                    log.info(f"  {item.name}/: {file_count} files")
                else:
                    log.info(f"  {item.name}")
    else:
        log.info("No increment needed")

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
