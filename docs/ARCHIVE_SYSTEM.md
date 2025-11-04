# Daily Backup System for INGV Graphs

## Overview

The EtnaMonitor v2 daily backup system provides automated archival, retrieval, and management of INGV seismic graphs. This system ensures data integrity and enables historical analysis while managing storage space efficiently.

## Features

- **Automated Daily Archival**: Automatically archives the last successful graph of each day
- **Organized Storage**: Files stored in hierarchical directory structure (`archives/YYYY/MM/DD/`)
- **Automatic Cleanup**: Removes archives older than configurable retention period
- **Compression Support**: Optional gzip compression for long-term storage
- **Atomic Operations**: Uses file locking and atomic writes to prevent data corruption
- **RESTful API**: Endpoints to list, retrieve, and analyze archived graphs

## Configuration

### Environment Variables

Add the following to your `.env` file:

```bash
# Archive settings
ARCHIVE_BASE_PATH=data/archives
ARCHIVE_RETENTION_DAYS=90
```

**Parameters:**
- `ARCHIVE_BASE_PATH`: Base directory for storing archives (default: `data/archives`)
- `ARCHIVE_RETENTION_DAYS`: Number of days to retain archives (default: `90`)
  - Set to `-1` to disable automatic cleanup

### Configuration in Code

The archive settings are automatically loaded from `config.py`:

```python
from config import Config

archive_base_path = Config.ARCHIVE_BASE_PATH
retention_days = Config.ARCHIVE_RETENTION_DAYS
```

## Usage

### Automatic Archival in etna_loop.py

The `etna_loop.py` script automatically archives graphs once per day:

```python
from backend.utils.archive import ArchiveManager

# Initialize archive manager
archive_manager = ArchiveManager()

# Archive is called after successful graph download
if scarica_grafico():
    aggiorna_log()
    archive_daily_graph()  # Saves and manages archives
```

### Manual Archival

You can manually archive a graph using the `ArchiveManager` class:

```python
from backend.utils.archive import ArchiveManager
from datetime import datetime

manager = ArchiveManager(
    base_path="data/archives",
    retention_days=90
)

# Save a graph
with open("grafici/etna_latest.png", "rb") as f:
    png_data = f.read()

archive_path = manager.save_daily_graph(
    png_data,
    date=datetime.now(),
    compress=False  # Set to True for gzip compression
)

print(f"Archived to: {archive_path}")
```

### Listing Archives

```python
from backend.utils.archive import ArchiveManager
from datetime import datetime, timedelta

manager = ArchiveManager()

# List all archives
archives = manager.list_archives()

# List archives within a date range
start_date = datetime.now() - timedelta(days=30)
archives = manager.list_archives(start_date=start_date)

for archive in archives:
    print(f"Date: {archive['date']}, Size: {archive['size']} bytes")
```

### Retrieving Archives

```python
from backend.utils.archive import ArchiveManager
from datetime import datetime

manager = ArchiveManager()

# Retrieve an archived graph
date = datetime(2025, 11, 4)
png_data = manager.get_archive(date)

if png_data:
    with open("retrieved_graph.png", "wb") as f:
        f.write(png_data)
```

### Cleanup Old Archives

```python
from backend.utils.archive import ArchiveManager

manager = ArchiveManager(retention_days=90)

# Remove archives older than 90 days
deleted_count = manager.cleanup_old_archives()
print(f"Deleted {deleted_count} old archives")
```

## API Endpoints

### List Archives

**Endpoint:** `GET /api/archives/list`

**Query Parameters:**
- `start_date` (optional): Filter archives from this date (format: `YYYY-MM-DD`)
- `end_date` (optional): Filter archives up to this date (format: `YYYY-MM-DD`)

**Example Request:**
```bash
curl "http://localhost:5000/api/archives/list?start_date=2025-11-01&end_date=2025-11-30"
```

**Example Response:**
```json
{
  "ok": true,
  "count": 3,
  "archives": [
    {
      "date": "2025-11-04",
      "path": "data/archives/2025/11/04/etna_20251104.png",
      "size": 123456,
      "compressed": false,
      "modified": "2025-11-04T12:00:00+00:00"
    }
  ]
}
```

### Retrieve Archived Graph

**Endpoint:** `GET /api/archives/graph/{date}`

**Parameters:**
- `date`: Date in `YYYY-MM-DD` format

**Example Request:**
```bash
curl "http://localhost:5000/api/archives/graph/2025-11-04" -o etna_20251104.png
```

**Response:**
- Content-Type: `image/png`
- Returns the PNG image file

### Get Processed Data

**Endpoint:** `GET /api/archives/data/{date}`

**Parameters:**
- `date`: Date in `YYYY-MM-DD` format

**Example Request:**
```bash
curl "http://localhost:5000/api/archives/data/2025-11-04"
```

**Example Response:**
```json
{
  "ok": true,
  "date": "2025-11-04",
  "count": 1440,
  "data": [
    {
      "timestamp": "2025-11-04T00:00:00Z",
      "value": 1.234
    },
    {
      "timestamp": "2025-11-04T00:10:00Z",
      "value": 1.456
    }
  ]
}
```

## Directory Structure

Archives are organized in a hierarchical directory structure:

```
data/archives/
├── 2025/
│   ├── 11/
│   │   ├── 01/
│   │   │   └── etna_20251101.png
│   │   ├── 02/
│   │   │   └── etna_20251102.png
│   │   └── 03/
│   │       └── etna_20251103.png.gz  # Compressed
│   └── 12/
│       └── ...
└── 2024/
    └── ...
```

## Technical Details

### File Locking

The archival system uses `fcntl.flock()` for exclusive file locking during writes to prevent corruption from concurrent access.

### Atomic Writes

Archives are written to temporary files first, then atomically moved to their final location using `shutil.move()`. This ensures that partially written files are never visible.

### Compression

When compression is enabled, files are compressed using gzip (level 6) before being saved with a `.gz` extension. Decompression is automatic when retrieving archives.

### Storage Management

The automatic cleanup feature removes archives older than the configured retention period, freeing up disk space. Cleanup runs after each successful archive operation.

## Error Handling

All archive operations include comprehensive error handling:

- **IOError**: File system operations (read/write/delete)
- **ValueError**: Invalid date formats or parameters
- **OSError**: Directory creation/removal issues

Errors are logged using Python's `logging` module with appropriate severity levels.

## Best Practices

1. **Regular Monitoring**: Check logs regularly for archival failures
2. **Disk Space**: Monitor available disk space, especially with low retention values
3. **Backup Strategy**: Consider backing up the archives directory to external storage
4. **Compression**: Enable compression for long-term archives to save space
5. **Retention Period**: Balance between data availability and storage costs

## Troubleshooting

### Archives Not Being Created

1. Check that `ARCHIVE_BASE_PATH` directory is writable
2. Verify `etna_loop.py` is running and successfully downloading graphs
3. Review logs for error messages

### Disk Space Issues

1. Reduce `ARCHIVE_RETENTION_DAYS` to free up space
2. Enable compression for future archives
3. Manually delete old archives if needed

### API Endpoints Not Working

1. Ensure `backend/app.py` is running
2. Check that archives exist in the expected directory structure
3. Verify date formats in API requests (must be `YYYY-MM-DD`)

## Future Enhancements

Potential improvements for the archival system:

- Cloud storage integration (S3, Google Cloud Storage)
- Incremental backups
- Archive verification and integrity checks
- Web interface for browsing archives
- Automated backup to remote locations
- Statistics and analytics on archived data

## Security Considerations

- Archives directory should have appropriate file permissions
- API endpoints should be protected with authentication in production
- Validate all user inputs (dates, paths) to prevent directory traversal
- Consider encryption for sensitive archived data

## Contributing

When contributing to the archival system:

1. Add tests for new features
2. Update this documentation
3. Follow existing code style and patterns
4. Ensure backward compatibility
5. Test with various date ranges and edge cases
