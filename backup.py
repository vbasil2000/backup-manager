#!/usr/bin/env python3
import os
import shutil
import json
import time
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import fnmatch
from typing import Dict, Set, Tuple, List, Optional

def get_relative_path(path: Path, base: Path) -> Path:
    try:
        return path.relative_to(base)
    except ValueError:
        return Path(path.name) if path.parent == base else path

def parse_pattern(pattern: str) -> Tuple[str, bool]:
    """Парсит паттерны: для файлов :rec означает рекурсивный поиск"""
    return (pattern[:-4], True) if pattern.endswith(":rec") else (pattern, False)

def expand_directory_patterns(base_path: Path, patterns: list[str]) -> Set[Path]:
    """Разворачивает маски директорий в абсолютные пути (БЕЗ :rec)"""
    expanded = set()
    base_path = base_path.resolve()
    
    for pattern in patterns:
        # Для директорий :rec не используется!
        try:
            matches = list(base_path.glob(pattern))
            for match in matches:
                if match.is_dir() and match.exists():
                    expanded.add(match.resolve())
        except Exception:
            continue
    
    return expanded

def expand_file_patterns(base_path: Path, patterns: list[str]) -> Set[Path]:
    expanded = set()
    base_path = base_path.resolve()

    for pattern in patterns:
        pat, is_rec = parse_pattern(pattern)

        try:
            # Проверяем есть ли путь, но БЕЗ масок в пути
            if '/' in pat:
                # Разбиваем на путь и маску имени
                if '*' in pat.split('/')[0] or '?' in pat.split('/')[0]:
                    print(f"Skip: mask in path - {pattern}")
                    continue
                    
                # Четкий путь + маска имени - ОК
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
                # Простая маска имени
                if is_rec:
                    matches = base_path.rglob(pat)
                else:
                    matches = base_path.glob(pat)

            for match in matches:
                if match.is_file() and match.exists():
                    expanded.add(match.resolve())
                    
        except Exception as e:
            print(f"Error: {pattern}: {e}")

    return expanded

def is_file_excluded(file_path: Path, exclude_patterns: list[str], src_path: Path) -> bool:
    """Проверяет, исключен ли файл по паттернам"""
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
    """Проверяет, исключена ли директория"""
    return any(exclude_dir in dir_path.parents or exclude_dir == dir_path for exclude_dir in exclude_dirs)

def scan_source_with_exclusion(src_path: Path, cfg: dict) -> Tuple[Set[Path], Set[Path]]:
    """Сканирует источник с исключением директорий"""
    src_path = src_path.resolve()
    
    # Разворачиваем все маски директорий (БЕЗ :rec)
    include_dirs = expand_directory_patterns(src_path, cfg["include_dirs"])
    track_dirs = expand_directory_patterns(src_path, cfg["track_dirs"])
    exclude_dirs = expand_directory_patterns(src_path, cfg["exclude_dirs"])
    
    # Сканируем директории с исключением
    all_files = set()
    tracked_files = set()
    
    # 1. Файлы из директорий (include_dirs + track_dirs)
    for dir_path in include_dirs | track_dirs:
        if is_dir_excluded(dir_path, exclude_dirs):
            continue
            
        try:
            for root, dirs, files in os.walk(dir_path):
                current_dir = Path(root)
                
                # Фильтруем поддиректории для исключенных
                dirs[:] = [d for d in dirs if not is_dir_excluded(current_dir / d, exclude_dirs)]
                
                for file in files:
                    file_path = current_dir / file
                    if file_path.is_file():
                        all_files.add(file_path)
        except (PermissionError, OSError):
            continue
    
    # 2. Файлы из паттернов (include_files + track_files) - С :rec поддержкой!
    include_files = expand_file_patterns(src_path, cfg["include_files"])
    track_files = expand_file_patterns(src_path, cfg["track_files"])
    all_files |= include_files | track_files
    
    # 3. Применяем exclude_files (тоже с :rec поддержкой)
    if cfg["exclude_files"]:
        all_files = {f for f in all_files if not is_file_excluded(f, cfg["exclude_files"], src_path)}
    
    # 4. Определяем tracked файлы
    track_dirs_rel = {str(get_relative_path(d, src_path)) for d in track_dirs}
    for file_path in all_files:
        try:
            rel_path = get_relative_path(file_path, src_path)
            rel_str = str(rel_path)
            
            # Проверяем tracked директории
            if any(rel_str.startswith(d + os.sep) or rel_str == d for d in track_dirs_rel):
                tracked_files.add(file_path)
                continue
                
            # Проверяем tracked файлы (с :rec поддержкой)
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
    stat = file_path.stat()
    return (stat.st_size, stat.st_mtime)

def load_mirror_json(dst_path: Path) -> Dict[Path, Tuple[Tuple[int, float], bool]]:
    """Загружает mirror.json из корня dist"""
    mirror_json = dst_path / "mirror.json"
    if not mirror_json.exists():
        return {}
    
    try:
        with open(mirror_json, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except:
        return {}
    
    mirror_files = {}
    for rel_path_str, file_data in data.get("files", {}).items():
        if isinstance(file_data, dict) and "meta" in file_data:
            mirror_files[Path(rel_path_str)] = (tuple(file_data["meta"]), file_data.get("tracked", False))
        else:
            mirror_files[Path(rel_path_str)] = (tuple(file_data), False)
    
    return mirror_files

def save_mirror_json(dst_path: Path, source_files: Set[Path], tracked_files: Set[Path], src_path: Path):
    """Сохраняет mirror.json в корень dist"""
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
    try:
        with open(dst_path / "mirror.json", 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except:
        pass

def save_expanded_config(dst_path: Path, cfg: dict, src_path: Path):
    """Сохраняет развернутый конфиг в dist"""
    expanded_config = cfg.copy()
    
    # Сохраняем развернутые пути
    expanded_config["include_dirs"] = [str(get_relative_path(d, src_path)) for d in expand_directory_patterns(src_path, cfg["include_dirs"])]
    expanded_config["track_dirs"] = [str(get_relative_path(d, src_path)) for d in expand_directory_patterns(src_path, cfg["track_dirs"])]
    expanded_config["exclude_dirs"] = [str(get_relative_path(d, src_path)) for d in expand_directory_patterns(src_path, cfg["exclude_dirs"])]
    
    # Сохраняем оригинальные файловые паттерны (с :rec)
    expanded_config["include_files"] = cfg["include_files"]
    expanded_config["track_files"] = cfg["track_files"]
    expanded_config["exclude_files"] = cfg["exclude_files"]
    
    try:
        with open(dst_path / "config_expanded.json", 'w', encoding='utf-8') as f:
            json.dump(expanded_config, f, indent=2, ensure_ascii=False)
    except:
        pass

def safe_copy(src: Path, dst: Path) -> bool:
    """Безопасное копирование файла"""
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except:
        return False

def safe_remove(path: Path) -> bool:
    """Безопасное удаление файла"""
    try:
        if path.exists():
            path.unlink()
            return True
    except:
        pass
    return False

def load_config(config_file: Path) -> dict:
    """Загружает конфигурацию"""
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
            "max_workers": 8
        }
        with open(config_file, 'w') as f:
            json.dump(default_config, f, indent=2)
        print(f"Created default config: {config_file}")
        sys.exit(1)
    
    with open(config_file, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    
    # Значения по умолчанию
    defaults = {
        "max_workers": 8,
        "use_mirror_json": True,
        "include_root": False
    }
    
    for key, value in defaults.items():
        if key not in cfg:
            cfg[key] = value
    
    return cfg

def backup(config_file: Path):
    """Основная функция бэкапа"""
    start_time = time.time()
    
    try:
        cfg = load_config(config_file)
        src_path = Path(cfg["src"]).expanduser().resolve()
        dst_path = Path(cfg["dist"]).expanduser().resolve()
        
        if not src_path.exists():
            raise FileNotFoundError(f"Source path does not exist: {src_path}")
    except Exception as e:
        print(f"Config error: {e}")
        sys.exit(1)
    
    mirror_path = dst_path / "mirror"
    mirror_path.mkdir(parents=True, exist_ok=True)
    
    print("Scanning source directory with metadata...")
    source_files, tracked_files = scan_source_with_exclusion(src_path, cfg)
    
    print("Scanning mirror directory with metadata...")
    old_mirror = load_mirror_json(dst_path)
    
    # Подготавливаем множества путей
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
    
    # 1. Определяем изменения для MIRROR (все файлы)
    mirror_new = source_paths - old_mirror_paths
    mirror_changed = set()
    mirror_deleted = old_mirror_paths - source_paths
    
    for path in source_paths & old_mirror_paths:
        current_meta = get_file_metadata(src_path / path)
        if current_meta != old_mirror[path][0]:
            mirror_changed.add(path)
    
    # 2. Определяем изменения для ИНКРЕМЕНТА (только tracked)
    increment_new = tracked_paths - old_mirror_paths
    increment_changed = set()
    increment_deleted = old_tracked_paths - source_paths
    
    for path in tracked_paths & old_tracked_paths:
        current_meta = get_file_metadata(src_path / path)
        if current_meta != old_mirror[path][0]:
            increment_changed.add(path)
    
    # 3. Создаем инкремент (только tracked изменения)
    increment_created = False
    if increment_new or increment_changed or increment_deleted:
        ts = time.strftime("%Y%m%d_%H%M%S")
        increment_path = dst_path / f"backup_{ts}"
        increment_path.mkdir(parents=True, exist_ok=True)
        
        # Новые/измененные tracked файлы
        for rel_path in increment_new | increment_changed:
            src_file = src_path / rel_path
            dst_file = increment_path / "track" / rel_path
            safe_copy(src_file, dst_file)
        
        # Удаленные tracked файлы
        for rel_path in increment_deleted:
            old_file = mirror_path / rel_path
            if old_file.exists():
                dst_file = increment_path / "deleted" / rel_path
                safe_copy(old_file, dst_file)
        
        increment_created = True
    
    # 4. Обновляем MIRROR (все файлы)
    mirror_update = mirror_new | mirror_changed
    mirror_remove = mirror_deleted
    
    # Копируем новые/измененные файлы
    for rel_path in mirror_update:
        src_file = src_path / rel_path
        dst_file = mirror_path / rel_path
        safe_copy(src_file, dst_file)
    
    # Удаляем старые файлы
    for rel_path in mirror_remove:
        old_file = mirror_path / rel_path
        safe_remove(old_file)
    
    # 5. Сохраняем состояние mirror и развернутый конфиг в КОРЕНЬ dist
    save_mirror_json(dst_path, source_files, tracked_files, src_path)
    save_expanded_config(dst_path, cfg, src_path)
    
    # 6. Вывод статистики
    total_time = time.time() - start_time
    print(f"Source files: {len(source_files)}, Tracked files: {len(tracked_files)}")
    print(f"Mirror files: {len(old_mirror)}, Updated: {len(mirror_update)}, Removed: {len(mirror_remove)}")
    
    if increment_created:
        print(f"Increment created: {len(increment_new) + len(increment_changed)} new/changed, {len(increment_deleted)} deleted")
    else:
        print("No changes - increment not created")
    
    print(f"Total time: {total_time:.2f}s")

if __name__ == "__main__":
    config_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("config.json")
    backup(config_file)
    
