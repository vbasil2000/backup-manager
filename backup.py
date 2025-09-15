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
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("backup")

def load_config(config_file: Path):
    with open(config_file, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("max_workers", 8)
    cfg.setdefault("include_dirs", [])
    cfg.setdefault("track_dirs", [])
    cfg.setdefault("include_files", [])
    cfg.setdefault("track_files", [])
    cfg.setdefault("exclude_dirs", [])
    cfg.setdefault("exclude_files", [])
    cfg.setdefault("max_files_per_dir", 50)
    return cfg

def copy_file(src, dst):
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except Exception as e:
        log.error(f"Failed to copy {src} to {dst}: {e}")
        return False

def copy_files_sequential(files_to_copy):
    success_count = 0
    for src, dst in files_to_copy:
        if copy_file(src, dst):
            success_count += 1
    return success_count

def optimize_copy_operations(files_to_update, max_files_per_dir=50):
    dir_groups = defaultdict(list)
    for src, dst in files_to_update:
        dir_groups[dst.parent].append((src, dst))
    optimized_operations = []
    for target_dir, files in dir_groups.items():
        if len(files) > max_files_per_dir:
            optimized_operations.append(('sequential', files))
        else:
            optimized_operations.append(('parallel', files))
    return optimized_operations

def hardlink_file(src, dst):
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.link(src, dst)
        return True
    except (OSError, PermissionError):
        try:
            shutil.copy2(src, dst)
            return True
        except Exception as e:
            log.error(f"Failed to copy {src} to {dst}: {e}")
            return False
    except Exception as e:
        log.error(f"Failed to link {src} to {dst}: {e}")
        return False

def remove_empty_dirs(path):
    try:
        for root, dirs, _ in os.walk(path, topdown=False):
            for d in dirs:
                p = Path(root) / d
                try:
                    if not any(p.iterdir()):
                        p.rmdir()
                except (PermissionError, OSError):
                    continue
    except (PermissionError, OSError):
        pass

def matches_any(path_str, patterns):
    return any(fnmatch.fnmatch(path_str, pat) for pat in patterns)

def build_mirror_set(src_path, include_dirs, track_dirs, include_files, track_files, exclude_dirs, exclude_files):
    src_path = src_path.resolve()
    all_files = {}
    exclude_parts = {tuple(Path(d).parts) for d in exclude_dirs}

    for d in include_dirs + track_dirs:
        is_tracked = d in track_dirs
        path = src_path / d
        if not path.exists():
            continue
        try:
            for f in path.rglob("*"):
                if f.is_file():
                    try:
                        rel_path = f.relative_to(src_path)
                        rel_parts = rel_path.parts
                        excluded = any(rel_parts[:len(ex)] == ex for ex in exclude_parts)
                        if not excluded:
                            all_files[f] = is_tracked
                    except ValueError:
                        continue
        except (PermissionError, OSError):
            continue

    explicit_files = set()
    for pattern in include_files + track_files:
        is_tracked = pattern in track_files
        if pattern.endswith(':rec'):
            matches = src_path.rglob(pattern[:-4])
        elif '/' in pattern:
            dir_part, file_pattern = pattern.rsplit('/', 1)
            dir_path = src_path / dir_part
            matches = list(dir_path.glob(file_pattern)) if dir_path.exists() else []
        else:
            matches = list(src_path.glob(pattern))
        for matched_file in matches:
            if matched_file.is_file():
                try:
                    matched_file.relative_to(src_path)
                    all_files[matched_file] = is_tracked
                    explicit_files.add(matched_file)
                except ValueError:
                    continue

    files_to_remove = set()
    compiled_exclude_patterns = [fnmatch.translate(p) for p in exclude_files]
    for file_path in list(all_files.keys()):
        if file_path in explicit_files:
            continue
        rel_path_str = str(file_path.relative_to(src_path))
        if any(fnmatch.fnmatch(rel_path_str, p) for p in exclude_files):
            files_to_remove.add(file_path)
    for file_path in files_to_remove:
        all_files.pop(file_path, None)
    return all_files

def scan_mirror_files(mirror_path: Path):
    mirror_files = set()
    for f in mirror_path.rglob("*"):
        if f.is_file():
            try:
                mirror_files.add(f.relative_to(mirror_path))
            except ValueError:
                continue
    return mirror_files

def get_file_info(file_path: Path):
    try:
        stat = file_path.stat()
        return {"size": stat.st_size, "mtime": stat.st_mtime, "exists": True}
    except OSError:
        return {"exists": False}

def create_increment_metadata(increment_path, new_changed_files, deleted_files, src_path):
    metadata_path = increment_path / f"{increment_path.name}.json"
    metadata = {
        "backup_info": {"name": increment_path.name, "timestamp": time.strftime("%Y%m%d_%H%M%S")},
        "statistics": {"new_changed_files": len(new_changed_files), "deleted_files": len(deleted_files)},
        "files": {"new_changed_sample": [], "deleted": list(deleted_files)}
    }
    for f in list(new_changed_files)[:50]:
        try:
            rel_path = str(f.relative_to(src_path))
            info = get_file_info(f)
            if info["exists"]:
                metadata["files"]["new_changed_sample"].append({
                    "path": rel_path, "size": info["size"], "mtime": info["mtime"]
                })
        except (OSError, ValueError):
            continue
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    return metadata_path

def backup(config_file: Path):
    start_total = time.time()
    cfg = load_config(config_file)
    src_path = Path(cfg["src"]).expanduser().resolve()
    dst_path = Path(cfg["dist"]).expanduser().resolve()
    mirror_path = dst_path / "mirror"
    mirror_path.mkdir(parents=True, exist_ok=True)

    log.info("Scanning source directory...")
    mirror_set = build_mirror_set(
        src_path,
        cfg["include_dirs"], cfg["track_dirs"],
        cfg["include_files"], cfg["track_files"],
        cfg["exclude_dirs"], cfg["exclude_files"]
    )

    tracked_set = {f for f, t in mirror_set.items() if t}
    all_files_set = set(mirror_set.keys())
    tracked_rel_set = {f.relative_to(src_path) for f in tracked_set}

    log.info("Scanning mirror directory...")
    mirror_files_set = scan_mirror_files(mirror_path)

    log.info("Checking for file changes...")
    new_or_changed_tracked = set()
    deleted_tracked = set()
    mirror_stats = {p: (mirror_path / p).stat() for p in mirror_files_set if (mirror_path / p).exists()}

    for f in tracked_set:
        rel_path = f.relative_to(src_path)
        if rel_path not in mirror_stats or (f.stat().st_size != mirror_stats[rel_path].st_size or abs(f.stat().st_mtime - mirror_stats[rel_path].st_mtime) > 1):
            new_or_changed_tracked.add(f)

    for p in mirror_files_set:
        if p in tracked_rel_set and not (src_path / p).exists():
            deleted_tracked.add(p)

    increment_created = False
    metadata_path = None

    if new_or_changed_tracked or deleted_tracked:
        ts = time.strftime("%Y%m%d_%H%M%S")
        increment_path = dst_path / f"backup_{ts}"
        increment_path.mkdir(parents=True, exist_ok=True)

        # Deleted tracked
        for rel_path in deleted_tracked:
            src_file = mirror_path / rel_path
            dst_file = increment_path / "deleted" / rel_path
            hardlink_file(src_file, dst_file)

        # New/changed tracked
        for f in new_or_changed_tracked:
            rel_path = f.relative_to(src_path)
            mirror_file = mirror_path / rel_path
            copy_file(f, mirror_file)
            dst_file = increment_path / "track" / rel_path
            hardlink_file(mirror_file, dst_file)

        metadata_path = create_increment_metadata(increment_path, new_or_changed_tracked, deleted_tracked, src_path)
        increment_created = True

    log.info("Updating mirror directory...")
    files_to_update = []
    source_stats = {f: f.stat() for f in all_files_set if f.exists()}
    for f in all_files_set:
        rel_path = f.relative_to(src_path)
        mirror_file = mirror_path / rel_path
        if not mirror_file.exists() or (f.exists() and (f.stat().st_size != mirror_file.stat().st_size or abs(f.stat().st_mtime - mirror_file.stat().st_mtime) > 1)):
            files_to_update.append((f, mirror_file))

    if files_to_update:
        optimized_ops = optimize_copy_operations(files_to_update, cfg.get("max_files_per_dir", 50))
        for op_type, files in optimized_ops:
            if op_type == 'sequential':
                copy_files_sequential(files)
            else:
                with ThreadPoolExecutor(max_workers=cfg["max_workers"]) as exe:
                    futures = {exe.submit(copy_file, src, dst): (src, dst) for src, dst in files}
                    for future in as_completed(futures):
                        future.result()

    current_source_rel = {f.relative_to(src_path) for f in all_files_set}
    for mirror_rel in mirror_files_set:
        if mirror_rel not in current_source_rel:
            try:
                (mirror_path / mirror_rel).unlink()
            except OSError:
                continue
    remove_empty_dirs(mirror_path)

    # Final stats
    total_time = time.time() - start_total
    log.info(f"Source: {len(all_files_set)} | Tracked: {len(tracked_set)} | Mirror: {len(scan_mirror_files(mirror_path))} | Updated: {len(files_to_update)} | Removed: {len(mirror_files_set - current_source_rel)}")
    if increment_created:
        log.info(f"Increment created: {len(new_or_changed_tracked)} new/changed, {len(deleted_tracked)} deleted (folder: {increment_path.name})")
    else:
        log.info("No file changes - no increment created")
    log.info(f"Total time: {total_time:.2f}s")

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
