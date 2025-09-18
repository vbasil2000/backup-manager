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
    """
    Загружает конфиг JSON и подставляет значения по умолчанию.
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
    cfg.setdefault("max_files_per_dir", 50)
    return cfg

# -------------------- PREPROCESSOR --------------------
def parse_rec_pattern(pattern: str):
    """
    Проверяет, оканчивается ли шаблон на :rec (рекурсивный поиск) и возвращает (шаблон, is_rec).
    """
    if pattern.endswith(":rec"):
        return pattern[:-4], True
    return pattern, False

def expand_directory_patterns(base_path: Path, patterns: list):
    """
    Разворачивает маски директорий в список существующих относительных директорий.
    """
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
    """
    Загружает конфиг и разворачивает маски директорий для include/track/exclude.
    """
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
    """
    Копирует файл с сохранением метаданных. Создает папку при необходимости.
    """
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except Exception as e:
        log.warning(f"Failed to copy {src} to {dst}: {e}")
        return False

def copy_files_sequential(files_to_copy):
    """
    Копирует файлы последовательно.
    """
    success_count = 0
    for src, dst in files_to_copy:
        if copy_file(src, dst):
            success_count += 1
    return success_count

def optimize_copy_operations(files_to_update, max_files_per_dir=50):
    """
    Разбивает операции копирования на последовательные и параллельные
    в зависимости от количества файлов в директории.
    """
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
    """
    Создает жесткую ссылку на файл, если невозможно — копирует.
    """
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.link(src, dst)
        return True
    except (OSError, PermissionError):
        return copy_file(src, dst)

def remove_empty_dirs(path: Path):
    """
    Рекурсивно удаляет пустые директории.
    """
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
    """
    Проверяет, соответствует ли файл паттерну exclude.
    """
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
    """
    Собирает все файлы из исходника с метаданными (размер, mtime) и отслеживанием.
    """
    src_path = src_path.resolve()
    all_files = {}
    exclude_parts = [tuple(Path(d).parts) for d in exclude_dirs]

    def is_excluded(rel_parts):
        for ep in exclude_parts:
            if len(rel_parts) >= len(ep) and tuple(rel_parts[:len(ep)]) == ep:
                return True
        return False

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
def scan_mirror_with_metadata(mirror_path: Path):
    """
    Собирает файлы и директории из зеркала с метаданными.
    """
    mirror_files = {}
    mirror_dirs = set()
    if not mirror_path.exists():
        return mirror_files, mirror_dirs
    stack = [mirror_path]
    while stack:
        current = stack.pop()
        try:
            for entry in current.iterdir():
                rel = entry.relative_to(mirror_path)
                try:
                    if entry.is_file():
                        try:
                            st = entry.stat()
                        except OSError:
                            continue
                        mirror_files[rel] = (st.st_size, st.st_mtime)
                    elif entry.is_dir():
                        mirror_dirs.add(rel)
                        stack.append(entry)
                except (OSError, PermissionError):
                    continue
        except (OSError, PermissionError):
            continue
    return mirror_files, mirror_dirs

# -------------------- METADATA --------------------
def create_increment_metadata(increment_path: Path, new_changed_files, deleted_files, src_path: Path):
    """
    Создает JSON с информацией о новых/измененных и удаленных файлах.
    """
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
            "deleted": [str(rel) for rel in sorted(deleted_files)]
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
    """
    Основная функция резервного копирования с mirror + incremental.
    """
    total_start_time = time.time()

    # --- Preprocess config ---
    cfg = preprocess_config(config_file)
    src_path = Path(cfg["src"]).expanduser().resolve()
    dst_path = Path(cfg["dist"]).expanduser().resolve()
    mirror_path = dst_path / "mirror"
    mirror_path.mkdir(parents=True, exist_ok=True)

    # --- Save expanded config for debugging ---
    try:
        expanded_config_path = dst_path / "config_expanded.json"
        with open(expanded_config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log.warning(f"Failed to save expanded config: {e}")

    # --- Scan source and mirror ---
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
    mirror_files_dict, mirror_dirs_set = scan_mirror_with_metadata(mirror_path)
    mirror_files_set = set(mirror_files_dict.keys())
    mirror_dirs_set = set(mirror_dirs_set)

    # --- Determine new/changed/deleted tracked files ---
    new_or_changed_tracked = set()
    for f in tracked_set:
        try:
            rel = f.relative_to(src_path)
        except ValueError:
            continue
        src_meta = src_files_dict[f][1]
        mir_meta = mirror_files_dict.get(rel)
        if mir_meta is None or src_meta != mir_meta:
            new_or_changed_tracked.add(f)

    tracked_dirs_rel = [Path(d) for d in cfg.get("track_dirs", [])]

    def rel_under_tracked_dir(rel: Path) -> bool:
        for td in tracked_dirs_rel:
            td_parts = td.parts
            if len(rel.parts) >= len(td_parts) and tuple(rel.parts[:len(td_parts)]) == td_parts:
                return True
        return False

    def rel_matches_track_files(rel: Path) -> bool:
        pstr = str(rel)
        for pattern in cfg.get("track_files", []):
            pat, is_rec = parse_rec_pattern(pattern)
            if is_rec:
                if fnmatch.fnmatch(pstr, pat):
                    return True
            elif '/' in pattern:
                if fnmatch.fnmatch(pstr, pattern):
                    return True
            else:
                if rel.parent == Path('.') and fnmatch.fnmatch(rel.name, pattern):
                    return True
        return False

    deleted_tracked = set()
    for rel in mirror_files_set:
        src_candidate = src_path / rel
        if src_candidate.exists():
            continue
        if rel in tracked_rel_set or rel_under_tracked_dir(rel) or rel_matches_track_files(rel):
            deleted_tracked.add(rel)
    for rel in mirror_dirs_set:
        src_candidate = src_path / rel
        if src_candidate.exists():
            continue
        if rel_under_tracked_dir(rel):
            deleted_tracked.add(rel)

    # --- Create increment if needed ---
    increment_created = False
    metadata_path = None
    if new_or_changed_tracked or deleted_tracked:
        ts = time.strftime("%Y%m%d_%H%M%S")
        increment_path = dst_path / f"backup_{ts}"
        increment_path.mkdir(parents=True, exist_ok=True)
        files_added = False

        # Deleted files -> increment/deleted
        for rel in sorted(deleted_tracked):
            src_mirror_file = mirror_path / rel
            if src_mirror_file.exists() and src_mirror_file.is_file():
                dst_file = increment_path / "deleted" / rel
                if hardlink_file(src_mirror_file, dst_file):
                    files_added = True
            elif (mirror_path / rel).exists() and (mirror_path / rel).is_dir():
                dst_dir = increment_path / "deleted" / rel
                try:
                    dst_dir.mkdir(parents=True, exist_ok=True)
                    files_added = True
                except Exception:
                    pass

        # New/changed tracked files -> mirror + increment/track
        for f in sorted(new_or_changed_tracked):
            if not f.exists():
                continue
            rel = f.relative_to(src_path)
            dest_in_mirror = mirror_path / rel
            if copy_file(f, dest_in_mirror):
                dst_file = increment_path / "track" / rel
                if hardlink_file(dest_in_mirror, dst_file):
                    files_added = True

        if files_added or deleted_tracked:
            metadata_path = create_increment_metadata(increment_path, new_or_changed_tracked, deleted_tracked, src_path)
            increment_created = True
        else:
            try:
                shutil.rmtree(increment_path)
            except Exception:
                pass

    # --- Update mirror for non-tracked files ---
    files_to_update = []
    for src_file in all_files_set:
        rel = src_file.relative_to(src_path)
        src_meta = src_files_dict[src_file][1]
        mir_meta = mirror_files_dict.get(rel)
        mirror_file = mirror_path / rel
        if mir_meta != src_meta:
            files_to_update.append((src_file, mirror_file))
    files_to_update = [(s, d) for s, d in files_to_update if s not in new_or_changed_tracked]

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

    # --- Cleanup mirror ---
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

    # --- Summary ---
    total_time = time.time() - total_start_time
    log.info(f"Source files: {len(all_files_set)}, Tracked files: {len(tracked_set)}")
    mirror_files_after, _ = scan_mirror_with_metadata(mirror_path)
    log.info(f"Mirror files: {len(mirror_files_after)}, Updated: {total_success}, Removed: {removed_count}")
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
    if not config_file.exists():
        log.error(f"Config file not found: {config_file}")
        exit(1)
    backup(config_file, dry_run=args.dry_run)
