"""
Module for handling daily archival of INGV graphs.

This module provides functionality to:
- Save daily PNG files in organized directory structure
- Automatically cleanup old archived files
- List and retrieve archived graphs
- Support compression for long-term storage
"""

import gzip
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any
import fcntl
import tempfile

logger = logging.getLogger(__name__)


class ArchiveManager:
    """Manages archival of INGV graphs with automatic cleanup and retrieval."""

    def __init__(
        self,
        base_path: Optional[str] = None,
        retention_days: Optional[int] = None,
    ):
        """
        Initialize the ArchiveManager.

        Args:
            base_path: Base directory for archives (default: data/archives)
            retention_days: Number of days to keep archives (default: 90)
        """
        self.base_path = Path(
            base_path or os.getenv("ARCHIVE_BASE_PATH", "data/archives")
        )
        self.retention_days = retention_days or int(
            os.getenv("ARCHIVE_RETENTION_DAYS", "90")
        )
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_archive_path(
        self, date: datetime, compressed: bool = False
    ) -> Path:
        """
        Get the archive path for a specific date.

        Args:
            date: Date for the archive
            compressed: Whether to use compressed (.gz) extension

        Returns:
            Path to the archive file
        """
        year = date.strftime("%Y")
        month = date.strftime("%m")
        day = date.strftime("%d")
        filename = f"etna_{date.strftime('%Y%m%d')}.png"
        if compressed:
            filename += ".gz"

        return self.base_path / year / month / day / filename

    def save_daily_graph(
        self,
        png_data: bytes,
        date: Optional[datetime] = None,
        compress: bool = False,
    ) -> Path:
        """
        Save daily graph using atomic file operations.

        Args:
            png_data: PNG image data as bytes
            date: Date for the archive (default: current UTC date)
            compress: Whether to compress the file

        Returns:
            Path to the saved archive file

        Raises:
            IOError: If file operations fail
        """
        if date is None:
            date = datetime.now(timezone.utc)
        elif date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)

        archive_path = self._get_archive_path(date, compressed=compress)
        archive_path.parent.mkdir(parents=True, exist_ok=True)

        # Use atomic write with temporary file
        temp_fd, temp_path = tempfile.mkstemp(
            dir=archive_path.parent, suffix=".tmp"
        )
        try:
            with os.fdopen(temp_fd, "wb") as f:
                # Acquire exclusive lock
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    if compress:
                        compressed_data = gzip.compress(png_data, compresslevel=6)
                        f.write(compressed_data)
                    else:
                        f.write(png_data)
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            # Atomic move
            shutil.move(temp_path, archive_path)
            logger.info(
                "Archived graph for %s to %s (compressed=%s, size=%d bytes)",
                date.strftime("%Y-%m-%d"),
                archive_path,
                compress,
                len(png_data),
            )
            return archive_path

        except Exception as e:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            logger.error("Failed to archive graph for %s: %s", date, e)
            raise

    def cleanup_old_archives(self) -> int:
        """
        Remove archives older than retention period.

        Returns:
            Number of files deleted

        Raises:
            IOError: If cleanup operations fail
        """
        if self.retention_days < 0:
            logger.info("Archive cleanup disabled (retention_days < 0)")
            return 0

        cutoff_date = datetime.now(timezone.utc) - timedelta(
            days=self.retention_days
        )
        deleted_count = 0

        try:
            # Walk through year/month/day structure
            for year_dir in sorted(self.base_path.iterdir()):
                if not year_dir.is_dir() or not year_dir.name.isdigit():
                    continue

                for month_dir in sorted(year_dir.iterdir()):
                    if not month_dir.is_dir() or not month_dir.name.isdigit():
                        continue

                    for day_dir in sorted(month_dir.iterdir()):
                        if not day_dir.is_dir() or not day_dir.name.isdigit():
                            continue

                        # Parse directory date
                        try:
                            dir_date = datetime.strptime(
                                f"{year_dir.name}{month_dir.name}{day_dir.name}",
                                "%Y%m%d",
                            ).replace(tzinfo=timezone.utc)
                        except ValueError:
                            logger.warning(
                                "Invalid date directory: %s", day_dir
                            )
                            continue

                        # Delete if older than cutoff
                        if dir_date < cutoff_date:
                            for file_path in day_dir.iterdir():
                                try:
                                    file_path.unlink()
                                    deleted_count += 1
                                    logger.debug(
                                        "Deleted old archive: %s", file_path
                                    )
                                except OSError as e:
                                    logger.error(
                                        "Failed to delete %s: %s",
                                        file_path,
                                        e,
                                    )

                            # Remove empty directories
                            try:
                                day_dir.rmdir()
                                # Try to remove month/year dirs if empty
                                try:
                                    month_dir.rmdir()
                                    try:
                                        year_dir.rmdir()
                                    except OSError:
                                        pass
                                except OSError:
                                    pass
                            except OSError as e:
                                logger.debug(
                                    "Could not remove directory %s: %s",
                                    day_dir,
                                    e,
                                )

            logger.info(
                "Cleanup completed: deleted %d archives older than %d days",
                deleted_count,
                self.retention_days,
            )
            return deleted_count

        except Exception as e:
            logger.error("Archive cleanup failed: %s", e)
            raise

    def list_archives(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        List available archived graphs.

        Args:
            start_date: Filter archives from this date (inclusive)
            end_date: Filter archives up to this date (inclusive)

        Returns:
            List of dictionaries with archive metadata
        """
        archives = []

        try:
            if not self.base_path.exists():
                return archives

            for year_dir in sorted(self.base_path.iterdir()):
                if not year_dir.is_dir() or not year_dir.name.isdigit():
                    continue

                for month_dir in sorted(year_dir.iterdir()):
                    if not month_dir.is_dir() or not month_dir.name.isdigit():
                        continue

                    for day_dir in sorted(month_dir.iterdir()):
                        if not day_dir.is_dir() or not day_dir.name.isdigit():
                            continue

                        # Parse directory date
                        try:
                            dir_date = datetime.strptime(
                                f"{year_dir.name}{month_dir.name}{day_dir.name}",
                                "%Y%m%d",
                            ).replace(tzinfo=timezone.utc)
                        except ValueError:
                            continue

                        # Apply date filters
                        if start_date and dir_date < start_date:
                            continue
                        if end_date and dir_date > end_date:
                            continue

                        # Find PNG files in this directory
                        for file_path in day_dir.iterdir():
                            if file_path.suffix in [".png", ".gz"]:
                                compressed = file_path.suffix == ".gz"
                                archives.append(
                                    {
                                        "date": dir_date.strftime("%Y-%m-%d"),
                                        "path": str(file_path),
                                        "size": file_path.stat().st_size,
                                        "compressed": compressed,
                                        "modified": datetime.fromtimestamp(
                                            file_path.stat().st_mtime,
                                            tz=timezone.utc,
                                        ).isoformat(),
                                    }
                                )

            return sorted(archives, key=lambda x: x["date"], reverse=True)

        except Exception as e:
            logger.error("Failed to list archives: %s", e)
            raise

    def get_archive(
        self, date: datetime, compressed: Optional[bool] = None
    ) -> Optional[bytes]:
        """
        Retrieve archived graph for a specific date.

        Args:
            date: Date of the archive to retrieve
            compressed: If True, look for .gz file; if False, .png; if None, try both

        Returns:
            PNG data as bytes, or None if not found

        Raises:
            IOError: If file read operations fail
        """
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)

        # Try to find the file
        paths_to_try = []
        if compressed is None:
            paths_to_try.append(self._get_archive_path(date, compressed=False))
            paths_to_try.append(self._get_archive_path(date, compressed=True))
        else:
            paths_to_try.append(
                self._get_archive_path(date, compressed=compressed)
            )

        for archive_path in paths_to_try:
            if archive_path.exists():
                try:
                    with open(archive_path, "rb") as f:
                        data = f.read()

                    # Decompress if needed
                    if archive_path.suffix == ".gz":
                        data = gzip.decompress(data)

                    logger.info(
                        "Retrieved archive for %s from %s",
                        date.strftime("%Y-%m-%d"),
                        archive_path,
                    )
                    return data

                except Exception as e:
                    logger.error(
                        "Failed to read archive %s: %s", archive_path, e
                    )
                    raise

        logger.warning(
            "Archive not found for date %s", date.strftime("%Y-%m-%d")
        )
        return None

    def archive_exists(self, date: datetime) -> bool:
        """
        Check if an archive exists for a specific date.

        Args:
            date: Date to check

        Returns:
            True if archive exists, False otherwise
        """
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)

        paths_to_check = [
            self._get_archive_path(date, compressed=False),
            self._get_archive_path(date, compressed=True),
        ]

        return any(path.exists() for path in paths_to_check)
