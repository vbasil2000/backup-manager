#!/usr/bin/env python3
"""
UTILITY FOR WORKING WITH INCREMENTAL BACKUPS
With improved readable output
"""

import json
import argparse
import shutil
import sys
import re
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Any, Tuple
import fnmatch
import logging

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BackupManager:
    def __init__(self, backup_dir: Path):
        self.backup_dir = Path(backup_dir)
        if not self.backup_dir.exists():
            raise ValueError(f"Backup directory does not exist: {backup_dir}")
    
    def format_size(self, size_bytes: int) -> str:
        """Format file size into human-readable form"""
        if size_bytes == 0:
            return "0 B"
        
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        i = 0
        size = float(size_bytes)
        
        while size >= 1024 and i < len(units) - 1:
            size /= 1024.0
            i += 1
        
        return f"{size:.1f} {units[i]}"
    
    def format_timestamp_display(self, timestamp: str) -> str:
        """Format timestamp for display (date and time)"""
        try:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            return dt.strftime("%Y-%m-%d %H:%M")
        except:
            return timestamp
    
    def find_all_backups(self) -> List[Path]:
        """Find all backup folders of the new format"""
        backups = []
        for item in self.backup_dir.iterdir():
            if item.is_dir() and item.name.startswith('backup_'):
                if (item / "track").exists() or (item / "deleted").exists():
                    backups.append(item)
        return sorted(backups, key=lambda x: x.stat().st_mtime)
    
    def load_metadata(self, backup_path: Path) -> Optional[Dict]:
        """Load metadata of a backup in new format"""
        metadata_file = backup_path / f"{backup_path.name}.json"
        if not metadata_file.exists():
            return None
        
        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Error loading metadata for {backup_path.name}: {e}")
            return None
    
    def recreate_metadata(self, backup_path: Path, force: bool = False) -> bool:
        """Recreate metadata for a new-format backup"""
        metadata_file = backup_path / f"{backup_path.name}.json"
        
        if metadata_file.exists() and not force:
            logger.info(f"Metadata already exists for {backup_path.name}, use --force to overwrite")
            return False
        
        file_catalog = {}
        statistics = {"total_files": 0, "total_size": 0}
        
        for category in ["track", "deleted"]:
            category_dir = backup_path / category
            if category_dir.exists():
                for file_path in category_dir.rglob('*'):
                    if file_path.is_file():
                        try:
                            rel_path = str(file_path.relative_to(category_dir))
                            
                            file_catalog[rel_path] = {
                                "size": file_path.stat().st_size,
                                "mtime": file_path.stat().st_mtime,
                                "mtime_iso": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
                                "mtime_date": datetime.fromtimestamp(file_path.stat().st_mtime).strftime("%Y-%m-%d"),
                                "category": category,
                                "backup_path": f"{category}/{rel_path}"
                            }
                            
                            statistics["total_files"] += 1
                            statistics["total_size"] += file_path.stat().st_size
                        except Exception as e:
                            logger.warning(f"Error processing file {file_path}: {e}")
        
        track_count = sum(1 for info in file_catalog.values() if info["category"] == "track")
        deleted_count = sum(1 for info in file_catalog.values() if info["category"] == "deleted")
        
        metadata = {
            "version": "1.0",
            "backup_type": "incremental",
            "backup_timestamp": datetime.fromtimestamp(backup_path.stat().st_ctime).isoformat(),
            "backup_name": backup_path.name,
            "backup_path": str(backup_path),
            "file_catalog": file_catalog,
            "summary": {
                "new_or_changed_tracked": track_count,
                "deleted_tracked": deleted_count,
                "total_operations": track_count + deleted_count
            },
            "statistics": statistics,
            "recreated": True,
            "recreated_at": datetime.now().isoformat()
        }
        
        try:
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            logger.info(f"Metadata recreated for {backup_path.name}")
            return True
        except IOError as e:
            logger.error(f"Error saving metadata for {backup_path.name}: {e}")
            return False
    
    def recreate_all_metadata(self, force: bool = False):
        """Recreate metadata for all incremental backups of the new format"""
        backups = self.find_all_backups()
        logger.info(f"Found {len(backups)} backups to process")
        
        success_count = 0
        for backup_path in backups:
            if self.recreate_metadata(backup_path, force):
                success_count += 1
        
        logger.info(f"Successfully recreated metadata for {success_count}/{len(backups)} backups")
    
    def _compile_regex_patterns(self, patterns: List[str]) -> re.Pattern:
        """Compile file masks into a single regex for faster search"""
        regex_parts = []
        for pattern in patterns:
            # Escape special characters except * and ?
            escaped = re.escape(pattern)
            escaped = escaped.replace(r'\*', '.*').replace(r'\?', '.')
            regex_parts.append(f"^{escaped}$")
        
        combined = '|'.join(regex_parts)
        return re.compile(combined)
    
    def _preprocess_patterns(self, patterns: List[str]) -> List[str]:
        """Preprocess patterns"""
        processed = []
        for pattern in patterns:
            pattern = pattern.strip()
            if not any(c in pattern for c in '*?[]'):
                pattern = f"*{pattern}*"
            processed.append(pattern)
        return processed
    
    def _validate_time_filter(self, time_filter: str) -> bool:
        """Validate time filter"""
        try:
            if not time_filter:
                return True
                
            if '..' in time_filter:
                start, end = time_filter.split('..', 1)
                datetime.strptime(start, "%Y-%m-%d")
                datetime.strptime(end, "%Y-%m-%d")
                return True
                
            elif time_filter.startswith(('<', '>')):
                date_part = time_filter[1:]
                datetime.strptime(date_part, "%Y-%m-%d")
                return True
                
            else:
                datetime.strptime(time_filter, "%Y-%m-%d")
                return True
                
        except ValueError:
            print(f"⚠️  Invalid date format: {time_filter}")
            return False
    
    def _check_time_filter(self, file_mtime: float, time_filter: str) -> bool:
        """Check if file matches time filter"""
        if not time_filter:
            return True
            
        try:
            file_dt = datetime.fromtimestamp(file_mtime)
            file_date_obj = file_dt.date()
            
            if re.match(r'^\d{4}-\d{2}-\d{2}$', time_filter):
                target_dt = datetime.strptime(time_filter, "%Y-%m-%d")
                return file_date_obj == target_dt.date()
            
            elif time_filter.startswith('<'):
                target_date = time_filter[1:]
                if re.match(r'^\d{4}-\d{2}-\d{2}$', target_date):
                    target_dt = datetime.strptime(target_date, "%Y-%m-%d")
                    return file_date_obj <= target_dt.date()
            
            elif time_filter.startswith('>'):
                target_date = time_filter[1:]
                if re.match(r'^\d{4}-\d{2}-\d{2}$', target_date):
                    target_dt = datetime.strptime(target_date, "%Y-%m-%d")
                    return file_date_obj >= target_dt.date()
            
            elif '..' in time_filter:
                start_date, end_date = time_filter.split('..', 1)
                if (re.match(r'^\d{4}-\d{2}-\d{2}$', start_date) and 
                    re.match(r'^\d{4}-\d{2}-\d{2}$', end_date)):
                    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
                    return start_dt.date() <= file_date_obj <= end_dt.date()
            
            return False
            
        except (ValueError, TypeError):
            return False
    
    def _check_size_filter(self, size: int, size_filter: str) -> bool:
        """Check if file matches size filter"""
        if not size_filter:
            return True
            
        try:
            if size_filter.startswith('>'):
                min_size = self._parse_size(size_filter[1:])
                return size > min_size
            elif size_filter.startswith('<'):
                max_size = self._parse_size(size_filter[1:])
                return size < max_size
            elif '-' in size_filter:
                min_str, max_str = size_filter.split('-', 1)
                min_size = self._parse_size(min_str)
                max_size = self._parse_size(max_str)
                return min_size <= size <= max_size
            else:
                target_size = self._parse_size(size_filter)
                return size == target_size
        except:
            return False
    
    def _parse_size(self, size_str: str) -> int:
        """Parse size string with suffixes"""
        size_str = size_str.strip().upper()
        if size_str.endswith('K'):
            return int(float(size_str[:-1]) * 1024)
        elif size_str.endswith('M'):
            return int(float(size_str[:-1]) * 1024 * 1024)
        elif size_str.endswith('G'):
            return int(float(size_str[:-1]) * 1024 * 1024 * 1024)
        else:
            return int(size_str)
    
    def search_files(self, patterns: List[str], size_filter: Optional[str] = None,
                    time_filter: Optional[str] = None, path_prefix: Optional[str] = None,
                    last_backups: Optional[int] = None) -> Dict:
        """Intelligent search for files in backups"""
        
        processed_patterns = self._preprocess_patterns(patterns)
        
        if time_filter and not self._validate_time_filter(time_filter):
            print("⚠️  Search will continue without time filter")
            time_filter = None
        
        # Compile regex for fast search
        regex = self._compile_regex_patterns(processed_patterns)
        
        results = {}
        all_backups = self.find_all_backups()
        
        if last_backups:
            backups = all_backups[-last_backups:]
        else:
            backups = all_backups
        
        for backup_path in backups:
            metadata = self.load_metadata(backup_path)
            if not metadata or "file_catalog" not in metadata:
                continue
            
            backup_results = []
            for file_path, file_info in metadata["file_catalog"].items():
                # Backward compatibility
                file_info.setdefault("backup_path", f"{file_info.get('category', 'track')}/{file_path}")
                file_info.setdefault("mtime_iso", datetime.fromtimestamp(file_info["mtime"]).isoformat())
                file_info.setdefault("mtime_date", datetime.fromtimestamp(file_info["mtime"]).strftime("%Y-%m-%d"))
                file_info.setdefault("filename", Path(file_path).name)
                
                # Filters
                if path_prefix and not file_path.startswith(path_prefix):
                    continue
                if size_filter and not self._check_size_filter(file_info["size"], size_filter):
                    continue
                if time_filter and not self._check_time_filter(file_info["mtime"], time_filter):
                    continue
                
                # Regex search
                if not (regex.search(file_path) or regex.search(file_info["filename"])):
                    continue
                
                backup_results.append({
                    "path": file_path,
                    "size": file_info["size"],
                    "mtime": file_info["mtime"],
                    "mtime_iso": file_info["mtime_iso"],
                    "mtime_date": file_info["mtime_date"],
                    "category": file_info.get("category", "track"),
                    "backup_path": file_info["backup_path"],
                    "filename": file_info["filename"]
                })
            
            if backup_results:
                # Sort files by name
                backup_results.sort(key=lambda x: x["filename"])
                results[backup_path.name] = {
                    "backup_path": str(backup_path),
                    "backup_timestamp": metadata.get('backup_timestamp', ''),
                    "files": backup_results,
                    "total_files": len(backup_results)
                }
        
        return results
    def _print_search_stats(self, results: Dict):
        """Print search statistics"""
        total_files = sum(len(b["files"]) for b in results.values())
        total_size = sum(f["size"] for b in results.values() for f in b["files"])
        
        print(f"\nSearch results:")
        print(f"   Backups: {len(results)}")
        print(f"   Files: {total_files}")
        print(f"   Size: {self.format_size(total_size)}")
        
        tracked = sum(1 for b in results.values() for f in b["files"] if f.get("category") in ["track", "tracked"])
        deleted = sum(1 for b in results.values() for f in b["files"] if f.get("category") in ["delete", "deleted"])
        print(f"   Tracked: {tracked}, Deleted: {deleted}")
    
    def print_results(self, results: Dict):
        """Improved output grouped by directories with aligned table"""
        if not results:
            print("🤷 No files found")
            return

        for backup_name, backup_info in results.items():
            display_timestamp = self.format_timestamp_display(backup_info['backup_timestamp'])
            print(f"\n📦 {backup_name} ({display_timestamp})")

            files = backup_info["files"]
            if not files:
                print("  (empty)")
                continue

            # Group files by directory
            files_by_dir = {}
            for file_info in files:
                full_path = file_info['path']
                dir_path = str(Path(full_path).parent)
                file_name = Path(full_path).name
                
                if dir_path not in files_by_dir:
                    files_by_dir[dir_path] = []
                files_by_dir[dir_path].append(file_info)

            # Sort directories alphabetically
            sorted_dirs = sorted(files_by_dir.keys())
            
            for dir_path in sorted_dirs:
                dir_files = files_by_dir[dir_path]
                
                # Directory header
                print(f"\n  📁 {dir_path}/")
                
                # Column headers with fixed width
                print("     {:<28} {:>10} {:>10} {:>10}".format(
                    "File name", "Size", "Date", "Status"
                ))
                print("     " + "-"*30 + " " + "-"*10 + " " + "-"*12 + " " + "-"*6)
                
                for file_info in dir_files:
                    size_str = self.format_size(file_info["size"])
                    category = file_info.get("category", "track")
                    mtime_date = file_info.get("mtime_date", 
                        datetime.fromtimestamp(file_info["mtime"]).strftime("%Y-%m-%d"))
                    
                    # Color and status
                    if category in ["track", "tracked"]:
                        color_start, status = "\033[92m", "✅"
                    else:
                        color_start, status = "\033[91m", "❌"
                    color_end = "\033[0m"
                    
                    file_name = Path(file_info['path']).name
                    name_part, ext_part = Path(file_name).stem, Path(file_name).suffix
                    
                    max_name_length = 25
                    if len(name_part) > max_name_length:
                        display_name = f"{name_part[:max_name_length-3]}...{ext_part}"
                    else:
                        display_name = file_name
                    
                    display_name = display_name.ljust(30)
                    colored_name = f"{color_start}{display_name}{color_end}"
                    
                    print("     {:<30} {:>9} {:>12} {:>4}".format(
                        colored_name, size_str, mtime_date, status
                    ))
    
    def delete_files_from_backup(self, backup_name: str, file_patterns: List[str], dry_run: bool = True):
        """Delete files from a new-format incremental backup"""
        backup_path = self.backup_dir / backup_name
        if not backup_path.exists():
            logger.error(f"Backup {backup_name} not found")
            return False
        
        metadata = self.load_metadata(backup_path)
        if not metadata:
            logger.error(f"Metadata not found for {backup_name}")
            return False
        
        processed_patterns = self._preprocess_patterns(file_patterns)
        regex = self._compile_regex_patterns(processed_patterns)
        
        files_to_delete = []
        for file_path, file_info in metadata["file_catalog"].items():
            if regex.search(file_path):
                files_to_delete.append((file_path, file_info))
        
        if not files_to_delete:
            logger.info(f"No files matching patterns found in {backup_name}")
            return True
        
        logger.info(f"Found {len(files_to_delete)} files to delete from {backup_name}")
        
        if dry_run:
            logger.info("DRY RUN: Would delete files:")
            for file_path, file_info in files_to_delete:
                logger.info(f"  {file_path} ({file_info['category']})")
            return True
        
        deleted_count = 0
        for file_path, file_info in files_to_delete:
            try:
                backup_path_value = file_info.get("backup_path", f"{file_info.get('category', 'track')}/{file_path}")
                file_to_delete = backup_path / backup_path_value
                
                if file_to_delete.exists():
                    file_to_delete.unlink()
                    logger.info(f"Deleted {file_path}")
                    deleted_count += 1
                
                if file_path in metadata["file_catalog"]:
                    del metadata["file_catalog"][file_path]
                
            except Exception as e:
                logger.error(f"Error deleting {file_path}: {e}")
        
        # Update statistics
        track_count = sum(1 for info in metadata["file_catalog"].values() if info.get("category") in ["track", "tracked"])
        deleted_count_remaining = sum(1 for info in metadata["file_catalog"].values() if info.get("category") in ["delete", "deleted"])
        
        metadata["summary"]["new_or_changed_tracked"] = track_count
        metadata["summary"]["deleted_tracked"] = deleted_count_remaining
        metadata["summary"]["total_operations"] = track_count + deleted_count_remaining
        
        metadata_file = backup_path / f"{backup_name}.json"
        try:
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            logger.info(f"Updated metadata for {backup_name}")
        except IOError as e:
            logger.error(f"Error saving updated metadata: {e}")
        
        logger.info(f"Successfully deleted {deleted_count} files from {backup_name}")
        return True
    
    def list_backups(self, detailed: bool = False):
        """List all backups with information"""
        backups = self.find_all_backups()
        
        if not backups:
            print("No backups found")
            return
        
        print(f"\nFound {len(backups)} backups:")
        
        for backup_path in backups:
            metadata = self.load_metadata(backup_path)
            if metadata:
                display_timestamp = self.format_timestamp_display(metadata.get('backup_timestamp', 'unknown'))
                print(f"\n{backup_path.name}:")
                print(f"  Time: {display_timestamp}")
                print(f"  Type: {metadata.get('backup_type', 'unknown')}")
                if "summary" in metadata:
                    summary = metadata["summary"]
                    print(f"  Tracked: {summary.get('new_or_changed_tracked', 0)} files")
                    print(f"  Deleted: {summary.get('deleted_tracked', 0)} files")
                    print(f"  Total operations: {summary.get('total_operations', 0)}")
                
                if detailed and "statistics" in metadata:
                    stats = metadata["statistics"]
                    size_str = self.format_size(stats.get('total_size', 0))
                    print(f"  Size: {size_str}")
                    print(f"  Files: {stats.get('total_files', 0)}")
            else:
                print(f"\n{backup_path.name}: (no metadata)")

def main():
    parser = argparse.ArgumentParser(description='Utility for managing incremental backups')
    parser.add_argument('backup_dir', help='Path to the backups directory')
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # LIST command
    list_parser = subparsers.add_parser('list', help='List all backups')
    list_parser.add_argument('--detailed', action='store_true', help='Show detailed info')
    
    # RECREATE command
    recreate_parser = subparsers.add_parser('recreate', help='Recreate metadata')
    recreate_parser.add_argument('--force', action='store_true', help='Overwrite existing metadata')
    recreate_parser.add_argument('--backup', help='Recreate metadata for a specific backup')
    
    # SEARCH command
    search_parser = subparsers.add_parser('search', help='Search files in backups')
    search_parser.add_argument('--mask', action='append', required=True, 
                              help='File mask (e.g. "*.txt", "test.py", "file")')
    search_parser.add_argument('--size', help='Size filter (e.g. ">100M", "<1G")')
    search_parser.add_argument('--time', help='Time filter (e.g. "2024-09-06", "<2024-09-06", ">2024-09-05", "2024-09-05..2024-09-06")')
    search_parser.add_argument('--path', help='Path prefix filter')
    search_parser.add_argument('--last-backups', type=int, help='Search only in last N backups')
    search_parser.add_argument('--json', action='store_true', help='Output in JSON format')
    
    # DELETE command
    delete_parser = subparsers.add_parser('delete', help='Delete files from a backup')
    delete_parser.add_argument('backup_name', help='Backup name to modify')
    delete_parser.add_argument('--mask', action='append', required=True, help='File mask for deletion')
    delete_parser.add_argument('--dry-run', action='store_true', help='Simulate deletion without changes')
    
    args = parser.parse_args()
    
    try:
        manager = BackupManager(args.backup_dir)
        
        if args.command == 'list':
            manager.list_backups(args.detailed)
            
        elif args.command == 'recreate':
            if args.backup:
                backup_path = Path(args.backup_dir) / args.backup
                if backup_path.exists():
                    manager.recreate_metadata(backup_path, args.force)
                else:
                    logger.error(f"Backup {args.backup} not found")
            else:
                manager.recreate_all_metadata(args.force)
        
        elif args.command == 'search':
            results = manager.search_files(
                args.mask, 
                args.size, 
                args.time, 
                args.path,
                args.last_backups
            )
            
            if args.json:
                print(json.dumps(results, indent=2, ensure_ascii=False))
            else:
                manager.print_results(results)
                if results:
                    manager._print_search_stats(results)
        
        elif args.command == 'delete':
            success = manager.delete_files_from_backup(args.backup_name, args.mask, args.dry_run)
            if not success:
                sys.exit(1)
                
        else:
            parser.print_help()
            
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()

