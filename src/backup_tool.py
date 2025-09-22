#!/usr/bin/env python3
"""
INCREMENTAL BACKUP EXPLORER UTILITY
Focused on search and analysis of backup contents
"""

import json
import argparse
import sys
import re
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Set, Any, Tuple
import fnmatch
import logging

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Color codes for terminal output
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

class BackupExplorer:
    def __init__(self, backup_dir: Path):
        self.backup_dir = Path(backup_dir)
        if not self.backup_dir.exists():
            raise ValueError(f"Backup directory does not exist: {backup_dir}")
        
        # Cache for metadata to avoid repeated file reads
        self.metadata_cache = {}
    
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
    
    def load_metadata(self, backup_path: Path, use_cache: bool = True) -> Optional[Dict]:
        """Load metadata of a backup in new format with caching"""
        backup_str = str(backup_path)
        if use_cache and backup_str in self.metadata_cache:
            return self.metadata_cache[backup_str]
        
        metadata_file = backup_path / f"{backup_path.name}.json"
        if not metadata_file.exists():
            return None
        
        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
                if use_cache:
                    self.metadata_cache[backup_str] = metadata
                return metadata
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Error loading metadata for {backup_path.name}: {e}")
            return None
    
    def clear_metadata_cache(self):
        """Clear the metadata cache"""
        self.metadata_cache = {}
    
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
            # Update cache
            self.metadata_cache[str(backup_path)] = metadata
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
                    "filename": file_info["filename"],
                    "full_backup_path": str(backup_path / file_info["backup_path"])
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
        
        print(f"\n{Colors.BOLD}Search results:{Colors.END}")
        print(f"   {Colors.CYAN}Backups:{Colors.END} {len(results)}")
        print(f"   {Colors.CYAN}Files:{Colors.END} {total_files}")
        print(f"   {Colors.CYAN}Size:{Colors.END} {self.format_size(total_size)}")
        
        tracked = sum(1 for b in results.values() for f in b["files"] if f.get("category") in ["track", "tracked"])
        deleted = sum(1 for b in results.values() for f in b["files"] if f.get("category") in ["delete", "deleted"])
        print(f"   {Colors.GREEN}Tracked:{Colors.END} {tracked}, {Colors.RED}Deleted:{Colors.END} {deleted}")
    
    def print_results(self, results: Dict, show_full_paths: bool = False):
        """Improved output grouped by directories with aligned table"""
        if not results:
            print("🤷 No files found")
            return

        for backup_name, backup_info in results.items():
            display_timestamp = self.format_timestamp_display(backup_info['backup_timestamp'])
            print(f"\n{Colors.BOLD}📦 {backup_name} ({display_timestamp}){Colors.END}")

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
                print(f"\n  {Colors.BLUE}📁 {dir_path}/{Colors.END}")
                
                # Column headers with fixed width
                if show_full_paths:
                    print("     {:<60} {:>10} {:>10} {:>10}".format(
                        "File path", "Size", "Date", "Status"
                    ))
                    print("     " + "-"*62 + " " + "-"*10 + " " + "-"*12 + " " + "-"*6)
                else:
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
                        color_start, status = Colors.GREEN, "✅"
                    else:
                        color_start, status = Colors.RED, "❌"
                    color_end = Colors.END
                    
                    if show_full_paths:
                        display_text = file_info['path']
                        max_length = 58
                    else:
                        file_name = Path(file_info['path']).name
                        name_part, ext_part = Path(file_name).stem, Path(file_name).suffix
                        max_length = 25
                        if len(name_part) > max_length:
                            display_text = f"{name_part[:max_length-3]}...{ext_part}"
                        else:
                            display_text = file_name
                    
                    display_text = display_text.ljust(max_length + 2)
                    colored_text = f"{color_start}{display_text}{color_end}"
                    
                    if show_full_paths:
                        print("     {:<60} {:>9} {:>12} {:>4}".format(
                            colored_text, size_str, mtime_date, status
                        ))
                    else:
                        print("     {:<30} {:>9} {:>12} {:>4}".format(
                            colored_text, size_str, mtime_date, status
                        ))
    
    def generate_restore_script(self, results: Dict, output_script: Path):
        """Generate a shell script to restore found files"""
        with open(output_script, 'w') as f:
            f.write("#!/bin/bash\n")
            f.write("# Auto-generated restore script\n")
            f.write("# Use: bash restore_files.sh /path/to/restore/destination\n")
            f.write("\n")
            f.write("DEST_DIR=\"$1\"\n")
            f.write("if [ -z \"$DEST_DIR\" ]; then\n")
            f.write("    echo \"Usage: $0 /path/to/restore/destination\"\n")
            f.write("    exit 1\n")
            f.write("fi\n")
            f.write("\n")
            f.write("mkdir -p \"$DEST_DIR\"\n")
            f.write("echo \"Restoring files to $DEST_DIR\"\n")
            f.write("\n")
            
            for backup_name, backup_info in results.items():
                backup_path = backup_info["backup_path"]
                for file_info in backup_info["files"]:
                    src_path = file_info["full_backup_path"]
                    dest_path = f"\"$DEST_DIR/{file_info['path']}\""
                    dest_dir = f"\"$DEST_DIR/{Path(file_info['path']).parent}\""
                    
                    f.write(f"mkdir -p {dest_dir} && ")
                    f.write(f"cp -p \"{src_path}\" {dest_path} && ")
                    f.write(f"echo \"Restored {file_info['path']}\"\n")
            
            f.write("\n")
            f.write("echo \"Restore completed\"\n")
        
        # Make script executable
        output_script.chmod(0o755)
        print(f"Generated restore script: {output_script}")
        print("Usage: bash restore_files.sh /path/to/restore/destination")

    def list_backups(self, detailed: bool = False):
        """List all backups with information"""
        backups = self.find_all_backups()
        
        if not backups:
            print("No backups found")
            return
        
        print(f"\n{Colors.BOLD}Found {len(backups)} backups:{Colors.END}")
        
        for backup_path in backups:
            metadata = self.load_metadata(backup_path)
            if metadata:
                display_timestamp = self.format_timestamp_display(metadata.get('backup_timestamp', 'unknown'))
                print(f"\n{Colors.BOLD}{backup_path.name}:{Colors.END}")
                print(f"  {Colors.CYAN}Time:{Colors.END} {display_timestamp}")
                print(f"  {Colors.CYAN}Type:{Colors.END} {metadata.get('backup_type', 'unknown')}")
                if "summary" in metadata:
                    summary = metadata["summary"]
                    print(f"  {Colors.GREEN}Tracked:{Colors.END} {summary.get('new_or_changed_tracked', 0)} files")
                    print(f"  {Colors.RED}Deleted:{Colors.END} {summary.get('deleted_tracked', 0)} files")
                    print(f"  {Colors.CYAN}Total operations:{Colors.END} {summary.get('total_operations', 0)}")
                
                if detailed and "statistics" in metadata:
                    stats = metadata["statistics"]
                    size_str = self.format_size(stats.get('total_size', 0))
                    print(f"  {Colors.CYAN}Size:{Colors.END} {size_str}")
                    print(f"  {Colors.CYAN}Files:{Colors.END} {stats.get('total_files', 0)}")
            else:
                print(f"\n{Colors.YELLOW}{backup_path.name}: (no metadata){Colors.END}")

def main():
    parser = argparse.ArgumentParser(description='Utility for exploring incremental backups')
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
    search_parser.add_argument('--full-paths', action='store_true', help='Show full file paths')
    search_parser.add_argument('--generate-script', help='Generate restore script to specified file')
    
    args = parser.parse_args()
    
    try:
        explorer = BackupExplorer(args.backup_dir)
        
        if args.command == 'list':
            explorer.list_backups(args.detailed)
            
        elif args.command == 'recreate':
            if args.backup:
                backup_path = Path(args.backup_dir) / args.backup
                if backup_path.exists():
                    explorer.recreate_metadata(backup_path, args.force)
                else:
                    logger.error(f"Backup {args.backup} not found")
            else:
                explorer.recreate_all_metadata(args.force)
        
        elif args.command == 'search':
            results = explorer.search_files(
                args.mask, 
                args.size, 
                args.time, 
                args.path,
                args.last_backups
            )
            
            if args.json:
                print(json.dumps(results, indent=2, ensure_ascii=False))
            else:
                explorer.print_results(results, args.full_paths)
                if results:
                    explorer._print_search_stats(results)
                    
                    # Generate restore script if requested
                    if args.generate_script:
                        explorer.generate_restore_script(results, Path(args.generate_script))
                
        else:
            parser.print_help()
            
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()
    
