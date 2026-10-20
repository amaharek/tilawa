"""Constants for the Tilawa integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "tilawa"
NAME: Final = "Tilawa"
REPO_URL: Final = "https://github.com/amaharek/tilawa"

# Config entry data
CONF_LIBRARY_PATH: Final = "library_path"
CONF_PENDING_MOVE_FROM: Final = "pending_move_from"
CONF_MOVE_FILES: Final = "move_files"

# Selection subentry data / action fields
CONF_RECITER_ID: Final = "reciter_id"
CONF_MOSHAF_ID: Final = "moshaf_id"
CONF_SURAHS: Final = "surahs"
CONF_ALL_SURAHS: Final = "all_surahs"  # form-only switch, never stored
CONF_DELETE_FILES: Final = "delete_files"
SUBENTRY_TYPE_SELECTION: Final = "selection"

# Options
OPT_NAMES_LANGUAGE: Final = "names_language"
OPT_TITLE_FORMAT: Final = "title_format"
OPT_NUMBER_SEPARATOR: Final = "number_separator"
OPT_MAX_PARALLEL: Final = "max_parallel"
OPT_BANDWIDTH_LIMIT: Final = "bandwidth_limit_kbps"
OPT_AUTO_SYNC: Final = "auto_sync"
OPT_REDOWNLOAD_CHANGED: Final = "redownload_changed"

AUTO_SYNC_OFF: Final = "off"
AUTO_SYNC_DAILY: Final = "daily"
AUTO_SYNC_WEEKLY: Final = "weekly"
AUTO_SYNC_OPTIONS: Final = (AUTO_SYNC_OFF, AUTO_SYNC_DAILY, AUTO_SYNC_WEEKLY)
AUTO_SYNC_HOUR: Final = 3
AUTO_SYNC_WEEKDAY: Final = 0  # Monday

MAX_PARALLEL_LIMIT: Final = 4
BANDWIDTH_LIMIT_MAX: Final = 100_000
DEFAULT_OPTIONS: Final[dict[str, str | int | bool]] = {
    OPT_NAMES_LANGUAGE: "ar",
    OPT_TITLE_FORMAT: "number_ar",
    OPT_NUMBER_SEPARATOR: "space",
    OPT_MAX_PARALLEL: 2,
    OPT_BANDWIDTH_LIMIT: 0,
    OPT_AUTO_SYNC: AUTO_SYNC_OFF,
    OPT_REDOWNLOAD_CHANGED: False,
}
DEFAULT_SUBFOLDER: Final = "Quran"

# Actions
SERVICE_SYNC: Final = "sync"
SERVICE_ADD_SELECTION: Final = "add_selection"
SERVICE_REMOVE_SELECTION: Final = "remove_selection"
SERVICE_RETAG: Final = "retag"

# Storage
STORAGE_VERSION: Final = 1
STORAGE_KEY_CATALOGUE: Final = f"{DOMAIN}.catalogue"
STORAGE_KEY_INDEX: Final = f"{DOMAIN}.library_index"
STORAGE_KEY_SYNC_STATE: Final = f"{DOMAIN}.sync_state"
CATALOGUE_CHECK_INTERVAL: Final = timedelta(days=1)
CATALOGUE_MAX_AGE: Final = timedelta(days=7)
INDEX_SAVE_DELAY: Final = 2.0

# Repair issues
ISSUE_LIBRARY_NOT_WRITABLE: Final = "library_not_writable"
ISSUE_LOW_DISK_SPACE: Final = "low_disk_space"
ISSUE_SELECTION_MISSING: Final = "selection_missing_upstream"
ISSUE_ORPHANED_FILES: Final = "orphaned_files"
