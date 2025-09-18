#!/usr/bin/env python3
import os
import shutil
import json
import time
import sys
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
    Load JSON config and set sensible defaults.
    Returns a dict with defaulted keys.
    """
    with open(config_file, encoding="utf-8") as f:
        cfg = json.load(f)
    # defaults
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
    Parse a pattern for ':rec' suffix.

    Returns (pattern_without_suffix, is_rec_flag).
    Note: :rec is used only for *file* patterns in this codebase.
    """
    if pattern.endswith(":rec"):
        return pattern[:-4], True
    return pattern, False


def expand_directory_patterns(base_path: Path, patterns: list):
    """
    Expand directory patterns against base_path.

    IMPORTANT:
      - Directories are treated as recursive by default (we walk inside them).
      - The ':rec' suffix on directory patterns is ignored — :rec is meaningful only for file masks.
      - This function finds directories that match the provided glob patterns at top-level under base_path
        (base_path.glob(pattern)). It does not perform a full recursive rglob for directory patterns,
        to avoid surprising matches. If you want to include nested directories by name, specify an explicit pattern.
    """
    expanded = set()
    for pattern in patterns:
        # If user accidentally added ':rec' for a directory pattern, strip it but don't do rglob.
        if pattern.endswith(":rec"):
            pat = pattern[:-4]
        else:
            pat = pattern
        try:
            matches = list(base_path.glob(pat))
        except Exception:
            matches = []
        for match in matches:
            if match.is_dir() and match.exists():
                try:
                    rel_path = match.relative_to(base_path)
                    expanded.add(str(rel_path))
                except ValueError:
                    # skip paths not under base_path
                    continue
    return sorted(expanded)


def preprocess_config(cfg_path: Path):
    """
    Load config (with defaults) and expand directory masks for include/track/exclude.
    Validates presence of 'src' and 'dist'.
    """
    if not cfg_path.exists():
        log.error(f"Config file not found: {cfg_path}")
        sys.exit(1)

    # Use load_config to apply default values
    cfg = load_config(cfg_path)

    if "src" not in cfg or "dist" not in cfg:
        log.error("Config must contain 'src' and 'dist' keys")
        sys.exit(1)

    base_path = Path(cfg["src"]).expanduser().resolve()

    # Expand directory patterns (include/track/exclude directories)
    for key in ["include_dirs", "track_dirs", "exclude_dirs"]:
        if key in cfg and cfg[key]:
            cfg[key] = expand_directory_patterns(base_path, cfg[key])
    return cfg


# -------------------- FILE OPERATIONS --------------------
def copy_file(src: Path, dst: Path, dry_run: bool = False) -> bool:
    """
    Copy a file preserving metadata (shutil.copy2).
    If dry_run is True, only log the intended action and return True (simulate success).
    """
    if dry_run:
        log.info(f"[dry-run] copy {src} -> {dst}")
        return True
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except Exception as e:
        log.warning(f"Failed to copy {src} to {dst}: {e}")
        return False


def copy_files_sequential(files_to_copy, dry_run: bool = False):
    """
    Sequential copy of a list of (src, dst) tuples. Uses copy_file for each.
    """
    success_count = 0
    for src, dst in files_to_copy:
        if copy_file(src, dst, dry_run=dry_run):
            success_count += 1
    return success_count


def optimize_copy_operations(files_to_update, max_files_per_dir=50):
    """
    Group copy operations by target directory and decide whether each group
    should be copied 'sequential'ly or 'parallel'ly based on max_files_per_dir.
    Returns a list of tuples: ('sequential'|'parallel', group_list)
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


def hardlink_file(src: Path, dst: Path, dry_run: bool = False) -> bool:
    """
    Create a hard link from src to dst. If hard link creation fails (cross-device, permissions),
    fall back to copying the file.
    If dry_run is True, only log the intended action and return True.
    """
    if dry_run:
        log.info(f"[dry-run] hardlink {src} -> {dst}")
        return True
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.link(src, dst)
        return True
    except (OSError, PermissionError):
        # fallback to copy (copy_file supports dry_run by default False here)
        return copy_file(src, dst, dry_run=False)


def remove_empty_dirs(path: Path):
    """
    Recursively remove empty directories under 'path'.
    Non-fatal on permission errors.
    """
    try:
        for root, dirs, _ in os.walk(path, topdown=False):
            for d in dirs:
                p = Path(root) / d
                try:
                    if p.exists() and not any(p.iterdir()):
                        p.rmdir()
                except (PermissionError, OSError):
                    continue
    except (PermissionError, OSError):
        pass


def matches_exclude_for_file(rel_path: Path, pattern: str) -> bool:
    """
    Return True if relative file path matches an exclude file pattern.
    Supports ':rec' suffix for recursive file pattern matching.
    """
    pstr = str(rel_path)
    pat, is_rec = parse_rec_pattern(pattern)
    if is_rec:
        return fnmatch.fnmatch(pstr, pat)
    if '/' in pattern:
        # pattern includes path component(s) — match against the full relative path
        return fnmatch.fnmatch(pstr, pattern)
    else:
        # pattern without path — only match files in root of tracked directory
        if rel_path.parent == Path('.'):
            return fnmatch.fnmatch(rel_path.name, pattern)
        return False


# -------------------- MIRROR BUILD --------------------
def build_mirror_set_with_metadata(src_path: Path,
                                   include_dirs, track_dirs,
                                   include_files, track_files,
                                   exclude_dirs, exclude_files):
    """
    Scan the source tree (only inside include_dirs and track_dirs), collect files,
    and return a dict mapping absolute Path -> (is_tracked, (size, mtime)).

    Exclude directories (exclude_dirs) are used to prune traversal early.
    Explicit include_files/track_files (patterns) are also resolved and added.
    """
    src_path = src_path.resolve()
    all_files = {}  # Path -> (is_tracked, (size, mtime))
    exclude_parts = [tuple(Path(d).parts) for d in exclude_dirs]

    def is_excluded(rel_parts):
        # Check whether the relative path parts start with any exclude_parts
        for ep in exclude_parts:
            if len(rel_parts) >= len(ep) and tuple(rel_parts[:len(ep)]) == ep:
                return True
        return False

    # Walk only inside the include and track directories (no global walk).
    for d in include_dirs + track_dirs:
        is_tracked = d in track_dirs
        root = src_path / d
        if not root.exists():
            # missing include/track directory -> skip
            continue
        stack = [root]
        while stack:
            current = stack.pop()
            try:
                for entry in current.iterdir():
                    # compute relative path once
                    try:
                        rel = entry.relative_to(src_path)
                    except ValueError:
                        continue
                    if entry.is_dir():
                        if not is_excluded(rel.parts):
                            # dir not excluded -> descend into it
                            stack.append(entry)
                    elif entry.is_file():
                        if is_excluded(rel.parts):
                            continue
                        try:
                            st = entry.stat()
                        except OSError:
                            # cannot stat file -> skip
                            continue
                        all_files[entry] = (is_tracked, (st.st_size, st.st_mtime))
            except (PermissionError, OSError):
                # skip directories we cannot access
                continue

    # Handle explicit include_files / track_files patterns (they may be outside include_dirs)
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

    # Apply exclude_files patterns (only to non-explicit files)
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
    Scan mirror directory and return:
      - mirror_files: dict of relative_path -> (size, mtime)
      - mirror_dirs: set of relative directory paths
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
                try:
                    rel = entry.relative_to(mirror_path)
                except ValueError:
                    continue
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
def create_increment_metadata(increment_path: Path, new_changed_files, deleted_files, src_path: Path, dry_run: bool = False):
    """
    Create a JSON metadata file for the increment with:
      - backup info (name, timestamps)
      - statistics (counts)
      - sample of new/changed files and list of deleted files (relative)
    If dry_run is True, metadata is not written to disk (only logged).
    """
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

    metadata_path = increment_path / f"{increment_path.name}.json"
    if dry_run:
        log.info(f"[dry-run] would write metadata to {metadata_path} -> {json.dumps(metadata, indent=2, ensure_ascii=False)[:500]}...")
        return metadata_path
    try:
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        with open(metadata_path, "w", encoding="utf-8") as mf:
            json.dump(metadata, mf, indent=2, ensure_ascii=False)
    except Exception as e:
        log.warning(f"Failed to write metadata: {e}")
    return metadata_path


# -------------------- BACKUP --------------------
def backup(config_file: Path, dry_run: bool = False):
    """
    Main backup routine: preprocess config, scan source & mirror, decide which files to copy/delete,
    create an increment (hardlinks) for tracked changes and update the mirror.
    If dry_run is True, do not perform destructive or write operations — only log them.
    """
    total_start_time = time.time()

    # --- Preprocess config ---
    cfg = preprocess_config(config_file)
    # Add dry_run flag into cfg for convenience (not strictly necessary)
    cfg["dry_run"] = bool(dry_run)

    src_path = Path(cfg["src"]).expanduser().resolve()
    dst_path = Path(cfg["dist"]).expanduser().resolve()

    if not src_path.exists() or not src_path.is_dir():
        log.error(f"Source path does not exist or is not a directory: {src_path}")
        sys.exit(1)

    mirror_path = dst_path / "mirror"
    if not dry_run:
        mirror_path.mkdir(parents=True, exist_ok=True)
    else:
        log.info(f"[dry-run] ensure mirror dir would exist: {mirror_path}")

    # --- Save expanded config for debugging (skip on dry-run) ---
    expanded_config_path = dst_path / "config_expanded.json"
    try:
        if dry_run:
            log.info(f"[dry-run] would write expanded config to {expanded_config_path}")
        else:
            expanded_config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(expanded_config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            log.info(f"Expanded config saved: {expanded_config_path}")
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

    all_files_set = set(src_files_dict.keys())  # absolute Paths
    tracked_set = {f for f, (tracked, _) in src_files_dict.items() if tracked}
    tracked_rel_set = {f.relative_to(src_path) for f in tracked_set}

    log.info("Scanning mirror directory with metadata...")
    mirror_files_dict, mirror_dirs = scan_mirror_with_metadata(mirror_path)
    mirror_files_set = set(mirror_files_dict.keys())
    mirror_dirs_set = set(mirror_dirs)

    # --- Determine new/changed tracked files ---
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
        """
        Return True if rel (relative path) is inside any tracked directory.
        """
        for td in tracked_dirs_rel:
            td_parts = td.parts
            if len(rel.parts) >= len(td_parts) and tuple(rel.parts[:len(td_parts)]) == td_parts:
                return True
        return False

    def rel_matches_track_files(rel: Path) -> bool:
        """
        Return True if the relative path matches any pattern in track_files.
        Supports ':rec' on file patterns.
        """
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

    # --- Determine deleted tracked files/dirs by comparing mirror -> src (no stat needed) ---
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

    # --- Create increment (if needed) ---
    increment_created = False
    metadata_path = None
    if new_or_changed_tracked or deleted_tracked:
        ts = time.strftime("%Y%m%d_%H%M%S")
        increment_path = dst_path / f"backup_{ts}"
        if not dry_run:
            increment_path.mkdir(parents=True, exist_ok=True)
        else:
            log.info(f"[dry-run] would create increment dir: {increment_path}")
        files_added = False

        # Deleted files -> put snapshot of them into increment/deleted (hardlink from mirror if possible)
        for rel in sorted(deleted_tracked):
            src_mirror_file = mirror_path / rel
            if src_mirror_file.exists() and src_mirror_file.is_file():
                dst_file = increment_path / "deleted" / rel
                if hardlink_file(src_mirror_file, dst_file, dry_run=dry_run):
                    files_added = True
            elif (mirror_path / rel).exists() and (mirror_path / rel).is_dir():
                dst_dir = increment_path / "deleted" / rel
                try:
                    if dry_run:
                        log.info(f"[dry-run] would create dir: {dst_dir}")
                    else:
                        dst_dir.mkdir(parents=True, exist_ok=True)
                    files_added = True
                except Exception:
                    pass

        # New/changed tracked files -> copy to mirror and hardlink into increment/track
        for f in sorted(new_or_changed_tracked):
            if not f.exists():
                continue
            rel = f.relative_to(src_path)
            dest_in_mirror = mirror_path / rel
            if copy_file(f, dest_in_mirror, dry_run=dry_run):
                dst_file = increment_path / "track" / rel
                if hardlink_file(dest_in_mirror, dst_file, dry_run=dry_run):
                    files_added = True

        if files_added or deleted_tracked:
            metadata_path = create_increment_metadata(increment_path, new_or_changed_tracked, deleted_tracked, src_path, dry_run=dry_run)
            increment_created = True
        else:
            # nothing to store
            if dry_run:
                log.info(f"[dry-run] would remove empty increment dir: {increment_path}")
            else:
                try:
                    shutil.rmtree(increment_path)
                except Exception:
                    pass

    # --- Update mirror for non-tracked files (parallel/sequential grouping) ---
    files_to_update = []
    for src_file in all_files_set:
        # skip ones already handled as tracked new/changed
        if src_file in new_or_changed_tracked:
            continue
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
                total_success += copy_files_sequential(group, dry_run=dry_run)
            else:
                # parallel copy: pass dry_run flag into worker
                with ThreadPoolExecutor(max_workers=cfg["max_workers"]) as exe:
                    futures = {exe.submit(copy_file, src, dst, dry_run): (src, dst) for src, dst in group}
                    for future in as_completed(futures):
                        src_dst = futures[future]
                        try:
                            if future.result():
                                total_success += 1
                        except Exception as e:
                            src, dst = src_dst
                            log.warning(f"Error copying {src} to {dst}: {e}")

    # --- Cleanup mirror: remove files that are no longer in source (no stat required) ---
    current_source_rel = {f.relative_to(src_path) for f in all_files_set}
    files_to_remove = [mirror_path / rel for rel in mirror_files_set if rel not in current_source_rel]
    removed_count = 0
    for f in files_to_remove:
        try:
            if dry_run:
                log.info(f"[dry-run] would remove: {f}")
            else:
                if f.exists():
                    f.unlink()
                    removed_count += 1
        except OSError:
            continue

    # Remove empty directories
    if dry_run:
        log.info(f"[dry-run] would remove empty dirs under {mirror_path}")
    else:
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
        sys.exit(1)
    backup(config_file, dry_run=args.dry_run)
