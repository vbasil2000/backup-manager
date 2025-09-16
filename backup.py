#!/usr/bin/env python3
import os
import shutil
import json
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import fnmatch
from collections import defaultdict

# --- Logging setup ---
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("backup")

# -------------------- CONFIG --------------------
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

# -------------------- FILE OPERATIONS --------------------
def copy_file(src: Path, dst: Path) -> bool:
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except Exception as e:
        log.warning(f"Failed to copy {src} to {dst}: {e}")
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

def hardlink_file(src: Path, dst: Path) -> bool:
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.link(src, dst)
        return True
    except (OSError, PermissionError):
        return copy_file(src, dst)

def remove_empty_dirs(path: Path):
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

# -------------------- PATTERN UTIL --------------------
def parse_rec_pattern(pattern: str):
    if pattern.endswith(':rec'):
        return pattern[:-4], True
    return pattern, False

def matches_exclude_for_file(rel_path: Path, pattern: str) -> bool:
    pstr = str(rel_path)
    pat, is_rec = parse_rec_pattern(pattern)
    if is_rec:
        return fnmatch.fnmatch(pstr, pat)
    if '/' in pattern:
        return fnmatch.fnmatch(pstr, pattern)
    else:
        if rel_path.parent == Path('.'):
            return fnmatch.fnmatch(rel_path.name, pattern)
        return False

# -------------------- MIRROR BUILD --------------------
def build_mirror_set_optimized(src_path: Path, include_dirs, track_dirs, include_files, track_files, exclude_dirs, exclude_files):
    src_path = src_path.resolve()
    all_files = {}  # Path -> is_tracked

    exclude_parts = [tuple(Path(d).parts) for d in exclude_dirs]

    def is_excluded(rel_parts):
        for ep in exclude_parts:
            if len(rel_parts) >= len(ep) and tuple(rel_parts[:len(ep)]) == ep:
                return True
        return False

    # 1) Scan include_dirs + track_dirs
    for d in include_dirs + track_dirs:
        is_tracked = d in track_dirs
        root = src_path / d
        if not root.exists():
            continue
        stack = [root]
        while stack:
            current = stack.pop()
            try:
                for entry in current.iterdir():
                    if entry.is_dir():
                        rel = entry.relative_to(src_path)
                        if is_excluded(rel.parts):
                            continue
                        stack.append(entry)
                    elif entry.is_file():
                        rel = entry.relative_to(src_path)
                        if is_excluded(rel.parts):
                            continue
                        try:
                            entry.stat()
                        except OSError:
                            continue
                        all_files[entry] = is_tracked
            except (PermissionError, OSError):
                continue

    # 2) Add explicit include/track files
    explicit_files = set()
    for pattern in include_files + track_files:
        is_tracked = pattern in track_files
        pat, is_rec = parse_rec_pattern(pattern)
        try:
            if is_rec:
                matches = list(src_path.rglob(pat))
            elif '/' in pattern:
                dir_part, file_pat = pattern.rsplit('/', 1)
                dir_path = src_path / dir_part
                matches = list(dir_path.glob(file_pat)) if dir_path.exists() else []
            else:
                matches = list(src_path.glob(pat))
        except (PermissionError, OSError):
            matches = []

        for m in matches:
            if not m.is_file():
                continue
            try:
                m.relative_to(src_path)
            except ValueError:
                continue
            all_files[m] = is_tracked
            explicit_files.add(m)

    # 3) Apply exclude_files only to non-explicit files
    for f in list(all_files.keys()):
        if f in explicit_files:
            continue
        rel = f.relative_to(src_path)
        for pat in exclude_files:
            if matches_exclude_for_file(rel, pat):
                del all_files[f]
                break

    return all_files

# -------------------- MIRROR SCAN --------------------
def scan_mirror_files(mirror_path: Path):
    log.info("Scanning mirror directory...")
    mirror_files = set()
    if not mirror_path.exists():
        return mirror_files
    stack = [mirror_path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_file(follow_symlinks=False):
                            rel = Path(entry.path).relative_to(mirror_path)
                            mirror_files.add(rel)
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError):
            continue
    return mirror_files

# -------------------- METADATA --------------------
def create_increment_metadata(increment_path: Path, new_changed_files, deleted_files, src_path: Path):
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
            "deleted_files": len(deleted_files)
        },
        "files": {
            "new_changed_sample": [],
            "deleted": list(deleted_files)
        }
    }
    for f in list(new_changed_files)[:50]:
        try:
            rel = str(f.relative_to(src_path))
            st = f.stat()
            metadata["files"]["new_changed_sample"].append({"path": rel, "size": st.st_size, "mtime": st.st_mtime})
        except (OSError, ValueError):
            continue
    with open(metadata_path, "w", encoding="utf-8") as mf:
        json.dump(metadata, mf, indent=2, ensure_ascii=False)
    return metadata_path

# -------------------- BACKUP --------------------
def backup(config_file: Path):
    total_start_time = time.time()
    cfg = load_config(config_file)
    src_path = Path(cfg["src"]).expanduser().resolve()
    dst_path = Path(cfg["dist"]).expanduser().resolve()
    mirror_path = dst_path / "mirror"
    mirror_path.mkdir(parents=True, exist_ok=True)

    # Build mirror set
    log.info("Scanning source directory...")
    mirror_set = build_mirror_set_optimized(
        src_path,
        cfg["include_dirs"],
        cfg["track_dirs"],
        cfg["include_files"],
        cfg["track_files"],
        cfg["exclude_dirs"],
        cfg["exclude_files"]
    )

    tracked_set = {f for f, tracked in mirror_set.items() if tracked}
    all_files_set = set(mirror_set.keys())
    tracked_rel_set = {f.relative_to(src_path) for f in tracked_set}

    # Scan mirror
    mirror_files_set = scan_mirror_files(mirror_path)

    # Check tracked files
    log.info("Checking for file changes...")
    new_or_changed_tracked = set()
    deleted_tracked = set()

    mirror_stats = {}
    for rel in mirror_files_set:
        mf = mirror_path / rel
        if mf.exists():
            try:
                mirror_stats[rel] = mf.stat()
            except OSError:
                continue

    for f in tracked_set:
        try:
            rel = f.relative_to(src_path)
        except ValueError:
            continue
        if rel not in mirror_stats:
            new_or_changed_tracked.add(f)
            continue
        try:
            src_st = f.stat()
            mir_st = mirror_stats[rel]
            if src_st.st_size != mir_st.st_size or abs(src_st.st_mtime - mir_st.st_mtime) > 1:
                new_or_changed_tracked.add(f)
        except OSError:
            new_or_changed_tracked.add(f)

    for rel in mirror_files_set:
        if rel in tracked_rel_set:
            if not (src_path / rel).exists():
                deleted_tracked.add(rel)

    # Create increment
    increment_created = False
    metadata_path = None
    if new_or_changed_tracked or deleted_tracked:
        ts = time.strftime("%Y%m%d_%H%M%S")
        increment_path = dst_path / f"backup_{ts}"
        increment_path.mkdir(parents=True, exist_ok=True)
        files_added = False

        for rel in deleted_tracked:
            src_mirror_file = mirror_path / rel
            if src_mirror_file.exists():
                dst_file = increment_path / "deleted" / rel
                if hardlink_file(src_mirror_file, dst_file):
                    files_added = True

        for f in new_or_changed_tracked:
            if not f.exists():
                continue
            rel = f.relative_to(src_path)
            dest_in_mirror = mirror_path / rel
            if copy_file(f, dest_in_mirror):
                dst_file = increment_path / "track" / rel
                if hardlink_file(dest_in_mirror, dst_file):
                    files_added = True

        if files_added:
            metadata_path = create_increment_metadata(increment_path, new_or_changed_tracked, deleted_tracked, src_path)
            increment_created = True
        else:
            try:
                shutil.rmtree(increment_path)
            except Exception:
                pass
            increment_created = False

    # Update mirror
    log.info("Updating mirror directory...")
    files_to_update = []
    for src_file in all_files_set:
        try:
            rel = src_file.relative_to(src_path)
        except ValueError:
            continue
        mirror_file = mirror_path / rel
        try:
            src_st = src_file.stat()
        except OSError:
            continue
        if not mirror_file.exists():
            files_to_update.append((src_file, mirror_file))
            continue
        try:
            mir_st = mirror_file.stat()
            if src_st.st_size != mir_st.st_size or abs(src_st.st_mtime - mir_st.st_mtime) > 1:
                files_to_update.append((src_file, mirror_file))
        except OSError:
            files_to_update.append((src_file, mirror_file))

    total_success = 0
    if files_to_update:
        ops = optimize_copy_operations(files_to_update, cfg.get("max_files_per_dir", 50))
        for op_type, group in ops:
            if op_type == 'sequential':
                total_success += copy_files_sequential(group)
            else:
                with ThreadPoolExecutor(max_workers=cfg["max_workers"]) as exe:
                    futures = {exe.submit(copy_file, src, dst): (src, dst) for src, dst in group}
                    for future in as_completed(futures):
                        src_dst = futures[future]
                        try:
                            if future.result():
                                total_success += 1
                        except Exception as e:
                            src, dst = src_dst
                            log.warning(f"Error copying {src} to {dst}: {e}")

    # Cleanup mirror
    current_source_rel = {f.relative_to(src_path) for f in all_files_set}
    files_to_remove = [mirror_path / rel for rel in mirror_files_set if rel not in current_source_rel]
    removed_count = 0
    for f in files_to_remove:
        try:
            f.unlink()
            removed_count += 1
        except OSError:
            continue
    remove_empty_dirs(mirror_path)
    mirror_files_set = scan_mirror_files(mirror_path)

    # Summary
    total_time = time.time() - total_start_time
    log.info(f"Source: {len(all_files_set)} | Tracked: {len(tracked_set)} | Mirror: {len(mirror_files_set)} | Updated: {total_success} | Removed: {removed_count}")
    if increment_created:
        log.info(f"Increment created: {len(new_or_changed_tracked)} new/changed, {len(deleted_tracked)} deleted (folder: {increment_path.name})")
    else:
        log.info("No file changes - no increment created")
    log.info(f"Total time: {total_time:.2f}s")

# -------------------- MAIN --------------------
if __name__ == "__main__":
    import argparse
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
