# Tilawa — design proposal (step 2)

Status: **approved and implemented** (steps 3–5 done 2026-10-19; see "Implementation notes" at the end). Written 2026-10-19 against Home Assistant 2026.3.4
(minimum supported version) and the live API findings in [`api-notes.md`](api-notes.md).

Tilawa (تلاوة, "recitation") is a Home Assistant custom integration, domain `tilawa`, that
downloads Quran recitations from mp3quran.net into a media folder and tags them so Music
Assistant's filesystem provider shows `Reciter → Riwaya/style album → Surah tracks`. Music
Assistant is never touched; the only contract is correctly tagged files in a folder it scans.

Decisions already taken (see the plan): name/domain **Tilawa / `tilawa`**; selections are
**config subentries**; **no Music Assistant refresh hook** in v1; folder and file names
**follow the display-language options**.

## 1. Repository tree

```
.
├── custom_components/tilawa/
│   ├── __init__.py              # async_setup (actions), async_setup_entry, async_unload_entry, migration
│   ├── manifest.json
│   ├── const.py                 # DOMAIN, CONF_*, OPT_*, defaults, enums, storage keys
│   ├── config_flow.py           # ConfigFlow (user → naming → reciter → version, reconfigure),
│   │                            # SelectionSubentryFlow (user → version, reconfigure), OptionsFlow
│   ├── coordinator.py           # TilawaCatalogueCoordinator (weekly) + TilawaSyncManager (jobs)
│   ├── entity.py                # TilawaEntity base: device info, has_entity_name, availability
│   ├── sensor.py                # 6 sensors
│   ├── binary_sensor.py         # API reachable (connectivity, diagnostic)
│   ├── button.py                # Sync now, Cancel sync
│   ├── services.py              # action handlers + schemas, called from async_setup
│   ├── services.yaml
│   ├── repairs.py               # fix flows: orphaned_files, selection_missing_upstream
│   ├── diagnostics.py
│   ├── icons.json
│   ├── translations/en.json     # no strings.json (Marketplace guidance); ar.json added in step 5
│   ├── quality_scale.yaml       # informational; hassfest ignores it for custom integrations
│   ├── brand/icon.png, icon@2x.png, dark_icon.png, dark_icon@2x.png
│   └── lib/                     # pure Python, no homeassistant imports, mypy --strict
│       ├── __init__.py
│       ├── api.py               # Mp3QuranClient (aiohttp session injected)
│       ├── models.py            # frozen dataclasses (section 3)
│       ├── naming.py            # normalisation, album/title/path rules, filesystem safety
│       ├── tagger.py            # mutagen ID3v2.4 writer/reader (blocking; run in executor)
│       ├── downloader.py        # resumable, atomic, rate-limited downloads
│       ├── library.py           # LibraryIndex + plan builder (desired set vs disk)
│       ├── sync.py              # SyncEngine: runs a plan, retag, move, delete
│       └── surahs.py            # range-string parser ("78-114", "1,36,55-56")
├── tests/
│   ├── conftest.py              # enable_custom_integrations, fixture loaders, fake session
│   ├── fixtures/*.json          # captured 2026-10-19 (already present)
│   ├── lib/test_naming.py, test_tagger.py, test_downloader.py, test_api.py, test_library.py
│   ├── test_config_flow.py, test_init.py, test_sensor.py
├── scripts/
│   ├── develop                  # uv venv + HA core + dev/config, runs hass (section 9)
│   ├── lint                     # uv run ruff check/format, mypy
│   └── make_brand.py            # generates brand PNGs with Pillow (step 5)
├── dev/
│   ├── configuration.yaml       # template copied into dev/config on first run
│   └── docker-compose.yml       # Music Assistant server sharing dev/media
├── docs/api-notes.md, design.md, publishing.md (step 5)
├── .github/workflows/validate.yml, tests.yml, release.yml
├── .github/ISSUE_TEMPLATE/bug_report.yml, feature_request.yml
├── hacs.json, README.md, README.ar.md, LICENSE (MIT), pyproject.toml, .gitignore
```

`manifest.json` (keys sorted as hassfest wants: `domain`, `name`, then alphabetical):

```json
{
  "domain": "tilawa",
  "name": "Tilawa",
  "codeowners": ["@amaharek"],
  "config_flow": true,
  "dependencies": ["repairs"],
  "documentation": "https://github.com/amaharek/tilawa",
  "integration_type": "service",
  "iot_class": "cloud_polling",
  "issue_tracker": "https://github.com/amaharek/tilawa/issues",
  "loggers": ["mutagen"],
  "single_config_entry": true,
  "version": "0.1.0"
}
```

`hacs.json`: `{"name": "Tilawa", "homeassistant": "2026.3.0"}`.

## 2. Core library (`lib/`) public surface

```python
# api.py
class Mp3QuranClient:
    def __init__(self, session: aiohttp.ClientSession, *, base_url: str = "https://www.mp3quran.net/api/v3", user_agent: str = USER_AGENT) -> None
    async def async_ping(self) -> None                      # GET /languages; raises Mp3QuranConnectionError
    async def async_fetch_catalogue(self) -> Catalogue       # 8 GETs (ar+eng × reciters, suwar, riwayat, moshaf), merged + normalised
    async def async_head(self, url: str) -> RemoteFile       # size, etag, last_modified; raises on 3xx/4xx/5xx
class Mp3QuranError(Exception); class Mp3QuranConnectionError(Mp3QuranError); class Mp3QuranResponseError(Mp3QuranError)

# downloader.py
class Downloader:
    def __init__(self, session, *, max_parallel: int = 2, bandwidth_limit_kbps: int = 0, max_retries: int = 5, user_agent: str = USER_AGENT) -> None
    async def async_download(self, url: str, part_path: Path, *, expected: RemoteFile | None, on_progress: Callable[[int], None]) -> RemoteFile
    # Range resume from existing .part + If-Range: <etag>; 200 after a Range request = changed upstream → restart;
    # allow_redirects=False; 301/308 followed once if target ends with the same NNN.mp3; 302/303/307 → RedirectRefused;
    # verifies final size == Content-Length; exponential backoff 1,2,4,8,16 s with jitter; shared token bucket for bandwidth.
class DownloadError(Exception); class RedirectRefused(DownloadError); class SizeMismatch(DownloadError); class UpstreamChanged(DownloadError)

# tagger.py (blocking, run via executor)
def write_tags(path: Path, tags: TrackTags) -> None          # ID3.delete() then save v2.4 UTF-8, keeps audio untouched
def read_identity(path: Path) -> TrackIdentity | None        # TXXX:TILAWA_* → (reciter_id, moshaf_id, surah, source_etag) or None

# naming.py
def normalize(text: str) -> str                               # strip, collapse spaces, U+00AD → "-", NFC
def safe_component(text: str, *, max_len: int = 120) -> str   # Windows/SMB/Linux safe
def album_name(moshaf: Moshaf, cat: Catalogue, lang: Language) -> str
def album_names_for_reciter(moshafs: Sequence[Moshaf], cat: Catalogue, lang: Language) -> dict[int, str]  # deterministic disambiguation
def track_title(surah: Surah, fmt: TitleFormat) -> str
def build_track(reciter, moshaf, surah, cat, opts: NamingOptions) -> TrackSpec   # path + tags together, so they can never drift
def naming_fingerprint(opts: NamingOptions) -> str            # stored per file; change ⇒ retag

# surahs.py
def parse_range(text: str) -> frozenset[int]                  # "78-114", "1,36,55-56"; ValueError on bad input
def format_range(surahs: frozenset[int]) -> str                # canonical "78-114" / "1, 36, 55-56"

# library.py
class LibraryIndex          # in-memory dict of IndexedFile keyed by "reciter:moshaf:surah"; to_dict()/from_dict(); no I/O
def build_plan(cat: Catalogue, selections: Sequence[Selection], opts: NamingOptions, index: LibraryIndex, *, root: Path, redownload_changed: bool) -> SyncPlan

# sync.py
class SyncEngine:
    def __init__(self, *, client, downloader, root: Path, index: LibraryIndex, run_blocking: RunBlocking, on_progress: Callable[[SyncProgress], None], on_index_changed: Callable[[], Awaitable[None]]) -> None
    async def async_estimate(self, plan: SyncPlan) -> int       # Σ HEAD sizes of downloads (concurrency 4)
    async def async_run(self, plan: SyncPlan, cancel: asyncio.Event) -> SyncResult
    async def async_retag(self, cat, selections, opts, cancel) -> SyncResult      # rewrite tags; rename/move files whose path changed
    async def async_move_root(self, new_root: Path, cancel) -> SyncResult         # move indexed files only, then prune empty dirs
    async def async_delete(self, keys: Sequence[str]) -> int                      # only indexed files whose TXXX identity matches
    async def async_adopt(self) -> int                                            # walk root, adopt files with our TXXX tags missing from index
```

`RunBlocking = Callable[..., Awaitable[Any]]`; the library defaults to
`loop.run_in_executor(None, …)` and Home Assistant passes `hass.async_add_executor_job`.

## 3. Data model (`lib/models.py`, all `@dataclass(frozen=True, slots=True)`)

| Type | Fields |
|---|---|
| `Surah` | `number`, `name_ar`, `name_en`, `makki: bool`, `start_page`, `end_page` |
| `Riwaya` | `id`, `name_ar`, `name_en` |
| `MoshafType` | `id` (= reciters' `moshaf_type`), `riwaya_id`, `style_id`, `name_ar`, `name_en` |
| `Moshaf` | `id`, `reciter_id`, `name_ar`, `name_en`, `riwaya_id`, `type_id`, `server`, `surahs: frozenset[int]` |
| `Reciter` | `id`, `name_ar`, `name_en`, `moshafs: tuple[Moshaf, ...]` |
| `Catalogue` | `fetched_at`, `reciters`, `moshafs`, `suwar`, `riwayat`, `moshaf_types` (all `Mapping[int, …]`), helpers `reciter_for_moshaf()` |
| `Selection` | `reciter_id`, `moshaf_id`, `surahs: frozenset[int] \| None` (None = everything the moshaf offers); `key` property `"118:119"` |
| `NamingOptions` | `names_language: Literal["ar","eng"]`, `title_format: Literal["number_ar","number_en","number_both"]`, `number_separator: Literal["space","hyphen","spaced_hyphen"]` (0.1.1) |
| `TrackTags` | `artist`, `album_artist`, `album`, `title`, `track: tuple[int,int]`, `disc=(1,1)`, `genre="Quran"`, `sort_artist`, `sort_album_artist`, `sort_album`, `sort_title`, `reciter_id`, `moshaf_id`, `surah`, `source_etag` |
| `TrackSpec` | `key`, `url`, `relative_path: PurePath`, `tags: TrackTags`, `surah` |
| `RemoteFile` | `size: int`, `etag: str \| None`, `last_modified: str \| None` |
| `IndexedFile` | `key`, `relative_path`, `size`, `source_etag`, `naming_fingerprint`, `downloaded_at` |
| `SyncPlan` | `downloads: list[TrackSpec]`, `retags: list[tuple[IndexedFile, TrackSpec]]`, `orphans: list[IndexedFile]` (indexed but no longer selected), `estimated_bytes` |
| `SyncProgress` | `state: SyncState`, `kind: JobKind`, `total`, `done`, `failed`, `bytes_total`, `bytes_done`, `current_key`, `started_at`, `error` |
| `SyncResult` | counts, duration, `errors: list[str]` (bounded to 20) |

`SyncState = idle | syncing | retagging | moving | error`; `JobKind = sync | retag | move`.

## 4. Naming and tagging rules

**Normalisation** (every API string): `str.strip()`, collapse whitespace runs, U+00AD → `-`,
`unicodedata.normalize("NFC")`. Derived from the data: 109 English surah names have trailing
spaces, five contain soft hyphens, three moshaf names have double spaces.

**Artist** = reciter name in `names_language`. `TPE1` = `TPE2` = that name. Sort tags
(`TSOP`, `TSO2`) = English name always.

**Album** = `f"{riwaya_short} – {style_short}"` (U+2013 en dash) built from `rewaya_id` and
`style_id = moshaf_type % 10` (or `/moshaf` row), never by parsing the display name. When the
riwaya is a style placeholder (ids 21, 22) the album is the style alone.

| rewaya_id | eng | ar | | style | eng | ar |
|---|---|---|---|---|---|---|
| 1 | Hafs | حفص | | 1 | Murattal | مرتل |
| 2 | Warsh | ورش | | 2 | Mujawwad | مجود |
| 3 | Khalaf | خلف | | 3 | Mu'allim | معلم |
| 4 | Al-Bazzi | البزي | | 4 | Featured | تلاوة مميزة |
| 5 | Qalun | قالون | | 20 | 1967 recording | تسجيل 1967 |
| 6 | Qunbul | قنبل | | | | |
| 7 | As-Susi | السوسي | | | | |
| 8 | Qalun (Abu Nashit) | قالون (أبي نشيط) | | | | |
| 9 | Ruways & Rawh | رويس وروح | | | | |
| 10 | Warsh (Al-Asbahani) | ورش (الأصبهاني) | | | | |
| 11 | Al-Bazzi & Qunbul | البزي وقنبل | | | | |
| 12 | Ad-Duri (Al-Kisa'i) | الدوري (الكسائي) | | | | |
| 13 | Ad-Duri (Abu Amr) | الدوري (أبي عمرو) | | | | |
| 15 | Shu'bah | شعبة | | | | |
| 16 | Ibn Dhakwan | ابن ذكوان | | | | |
| 18 | Warsh (Al-Azraq) | ورش (الأزرق) | | | | |
| 19 | Hisham | هشام | | | | |
| 20 | Ibn Jammaz | ابن جماز | | | | |

Examples: type 11 → `Hafs – Murattal` / `حفص – مرتل`; 21 → `Warsh – Murattal`; 222 →
`Mujawwad`; 213 → `Mu'allim`; 13 → `Hafs – Mu'allim`; 14 → `Hafs – Featured`; 120 →
`Hafs – 1967 recording`. Unknown ids fall back to the normalised API name split on ` - `.
Sort album (`TSOA`) = English album. **Disambiguation**: within one reciter's selected
moshafs, equal album names get ` (#<moshaf_id>)` appended, deterministic and stable.

**Title** (`TIT2`) by `title_format`: `number_ar` → `018 الكهف` (default); `number_en` →
`018 Al-Kahf`; `number_both` → `018 الكهف – Al-Kahf`. `TSOT` = `018 Al-Kahf` always.
`TRCK` = `18/114` (canonical even for ranges), `TPOS` = `1/1`, `TCON` = `Quran`.

**Identity** (`TXXX`): `TILAWA_RECITER_ID`, `TILAWA_MOSHAF_ID`, `TILAWA_SURAH`,
`TILAWA_SOURCE_ETAG`. Only files carrying all three ids are ever renamed or deleted.

**Path**: `<library>/<safe(artist)>/<safe(album)>/<NNN> <safe(title without number)>.mp3`,
e.g. `/media/Quran/محمود خليل الحصري/حفص – مرتل/018 الكهف.mp3`. `safe_component` replaces
`<>:"/\|?*` and control chars with `_`, strips trailing dots and spaces, prefixes `_` to
Windows reserved names, and truncates to 120 code points. Temp files are `<final>.part` in the
same directory; `os.replace` makes the publish atomic.

**Invariants tested**: all tracks of one moshaf share identical `TALB`/`TPE1`/`TPE2`; all
albums of one reciter share identical `TPE1`/`TPE2`; path and tags come from one
`build_track` call.

**Cover art**: not in v1 (Arabic text needs libraqm, which HA's Pillow wheels may lack;
existing APIC frames are stripped). Revisit in v2 with English-only text if wanted.

## 5. Sync engine

**Desired set** = for each selection: `moshaf.surahs ∩ (selection.surahs or all)`, built from
the current catalogue, so new surahs upstream are picked up on the next sync.

**Plan** (pure): for each desired track, compare with the index: missing → download;
present but `naming_fingerprint` differs → retag (+ rename if the path changed); present and
`redownload_changed` and HEAD etag ≠ stored → download; indexed but not desired → orphan
(never deleted here; reported). Index lookups are by key; a missing-on-disk indexed file is
treated as missing (and dropped from the index).

**Run** (`JobKind.sync`):
1. Refresh catalogue if older than 7 days (best effort; stale cache is fine).
2. Build plan; `async_estimate` HEADs each download (concurrency 4) to size the job.
3. Free space: `shutil.disk_usage(root).free < estimate × 1.05 + 256 MiB` → abort, raise
   repair `low_disk_space` with placeholders (needed, free). Also aborts if root is not writable
   → repair `library_not_writable`.
4. Workers (`max_parallel`, default 2) pull tracks from a queue: ensure dirs → download to
   `.part` with resume → verify size → `write_tags` in executor → `os.replace` → index update →
   progress callback. Per-file failures are logged once, counted, and do not stop the job; the
   job ends `error` if any failed. Cancel = `asyncio.Event`; `.part` files stay for resume.
5. Finish: persist index + stats; `last_success` only when `failed == 0`.

**Retag** (`JobKind.retag`, triggered by naming option changes or the `tilawa.retag` action):
for each indexed file, compute the new `TrackSpec`; if the relative path differs, create dirs
and `os.replace` (same filesystem); rewrite tags; prune empty directories; update index. No
network. Music Assistant will see renamed files as new items (documented limitation chosen by
the user).

**Move** (`JobKind.move`, from the reconfigure flow with "move files"): moves indexed files
only, directory by directory, falling back to copy+delete across filesystems, then prunes.
Runs on setup when entry data has `pending_move_from`, so it survives a restart.

**Delete** (from the Repair fix flow or `remove_selection(delete_files=true)`): for each
indexed file of the selection, `read_identity` must match the key, then unlink; prune empty
dirs; drop from index. Files without our tags are never touched.

**Resume after restart**: the sync state store keeps `active_job: {kind, filter,
requested_at}`. On setup, if present, the manager waits for `EVENT_HOMEASSISTANT_STARTED` and
re-runs the same job kind from a fresh plan: completed files are skipped by the index, partial
ones resume via Range. Cancelling clears `active_job`.

**Adopt**: if the index is empty or a plan finds an expected path occupied by an untracked file,
`async_adopt` walks the library once, reads `TXXX` ids and adopts matching files (handles a
restored `.storage` or a manually copied library).

**Politeness**: `User-Agent: Tilawa/<version> (+https://github.com/amaharek/tilawa)`,
default 2 parallel downloads, optional token-bucket bandwidth limit, backoff on 429/5xx.

## 6. Storage (`homeassistant.helpers.storage.Store`, all version 1)

| Key | Content |
|---|---|
| `tilawa.catalogue` | `{"fetched_at": iso, "catalogue": Catalogue.to_dict()}` (both languages, ~400 KB) |
| `tilawa.library_index` | `{"root": "/media/Quran", "files": {key: IndexedFile.to_dict()}}` |
| `tilawa.sync_state` | `{"active_job": {...} \| null, "last_success": iso \| null, "last_result": SyncResult.to_dict() \| null, "errors": [..20]}` |

Nothing is stored inside the library folder, so `hacs.json` needs no `persistent_directory`.

## 7. Home Assistant integration

### 7.1 Setup and runtime data

```python
@dataclass
class TilawaRuntimeData:
    client: Mp3QuranClient
    catalogue: TilawaCatalogueCoordinator
    sync: TilawaSyncManager


type TilawaConfigEntry = ConfigEntry[TilawaRuntimeData]
```

`async_setup` registers the four actions (rule `action-setup`). `async_setup_entry`: build
client on `async_get_clientsession(hass)`; coordinator `async_config_entry_first_refresh()`
(uses the cached catalogue when fresh; raises `ConfigEntryNotReady` only when there is no cache
and the API is unreachable — rule `test-before-setup`); create the sync manager (load stores,
run pending move, schedule resume); forward `sensor`, `binary_sensor`, `button`; register the
update listener; arm the auto-sync timer. `async_unload_entry` cancels a running job (keeping
`active_job` so it resumes), unloads platforms. `async_remove_entry` deletes the three stores
and leaves files on disk (documented).

**Update listener** (fires on options change and on subentry add/remove/update, verified in
`config_entries._async_update_entry`): naming options changed → schedule retag; sync options
changed → apply to the next job and re-arm the timer; subentry added or range widened →
schedule sync; subentry removed → if its files are indexed, raise repair `orphaned_files`
for that key. No entry reload is needed for any of these.

### 7.2 Coordinators

`TilawaCatalogueCoordinator(DataUpdateCoordinator[Catalogue])`, `update_interval = 7 days`,
`config_entry` passed, `PARALLEL_UPDATES = 0` in platforms. `_async_update_data` fetches both
languages, saves to `tilawa.catalogue`, and on failure raises `UpdateFailed` while entities
keep the last catalogue (the coordinator logs once on failure and once on recovery, rule
`log-when-unavailable`). It also compares selections against the new catalogue and raises or
clears repair `selection_missing_upstream`.

`TilawaSyncManager` (not a coordinator): owns the `SyncEngine`, the job task, the state store,
a `SyncProgress` snapshot and a listener set; entities subscribe via `async_add_listener`.
Public: `async_request_sync(filter)`, `async_request_retag()`, `async_cancel()`,
`async_remove_selection(key, delete_files)`, `progress`, `stats` (files, bytes, reciters).
Requests arriving during a job set a `rerun` flag that is honoured when the job finishes.

### 7.3 Config flow (`single_config_entry: true`, unique id = `tilawa`)

| Step | Fields | Validation / notes |
|---|---|---|
| `user` | `library_path` (text, default `<first media_dir>/Quran`) | API ping first (`cannot_connect`, rule `test-before-configure`); create folder if missing (`cannot_create`); write-probe a temp file (`not_writable`); `description_placeholders` show free space of the parent volume |
| `naming` | `names_language` (select ar/eng, default ar), `title_format` (select, default `number_ar`) | selectors with `translation_key` so option labels are translated |
| `reciter` | `reciter_id` (select, dropdown with search, labels `Name (N versions)` in `names_language`) | from the catalogue fetched in `user` |
| `version` | `moshaf_id` (select, labels `Album (N surahs)`), `surahs` (optional text, e.g. `78-114`) | `invalid_surahs`, `surahs_not_available` (outside the moshaf's list) |
| create | title `Tilawa`, data `{library_path}`, options defaults, `subentries=[first selection]` | one wizard, no second flow needed |
| `reconfigure` | `library_path`, `move_files` (bool, default on) | same validation; stores `pending_move_from` when moving; `async_update_reload_and_abort` |

### 7.4 Selection subentry flow (type `selection`)

Button label "Add reciter" on the integration page. Steps `user` (reciter) → `version`
(moshaf + optional range) → `async_create_entry(title="Al-Hussary — Hafs – Murattal (78–114)",
data={reciter_id, moshaf_id, surahs}, unique_id="118:118")`. Duplicate `unique_id` aborts with
`already_configured` automatically. `reconfigure` edits only `surahs` (reciter and version are
the identity). Removal uses HA's own subentry delete; the update listener then raises the
`orphaned_files` repair if files exist.

### 7.5 Options flow (single `init` form)

| Option | Type | Default |
|---|---|---|
| `names_language` | ar / eng | ar |
| `title_format` | number_ar / number_en / number_both | number_ar |
| `number_separator` | space / hyphen / spaced_hyphen (`018 `, `018- `, `018 - `) | space |
| `max_parallel` | 1–4 | 2 |
| `bandwidth_limit_kbps` | 0–100000 (0 = unlimited) | 0 |
| `auto_sync` | off / daily / weekly | off |
| `redownload_changed` | bool (re-fetch when upstream ETag changed) | off |

Auto-sync runs at 03:00 local time via `async_track_time_change`; weekly = Mondays.

### 7.6 Entities (one device "Tilawa", `has_entity_name`, unique ids `<entry_id>_<key>`)

| Entity | Class | Details |
|---|---|---|
| `sensor.tilawa_sync_status` | enum: idle, syncing, retagging, moving, error | attributes: `job`, `current`, `done`, `total`, `failed` |
| `sensor.tilawa_sync_progress` | `%` | 0–100 from bytes when known, else from file counts |
| `sensor.tilawa_files` | count, diagnostic | files in the index |
| `sensor.tilawa_library_size` | `data_size`, bytes, diagnostic, `suggested_unit_of_measurement = GB`, precision 2 | Σ index sizes |
| `sensor.tilawa_last_sync` | `timestamp`, diagnostic | last fully successful sync |
| `sensor.tilawa_reciters` | count, diagnostic | distinct reciters among selections |
| `binary_sensor.tilawa_api` | `connectivity`, diagnostic | `coordinator.last_update_success` |
| `button.tilawa_sync_now` | | disabled state while a job runs is reflected via availability? No: always available, no-op with a log line if busy |
| `button.tilawa_cancel_sync` | | |

Sync and library entities are **not** marked unavailable when the API is down (their data is
local). The connectivity sensor carries the API state. Icons in `icons.json`
(`mdi:book-open-page-variant`, `mdi:sync`, `mdi:harddisk`, …).

### 7.7 Actions (`services.yaml`, translated, registered in `async_setup`)

| Action | Fields | Errors (`ServiceValidationError`, translated) |
|---|---|---|
| `tilawa.sync` | `reciter_id?`, `moshaf_id?` | `not_loaded`, `unknown_selection` |
| `tilawa.add_selection` | `reciter_id`, `moshaf_id`, `surahs?` | `unknown_reciter`, `unknown_moshaf`, `invalid_surahs`, `surahs_not_available`, `already_selected` |
| `tilawa.remove_selection` | `reciter_id`, `moshaf_id`, `delete_files` (default false) | `unknown_selection` |
| `tilawa.retag` | – | `not_loaded`, `busy` |

`add_selection` creates a subentry through `hass.config_entries.async_add_subentry`;
`remove_selection` removes it and deletes files when asked. Runtime failures (I/O, network)
raise `HomeAssistantError` with translation keys.

### 7.8 Repairs and diagnostics

| Issue id | Fixable | Trigger |
|---|---|---|
| `library_not_writable` | no (instructions) | setup or job start cannot write to the library |
| `low_disk_space` | no | estimate exceeds free space; placeholders `needed`, `free` |
| `selection_missing_upstream_<key>` | yes, confirm → remove selection (files kept) | catalogue refresh no longer lists the reciter or moshaf |
| `orphaned_files_<key>` | yes, form with `delete_files` (default off) | selection removed while indexed files remain; "keep" dismisses and forgets the index rows |

Diagnostics: entry data and options, subentries, index summary (counts, bytes, per-selection
counts), sync state, last 20 errors, catalogue `fetched_at` and counts, through
`async_redact_data` with an (empty for now) `TO_REDACT` set.

### 7.9 Translations and icons

`translations/en.json` covers `config` (steps, errors, abort), `config_subentries.selection`
(`initiate_flow.user/reconfigure`, `entry_type`, steps, errors, abort), `options`, `entity`
(names and enum states), `exceptions`, `issues`, `services`, `selector` (option labels).
`ar.json` mirrors it in step 5. `icons.json` gives entity and service icons.

## 8. Dev tooling (uv only)

`pyproject.toml`: `[project] name = "tilawa" requires-python = ">=3.14.2"` (not published),
`[dependency-groups] dev = ["pytest-homeassistant-custom-component==0.13.320", "aioresponses",
"pytest-cov", "ruff", "mypy", "mutagen>=1.47.0,<2", "Pillow"]`, ruff config copied from HA
core's rule set, `[tool.mypy] strict = true` scoped to `custom_components/tilawa`, pytest
`asyncio_mode = auto`, `testpaths = ["tests"]`.

Commands: `uv sync --group dev`, `uv run pytest`, `uv run ruff check`, `uv run ruff format
--check`, `uv run mypy custom_components/tilawa`. `scripts/develop` builds a separate venv
with `homeassistant==${HA_VERSION:-2026.3.4}`, symlinks the integration into
`dev/config/custom_components/`, and runs `hass -c dev/config --debug`. `dev/docker-compose.yml`
starts Music Assistant with `./dev/media:/media`. CI (`tests.yml`) uses `astral-sh/setup-uv`;
`validate.yml` runs `hacs/action` and hassfest as in the spec; `release.yml` (step 5) creates
a GitHub release from a `v*` tag after checking it matches `manifest.json`.

## 9. Phase A tests (ship with steps 3–4)

| File | Cases |
|---|---|
| `tests/lib/test_naming.py` | normalisation (trailing space, soft hyphen, double space); album name for every `moshaf_type` in `moshaf_eng.json`, ar and eng; disambiguation; title formats; `safe_component` on `CON`, `a/b:c`, trailing dot; the album/artist invariants over a full 114-track build |
| `tests/lib/test_surahs.py` | parse/format ranges, rejects `0`, `115`, `20-10` |
| `tests/lib/test_api.py` | catalogue parsing from fixtures: counts, `rewaya_id`, `surahs`, both languages merged; connection error mapping |
| `tests/lib/test_tagger.py` | write then read back on a generated silent MP3; prior APIC/TPE2 removed; identity round-trip |
| `tests/lib/test_downloader.py` | full download verifies size and atomic publish; resume from `.part` sends `Range` + `If-Range`; 302 is refused; size mismatch raises |
| `tests/lib/test_library.py` | plan: missing → download, fingerprint change → retag, deselected → orphan |
| `tests/test_config_flow.py` | happy path creates entry with one subentry; `cannot_connect`; `not_writable`; subentry add + duplicate abort |
| `tests/test_init.py` | setup/unload; `ConfigEntryNotReady` without cache and API down |
| `tests/test_sensor.py` | status and library-size sensors follow manager state |

## 10. Points to confirm before step 3

1. Album short names and spellings in the table above (section 4).
2. `number_both` title separator: `018 الكهف – Al-Kahf`.
3. Adding a selection starts a sync immediately (no extra "Sync now" needed).
4. Auto-sync time 03:00 local, weekly on Mondays.
5. Cover art left out of v1.
6. Bandwidth limit expressed in kB/s.
7. Deleting the integration keeps the files (removal of files only through repairs/action).

## Implementation notes (deviations from the proposal)

- `tilawa.retag` while a job runs is **queued** and runs after it, instead of raising
  `busy`. Only `remove_selection` with `delete_files` and the orphaned-files repair
  refuse to run while a job is active.
- `manifest.json` lists `repairs` as a dependency so the fix flows are always available.
- `manifest.json` declares **no `requirements`**: mutagen is in Home Assistant core's own
  `requirements.txt` (1.47.0 at 2026.3.0), and hassfest rejects custom integrations that
  re-list a core dependency. The dev group still pins `mutagen>=1.47.0,<2` for tests.
- `dependencies`, `services.yaml`, `icons.json` and both translation files exist; there
  is no `strings.json` (Marketplace guidance).
- The catalogue coordinator polls daily (connectivity ping) and fetches weekly, so the
  connectivity sensor is at most a day stale instead of a week.
- `sync.py` exposes `async_head_many` so the "re-download changed files" option can HEAD
  already-indexed files before planning.
- 0.1.2: the version and reconfigure steps carry a **Download all surahs** switch (on by
  default); the range field is used only when it is off. The switch is form-only and
  not stored; a selection without a range still means "everything available".
- Phase A shipped 65 tests at 83 % line coverage of the integration; Phase B (full
  error paths, >95 %, HA version matrix) starts after the manual Home Assistant test.
