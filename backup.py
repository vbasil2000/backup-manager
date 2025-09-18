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
    # Defaults
    cfg.setdefault("max_workers", 8)
    cfg.setdefault("include_dirs", [])
    cfg.setdefault("track_dirs", [])
    cfg.setdefault("include_files", [])
    cfg.setdefault("track_files", [])
    cfg.setdefault("exclude_dirs", [])
    cfg.setdefault("exclude_files", [])
    cfg.setdefault("max_files_per_dir", 50)
    return cfg

# -------------------- PREPROCESSOR (expand dirs) --------------------
def parse_rec_pattern(pattern: str):
    if pattern.endswith(":rec"):
        return pattern[:-4], True
    return pattern, False

def expand_directory_patterns(base_path: Path, patterns: list[str]) -> list[str]:
    expanded = set()
    for pattern in patterns:
        if pattern.endswith(":rec"):
            actual_pattern = pattern[:-4]
            matches = list(base_path.rglob(actual_pattern))
        else:
            matches = list(base_path.glob(pattern))
        for match in matches:
            if match.is_dir() and match.exists():
                try:
                    rel_path = match.relative_to(base_path)
                    expanded.add(str(rel_path))
                except ValueError:
                    continue
    return sorted(expanded)

def preprocess_config(cfg_path: Path):
    if not cfg_path.exists():
        log.error(f"Config file not found: {cfg_path}")
        exit(1)
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)

    base_path = Path(cfg["src"]).expanduser().resolve()

    for key in ["include_dirs", "track_dirs", "exclude_dirs"]:
        if key in cfg and cfg[key]:
            cfg[key] = expand_directory_patterns(base_path, cfg[key])
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
def build_mirror_set_with_metadata(src_path: Path, include_dirs, track_dirs, include_files, track_files, exclude_dirs, exclude_files):
    src_path = src_path.resolve()
    all_files = {}  # Path -> (is_tracked, (size, mtime))
    exclude_parts = [tuple(Path(d).parts) for d in exclude_dirs]

    def is_excluded(rel_parts):
        for ep in exclude_parts:
            if len(rel_parts) >= len(ep) and tuple(rel_parts[:len(ep)]) == ep:
                return True
        return False

    # Scan include_dirs + track_dirs
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
                    rel = entry.relative_to(src_path)
                    if entry.is_dir():
                        if not is_excluded(rel.parts):
                            stack.append(entry)
                    elif entry.is_file():
                        if is_excluded(rel.parts):
                            continue
                        try:
                            st = entry.stat()
                        except OSError:
                            continue
                        all_files[entry] = (is_tracked, (st.st_size, st.st_mtime))
            except (PermissionError, OSError):
                continue

    # Explicit include/track files
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
                st = m.stat()
            except OSError:
                continue
            all_files[m] = (is_tracked, (st.st_size, st.st_mtime))
            explicit_files.add(m)

    # Exclude files for non-explicit
    for f in list(all_files.keys()):
        if f in explicit_files:
            continue
        rel = f.relative_to(src_path)
        for pat in exclude_files:
            if matches_exclude_for_file(rel, pat):
                del all_files[f]
                break

    return all_files

def scan_mirror_with_metadata(mirror_path: Path):
    mirror_files = {}
    if not mirror_path.exists():
        return mirror_files
    stack = [mirror_path]
    while stack:
        current = stack.pop()
        try:
            for entry in current.iterdir():
                rel = entry.relative_to(mirror_path)
                if entry.is_file():
                    try:
                        st = entry.stat()
                    except OSError:
                        continue
                    mirror_files[rel] = (st.st_size, st.st_mtime)
                elif entry.is_dir():
                    stack.append(entry)
        except (PermissionError, OSError):
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
def backup(config_file: Path, dry_run=False):
    total_start_time = time.time()
    cfg = preprocess_config(config_file)
    src_path = Path(cfg["src"]).expanduser().resolve()
    dst_path = Path(cfg["dist"]).expanduser().resolve()
    mirror_path = dst_path / "mirror"
    mirror_path.mkdir(parents=True, exist_ok=True)

    log.info("Scanning source directory with metadata...")
    src_files_dict = build_mirror_set_with_metadata(
        src_path,
        cfg["include_dirs"],
        cfg["track_dirs"],
        cfg["include_files"],
        cfg["track_files"],
        cfg["exclude_dirs"],
        cfg["exclude_files"]
    )
    all_files_set = set(src_files_dict.keys())
    tracked_set = {f for f, (tracked, _) in src_files_dict.items() if tracked}
    tracked_rel_set = {f.relative_to(src_path) for f in tracked_set}

    log.info("Scanning mirror directory with metadata...")
    mirror_files_dict = scan_mirror_with_metadata(mirror_path)
    mirror_set = set(mirror_files_dict.keys())

    # Compare tracked files
    new_or_changed_tracked = {f for f in tracked_set
                              if f.relative_to(src_path) not in mirror_set
                              or src_files_dict[f][1] != mirror_files_dict.get(f.relative_to(src_path))}
    deleted_tracked = {rel for rel in mirror_set if rel in tracked_rel_set and not (src_path / rel).exists()}

    # Create increment if needed
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

    # Update mirror
    files_to_update = []
    for src_file in all_files_set:
        rel = src_file.relative_to(src_path)
        src_meta = src_files_dict[src_file][1]
        mir_meta = mirror_files_dict.get(rel)
        mirror_file = mirror_path / rel
        if mir_meta != src_meta:
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
    current_rel_set = {f.relative_to(src_path) for f in all_files_set}
    files_to_remove = [mirror_path / rel for rel in mirror_set if rel not in current_rel_set]
    removed_count = 0
    for f in files_to_remove:
        try:
            f.unlink()
            removed_count += 1
        except OSError:
            continue
    remove_empty_dirs(mirror_path)

    total_time = time.time() - total_start_time
    log.info(f"Source files: {len(all_files_set)}, Tracked files: {len(tracked_set)}")
    mirror_files_set = scan_mirror_with_metadata(mirror_path)
    log.info(f"Mirror files: {len(mirror_files_set)}, Updated: {total_success}, Removed: {removed_count}")
    if increment_created:
        log.info(f"Increment created: {len(new_or_changed_tracked)} new/changed, {len(deleted_tracked)} deleted (folder: {increment_path.name})")
    else:
        log.info("No changes - increment not created")
    log.info(f"Total time: {total_time:.2f}s")

# -------------------- MAIN --------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Backup script with mirror + incremental")
    parser.add_argument("config", nargs="?", default="config.json", help="Path to config file")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run")
    args = parser.parse_args()
    config_file = Path(args.config).resolve()
    backup(config_file, dry_run=args.dry_run)
