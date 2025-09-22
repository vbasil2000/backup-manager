#!/usr/bin/env python3
"""
Axiomatic Backup System - Реализация алгоритма построения множеств
"""

import os
import shutil
import json
import time
import sys
import logging
import fnmatch
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Set, Dict, List, Tuple, Any, Optional
from dataclasses import dataclass, field
from functools import lru_cache
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Настройка логирования ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("backup.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# --- Кэшированные вспомогательные функции ---

@lru_cache(maxsize=10000)
def get_relative_path_cached(path: Path, base: Path) -> Path:
    """Кэшированная версия get_relative_path"""
    try:
        return path.relative_to(base)
    except ValueError:
        return Path(path.name) if path.parent == base else path

@lru_cache(maxsize=1000)
def parse_pattern_cached(pattern: str) -> Tuple[str, bool]:
    """Кэшированная версия parse_pattern"""
    pattern = pattern.strip()
    if pattern.endswith(":rec"):
        return pattern[:-4], True
    return pattern, False

@lru_cache(maxsize=10000)
def get_file_metadata_cached(file_path: Path) -> Tuple[int, float]:
    """Кэшированная версия get_file_metadata (только размер и время модификации)"""
    try:
        stat = file_path.stat()
        return (stat.st_size, stat.st_mtime)
    except Exception as e:
        logger.warning(f"Error getting metadata for {file_path}: {e}")
        return (0, 0)

@lru_cache(maxsize=10000)
def is_dir_excluded_cached(dir_path: Path, exclude_dirs: Tuple[Path]) -> bool:
    """Кэшированная проверка исключения директории"""
    return any(exclude_dir in dir_path.parents or exclude_dir == dir_path for exclude_dir in exclude_dirs)

# --- Функции для работы с шаблонами ---

def expand_directory_patterns(base_path: Path, patterns: List[str]) -> Set[Path]:
    """Развертывание шаблонов директорий в абсолютные пути"""
    expanded = set()
    base_path = base_path.resolve()
    
    for pattern in patterns:
        try:
            if not pattern or pattern.strip() == "":
                continue
                
            # Для шаблонов с wildcards используем glob
            if '*' in pattern or '?' in pattern or '[' in pattern:
                matches = list(base_path.glob(pattern))
                for match in matches:
                    if match.exists() and match.is_dir():
                        expanded.add(match.resolve())
            else:
                # Для простых путей проверяем существование
                dir_path = base_path / pattern
                if dir_path.exists() and dir_path.is_dir():
                    expanded.add(dir_path.resolve())
        except Exception as e:
            logger.warning(f"Error expanding directory pattern '{pattern}': {e}")
    return expanded

def expand_file_patterns(base_path: Path, patterns: List[str]) -> Set[Path]:
    """Развертывание шаблонов файлов в абсолютные пути"""
    expanded = set()
    base_path = base_path.resolve()

    for pattern in patterns:
        pat, is_rec = parse_pattern_cached(pattern)

        try:
            if is_rec:
                matches = base_path.rglob(pat)
            else:
                matches = base_path.glob(pat)

            for match in matches:
                if match.is_file() and match.exists():
                    expanded.add(match.resolve())
        except Exception as e:
            logger.error(f"Error expanding pattern '{pattern}': {e}")

    return expanded

def is_file_excluded(file_path: Path, exclude_patterns: List[str], src_path: Path) -> bool:
    """Проверка исключения файла по шаблонам"""
    rel_path = get_relative_path_cached(file_path, src_path)
    
    for pattern in exclude_patterns:
        pat, is_rec = parse_pattern_cached(pattern)
        if is_rec:
            if fnmatch.fnmatch(str(rel_path), pat):
                return True
        else:
            if fnmatch.fnmatch(rel_path.name, pat):
                return True
    return False

# --- Сканирование файловой системы ---

def scan_directory_recursive(dir_path: Path, exclude_dirs: Set[Path]) -> Set[Path]:
    """Рекурсивное сканирование директории с исключениями"""
    files = set()
    
    try:
        for root, dirs, filenames in os.walk(dir_path):
            current_dir = Path(root)
            
            # Исключаем директории из exclude_dirs
            dirs[:] = [d for d in dirs if not is_dir_excluded_cached(current_dir / d, tuple(exclude_dirs))]
            
            # Добавляем файлы
            for filename in filenames:
                file_path = current_dir / filename
                if file_path.is_file():
                    files.add(file_path.resolve())
    except (PermissionError, OSError) as e:
        logger.warning(f"Can't scan directory {dir_path}: {e}")
    
    return files

def scan_all_directories(directories: Set[Path], exclude_dirs: Set[Path]) -> Set[Path]:
    """Сканирование всех директорий с исключениями"""
    all_files = set()
    
    for dir_path in directories:
        if not is_dir_excluded_cached(dir_path, tuple(exclude_dirs)):
            all_files.update(scan_directory_recursive(dir_path, exclude_dirs))
    
    return all_files

def remove_empty_dirs(path: Path, preserve_dirs: Set[str] = None):
    """Рекурсивно удаляет пустые директории, исключая preserve_dirs"""
    if preserve_dirs is None:
        preserve_dirs = set()
        
    try:
        # Сначала обрабатываем поддиректории
        for child in path.iterdir():
            if child.is_dir():
                remove_empty_dirs(child, preserve_dirs)
        
        # Проверяем, пуста ли текущая директория и не должна ли быть сохранена
        if path.is_dir() and not any(path.iterdir()):
            dir_name = path.name
            if not any(p in dir_name for p in preserve_dirs):
                try:
                    path.rmdir()
                    logger.debug(f"Removed empty directory: {path}")
                except (OSError, PermissionError) as e:
                    logger.warning(f"Can't remove directory {path}: {e}")
    except (PermissionError, OSError) as e:
        logger.warning(f"Can't access directory {path}: {e}")

def create_hardlink_or_copy(src: Path, dst: Path) -> bool:
    """Создает hardlink если возможно, иначе копирует файл"""
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.link(src, dst)
        logger.debug(f"Created hardlink: {src} -> {dst}")
        return True
    except (OSError, AttributeError):
        try:
            shutil.copy2(src, dst)
            logger.debug(f"Copied file (hardlink failed): {src} -> {dst}")
            return True
        except Exception as e:
            logger.error(f"Copy failed {src} -> {dst}: {e}")
            return False

# --- Классы конфигурации и системы бэкапа ---

@dataclass
class BackupConfig:
    """Конфигурация системы бэкапа"""
    src: Path
    dst: Path
    directory_priority: str = field(default="track")  # "include" или "track"
    include_dirs: Set[str] = field(default_factory=set)
    exclude_dirs: Set[str] = field(default_factory=set)
    include_files: Set[str] = field(default_factory=set)
    exclude_files: Set[str] = field(default_factory=set)
    track_dirs: Set[str] = field(default_factory=set)
    track_files: Set[str] = field(default_factory=set)
    preserved_dirs: Set[str] = field(default_factory=set)
    max_workers: int = 8
    
    def __post_init__(self):
        """Валидация конфигурации"""
        self.src = self.src.resolve()
        self.dst = self.dst.resolve()
        
        if not self.src.exists():
            raise ValueError(f"Source path does not exist: {self.src}")
            
        if not self.src.is_dir():
            raise ValueError(f"Source path is not a directory: {self.src}")
            
        if self.directory_priority not in ["include", "track"]:
            raise ValueError("directory_priority must be 'include' or 'track'")
            
        self.dst.mkdir(parents=True, exist_ok=True)
        
        # Проверка конфликтов
        self.check_conflicts()
    
    def check_conflicts(self):
        """Проверка конфликтующих правил"""
        common_dirs = self.include_dirs & self.exclude_dirs
        if common_dirs:
            logger.warning(f"Directories both included and excluded: {common_dirs}")
        
        common_files = self.include_files & self.exclude_files
        if common_files:
            logger.warning(f"Files both included and excluded: {common_files}")

class AxiomaticBackupSystem:
    """Аксиоматическая система бэкапа"""
    
    def __init__(self, cfg: BackupConfig):
        self.cfg = cfg
        self.all_files: Set[Path] = set()
        self.tracked_files: Set[Path] = set()
        self.mirror_state: Dict[str, Dict] = {}
        self.tracked_new_files: Set[Path] = set()
        self.tracked_changed_files: Set[Path] = set()
        self.tracked_deleted_files: Set[Path] = set()
        self.load_mirror_state()

    def load_mirror_state(self):
        """Загрузка состояния mirror"""
        mirror_file = self.cfg.dst / "mirror.json"
        if mirror_file.exists():
            try:
                with open(mirror_file, 'r', encoding='utf-8') as f:
                    self.mirror_state = json.load(f)
                logger.info(f"Loaded mirror state with {len(self.mirror_state)} files")
            except Exception as e:
                logger.error(f"Error loading mirror state: {e}")
                self.mirror_state = {}
        else:
            logger.info("No existing mirror state found")

    def save_mirror_state(self):
        """Сохранение состояния mirror"""
        mirror_file = self.cfg.dst / "mirror.json"
        temp_file = self.cfg.dst / "mirror.json.tmp"
        
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.mirror_state, f, indent=2, ensure_ascii=False)
            temp_file.replace(mirror_file)
            logger.info(f"Mirror state saved with {len(self.mirror_state)} files")
        except Exception as e:
            logger.error(f"Error saving mirror state: {e}")
            if temp_file.exists():
                temp_file.unlink()

    def build_file_sets(self):
        """Построение множеств файлов с учетом приоритета директорий"""
        logger.info("Building file sets...")
        
        # 1. Формируем множества директорий
        include_dirs = expand_directory_patterns(self.cfg.src, list(self.cfg.include_dirs))
        track_dirs = expand_directory_patterns(self.cfg.src, list(self.cfg.track_dirs))
        exclude_dirs = expand_directory_patterns(self.cfg.src, list(self.cfg.exclude_dirs))
        
        logger.info(f"Included directories: {len(include_dirs)}")
        logger.info(f"Tracked directories: {len(track_dirs)}")
        logger.info(f"Excluded directories: {len(exclude_dirs)}")
        
        # 2. Сканируем все директории
        all_scanned_files = set()
        file_to_dir_type = {}  # Для каждого файла сохраняем тип директории, в которой он находится
        
        # Сначала сканируем include_dirs
        for dir_path in include_dirs:
            files_in_dir = scan_directory_recursive(dir_path, exclude_dirs)
            all_scanned_files.update(files_in_dir)
            for file_path in files_in_dir:
                file_to_dir_type[file_path] = 'include'
        
        # Затем сканируем track_dirs, но переопределяем тип для файлов, которые уже есть в include_dirs
        for dir_path in track_dirs:
            files_in_dir = scan_directory_recursive(dir_path, exclude_dirs)
            for file_path in files_in_dir:
                if file_path in file_to_dir_type:
                    # Файл уже есть в include_dirs, проверяем приоритет
                    if self.cfg.directory_priority == "include":
                        # Приоритет include - оставляем как include
                        pass
                    else:
                        # Приоритет track - меняем на track
                        file_to_dir_type[file_path] = 'track'
                else:
                    # Файла нет в include_dirs, добавляем как track
                    file_to_dir_type[file_path] = 'track'
                    all_scanned_files.add(file_path)
        
        # 3. Разделяем файлы по типам
        files_from_include_dirs = {f for f, t in file_to_dir_type.items() if t == 'include'}
        files_from_track_dirs = {f for f, t in file_to_dir_type.items() if t == 'track'}
        
        logger.info(f"Files from include directories: {len(files_from_include_dirs)}")
        logger.info(f"Files from track directories: {len(files_from_track_dirs)}")
        
        # 4. Получаем файлы из шаблонов
        include_files = expand_file_patterns(self.cfg.src, list(self.cfg.include_files))
        track_files = expand_file_patterns(self.cfg.src, list(self.cfg.track_files))
        
        # 5. Применяем приоритет include над track для файлов
        track_files = track_files - include_files
        
        # 6. Применяем exclude_files только к файлам из директорий
        if self.cfg.exclude_files:
            excluded_count = 0
            filtered_files_from_include_dirs = set()
            for file_path in files_from_include_dirs:
                if is_file_excluded(file_path, list(self.cfg.exclude_files), self.cfg.src):
                    excluded_count += 1
                else:
                    filtered_files_from_include_dirs.add(file_path)
            
            filtered_files_from_track_dirs = set()
            for file_path in files_from_track_dirs:
                if is_file_excluded(file_path, list(self.cfg.exclude_files), self.cfg.src):
                    excluded_count += 1
                else:
                    filtered_files_from_track_dirs.add(file_path)
            
            logger.info(f"Excluded {excluded_count} files from directories by exclude patterns")
        else:
            filtered_files_from_include_dirs = files_from_include_dirs
            filtered_files_from_track_dirs = files_from_track_dirs
        
        # 7. Объединение множеств
        self.all_files = (
            filtered_files_from_include_dirs | 
            filtered_files_from_track_dirs | 
            include_files | 
            track_files
        )
        
        self.tracked_files = (
            filtered_files_from_track_dirs | 
            track_files
        ) & self.all_files
        
        logger.info(f"All files: {len(self.all_files)}")
        logger.info(f"Tracked files: {len(self.tracked_files)}")

    def get_changes(self) -> Tuple[Set[Path], Set[Path], Set[Path]]:
        """Определение изменений для track файлов"""
        current_tracked = self.tracked_files
        
        # Файлы, которые были track в mirror_state
        previous_tracked = set()
        for rel_path_str, info in self.mirror_state.items():
            if info.get('tracked', False):
                absolute_path = self.cfg.src / rel_path_str
                previous_tracked.add(absolute_path)
        
        # Удаленные track файлы: были track, но теперь отсутствуют в all_files
        deleted_files = previous_tracked - self.all_files
        
        # Новые track файлы: сейчас track, но не были в предыдущем состоянии
        new_files = current_tracked - previous_tracked
        
        # Измененные track файлы: общие файлы с измененными метаданными
        common_files = current_tracked & previous_tracked
        changed_files = set()
        for file_path in common_files:
            rel_path = get_relative_path_cached(file_path, self.cfg.src)
            current_size, current_mtime = get_file_metadata_cached(file_path)
            stored_meta = self.mirror_state.get(str(rel_path), {})
            stored_size = stored_meta.get('size', 0)
            stored_mtime = stored_meta.get('mtime', 0)
            
            # Проверяем изменение размера или времени модификации (разница > 1 секунды)
            if (stored_size != current_size or 
                abs(stored_mtime - current_mtime) > 1.0):
                changed_files.add(file_path)
        
        logger.info(f"Changes detected: {len(new_files)} new, {len(changed_files)} changed, {len(deleted_files)} deleted")
        return new_files, changed_files, deleted_files

    def safe_copy(self, src: Path, dst: Path) -> bool:
        """Безопасное копирование файла"""
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return True
        except Exception as e:
            logger.error(f"Copy failed {src} -> {dst}: {e}")
            return False

    def create_increment_metadata(self, backup_dir: Path, timestamp: str, 
                                new_files: Set[Path], changed_files: Set[Path], 
                                deleted_files: Set[Path]):
        """Создает метаданные для инкремента"""
        metadata = {
            "version": "1.0",
            "backup_type": "incremental",
            "timestamp": datetime.now().isoformat(),
            "backup_name": f"backup_{timestamp}",
            "file_catalog": {},
            "summary": {
                "new_or_changed_tracked": len(new_files) + len(changed_files),
                "deleted_tracked": len(deleted_files)
            }
        }
        
        # Добавляем информацию о файлах
        for file_path in new_files | changed_files:
            rel_path = get_relative_path_cached(file_path, self.cfg.src)
            size, mtime = get_file_metadata_cached(file_path)
            metadata["file_catalog"][str(rel_path)] = {
                "size": size,
                "mtime": mtime,
                "category": "tracked"
            }
        
        for file_path in deleted_files:
            rel_path = get_relative_path_cached(file_path, self.cfg.src)
            # Для удаленных файлов берем информацию из mirror_state
            if str(rel_path) in self.mirror_state:
                stored_meta = self.mirror_state[str(rel_path)]
                metadata["file_catalog"][str(rel_path)] = {
                    "size": stored_meta.get('size', 0),
                    "mtime": stored_meta.get('mtime', 0),
                    "category": "deleted"
                }
        
        # Переименовываем meta.json в backup_{timestamp}.json
        metadata_file = backup_dir / f"backup_{timestamp}.json"
        try:
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            logger.info(f"Backup metadata saved to {metadata_file}")
        except Exception as e:
            logger.error(f"Error saving metadata: {e}")

    def execute_backup(self) -> Dict[str, Any]:
        """Выполнение бэкапа согласно аксиоматическому алгоритму"""
        start_time = time.time()
        
        # Строим множества файлов
        self.build_file_sets()
        
        # Если нет файлов для бэкапа, выходим
        if not self.all_files:
            logger.warning("No files to backup")
            return {
                "total_files": 0,
                "tracked_files": 0,
                "new_files": 0,
                "changed_files": 0,
                "deleted_files": 0,
                "backup_time": time.time() - start_time
            }
        
        # Создаем/проверяем mirror директорию
        mirror_dir = self.cfg.dst / "mirror"
        mirror_dir.mkdir(parents=True, exist_ok=True)
        
        # Определяем изменения для track файлов
        new_files, changed_files, deleted_files = self.get_changes()
        
        # Создаем инкремент только если есть изменения в track файлах
        if new_files or changed_files or deleted_files:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = self.cfg.dst / f"backup_{timestamp}"
            backup_dir.mkdir(parents=True, exist_ok=True)
            
            # 1. Обрабатываем удаленные track файлы: создаем hardlink в deleted инкремента
            if deleted_files:
                deleted_dir = backup_dir / "deleted"
                deleted_dir.mkdir(parents=True, exist_ok=True)
                
                for file_path in deleted_files:
                    rel_path = get_relative_path_cached(file_path, self.cfg.src)
                    mirror_path = mirror_dir / rel_path
                    increment_path = deleted_dir / rel_path
                    
                    if mirror_path.exists():
                        create_hardlink_or_copy(mirror_path, increment_path)
            
            # 2. Удаляем из mirror файлы, которых нет в all_files
            files_to_remove_from_mirror = set()
            for rel_path_str in list(self.mirror_state.keys()):
                mirror_file_path = mirror_dir / rel_path_str
                if not mirror_file_path.exists():
                    continue
                absolute_path = self.cfg.src / rel_path_str
                if absolute_path not in self.all_files:
                    files_to_remove_from_mirror.add(mirror_file_path)
            
            for mirror_file_path in files_to_remove_from_mirror:
                try:
                    mirror_file_path.unlink()
                    logger.debug(f"Removed from mirror: {mirror_file_path}")
                except Exception as e:
                    logger.error(f"Error removing file from mirror: {e}")
            
            # 3. Копируем новые/измененные файлы в mirror (многопоточное копирование)
            files_to_copy_to_mirror = set()
            for file_path in self.all_files:
                rel_path = get_relative_path_cached(file_path, self.cfg.src)
                mirror_path = mirror_dir / rel_path
                
                # Проверяем, нужно ли копировать файл
                if not mirror_path.exists():
                    files_to_copy_to_mirror.add((file_path, mirror_path))
                else:
                    # Проверяем, изменился ли файл
                    current_size, current_mtime = get_file_metadata_cached(file_path)
                    mirror_size, mirror_mtime = get_file_metadata_cached(mirror_path)
                    
                    if (current_size != mirror_size or 
                        abs(current_mtime - mirror_mtime) > 1.0):
                        files_to_copy_to_mirror.add((file_path, mirror_path))
            
            # Многопоточное копирование
            with ThreadPoolExecutor(max_workers=self.cfg.max_workers) as executor:
                future_to_copy = {
                    executor.submit(self.safe_copy, src, dst): (src, dst) 
                    for src, dst in files_to_copy_to_mirror
                }
                
                for future in as_completed(future_to_copy):
                    src, dst = future_to_copy[future]
                    try:
                        success = future.result()
                        if not success:
                            logger.error(f"Failed to copy {src} to {dst}")
                    except Exception as e:
                        logger.error(f"Exception during copy {src} to {dst}: {e}")
            
            # 4. Обрабатываем новые/измененные track файлы: создаем hardlink в track инкремента
            if new_files or changed_files:
                track_dir = backup_dir / "track"
                track_dir.mkdir(parents=True, exist_ok=True)
                
                for file_path in new_files | changed_files:
                    rel_path = get_relative_path_cached(file_path, self.cfg.src)
                    mirror_path = mirror_dir / rel_path
                    increment_path = track_dir / rel_path
                    
                    if mirror_path.exists():
                        create_hardlink_or_copy(mirror_path, increment_path)
            
            # 5. Проверяем, не пуст ли инкремент
            if not any(backup_dir.iterdir()):
                shutil.rmtree(backup_dir, ignore_errors=True)
                logger.info(f"Removed empty backup directory: {backup_dir}")
            else:
                # Обновляем состояние mirror
                self.update_mirror_state()
                self.save_mirror_state()
                
                # Создаем метаданные инкремента
                self.create_increment_metadata(backup_dir, timestamp, new_files, changed_files, deleted_files)
                logger.info(f"Created increment: {backup_dir}")
        else:
            logger.info("No changes in tracked files, skipping increment creation")
        
        # Если нет инкремента, но есть изменения в include файлах, мы все равно обновляем mirror
        # Находим файлы, которые нужно обновить в mirror
        files_to_update = set()
        for file_path in self.all_files:
            rel_path = get_relative_path_cached(file_path, self.cfg.src)
            mirror_path = mirror_dir / rel_path
            
            # Проверяем, нужно ли копировать файл
            if not mirror_path.exists():
                files_to_update.add((file_path, mirror_path))
            else:
                # Проверяем, изменился ли файл
                current_size, current_mtime = get_file_metadata_cached(file_path)
                mirror_size, mirror_mtime = get_file_metadata_cached(mirror_path)
                
                if (current_size != mirror_size or 
                    abs(current_mtime - mirror_mtime) > 1.0):
                    files_to_update.add((file_path, mirror_path))
        
        if files_to_update:
            # Многопоточное копирование
            with ThreadPoolExecutor(max_workers=self.cfg.max_workers) as executor:
                future_to_copy = {
                    executor.submit(self.safe_copy, src, dst): (src, dst) 
                    for src, dst in files_to_update
                }
                
                for future in as_completed(future_to_copy):
                    src, dst = future_to_copy[future]
                    try:
                        success = future.result()
                        if not success:
                            logger.error(f"Failed to copy {src} to {dst}")
                    except Exception as e:
                        logger.error(f"Exception during copy {src} to {dst}: {e}")
            
            # Обновляем mirror_state
            self.update_mirror_state()
            self.save_mirror_state()
        
        logger.info(f"Backup completed in {time.time() - start_time:.2f}s")
        return {
            "total_files": len(self.all_files),
            "tracked_files": len(self.tracked_files),
            "new_files": len(new_files),
            "changed_files": len(changed_files),
            "deleted_files": len(deleted_files),
            "backup_time": time.time() - start_time
        }

    def update_mirror_state(self):
        """Обновление состояния mirror для всех файлов"""
        new_mirror_state = {}
        
        for file_path in self.all_files:
            try:
                rel_path = get_relative_path_cached(file_path, self.cfg.src)
                size, mtime = get_file_metadata_cached(file_path)
                is_tracked = file_path in self.tracked_files
                
                new_mirror_state[str(rel_path)] = {
                    'size': size,
                    'mtime': mtime,
                    'tracked': is_tracked
                }
            except Exception as e:
                logger.warning(f"Error updating mirror state for {file_path}: {e}")
        
        self.mirror_state = new_mirror_state
        logger.info(f"Mirror state updated with {len(self.mirror_state)} files")

# --- Функции для работы с конфигурацией ---

def load_config(config_file: Path) -> BackupConfig:
    """Загрузка конфигурации из JSON файла"""
    if not config_file.exists():
        # Создаем конфигурацию по умолчанию
        default_config = {
            "src": str(Path.home() / "test_data"),
            "dst": str(Path.home() / "backups"),
            "directory_priority": "track",
            "include_dirs": ["documents", "photos"],
            "exclude_dirs": ["temp", "cache"],
            "include_files": ["*.txt", "*.pdf", "*.jpg", "*.png"],
            "exclude_files": ["*.tmp", "*.log"],
            "track_dirs": ["important"],
            "track_files": ["*.important"],
            "preserved_dirs": [".git", "node_modules"],
            "max_workers": 4
        }
        
        with open(config_file, 'w') as f:
            json.dump(default_config, f, indent=2)
        logger.info(f"Created default config: {config_file}")
        logger.info("Please edit the config file and run again")
        sys.exit(0)
    
    with open(config_file, 'r', encoding='utf-8') as f:
        config_data = json.load(f)
    
    return BackupConfig(
        src=Path(config_data["src"]),
        dst=Path(config_data["dst"]),
        directory_priority=config_data.get("directory_priority", "track"),
        include_dirs=set(config_data["include_dirs"]),
        exclude_dirs=set(config_data["exclude_dirs"]),
        include_files=set(config_data["include_files"]),
        exclude_files=set(config_data["exclude_files"]),
        track_dirs=set(config_data["track_dirs"]),
        track_files=set(config_data["track_files"]),
        preserved_dirs=set(config_data["preserved_dirs"]),
        max_workers=config_data.get("max_workers", 4)
    )

# --- Основная функция ---

def main():
    """Основная функция"""
    parser = argparse.ArgumentParser(description="Axiomatic Backup System")
    parser.add_argument("--config", "-c", default="backup_config.json", help="Configuration file")
    parser.add_argument("--debug", "-d", action="store_true", help="Enable debug logging")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Dry run without actual backup")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        # Загрузка конфигурации
        cfg = load_config(Path(args.config))
        
        if args.dry_run:
            logger.info("Dry run mode - no backup will be performed")
            # Создаем систему бэкапа только для построения множеств
            backup_system = AxiomaticBackupSystem(cfg)
            backup_system.build_file_sets()
            logger.info(f"Would backup {len(backup_system.all_files)} files")
            logger.info(f"Would track {len(backup_system.tracked_files)} files")
            return
        
        # Создание системы бэкапа
        backup_system = AxiomaticBackupSystem(cfg)
        
        # Выполнение бэкапа
        stats = backup_system.execute_backup()
        
        # Вывод статистики
        logger.info("=== BACKUP STATISTICS ===")
        for key, value in stats.items():
            logger.info(f"{key}: {value}")
                
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
    
