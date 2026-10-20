# Tilawa — a Quran recitation library for Music Assistant

[العربية](README.ar.md)

Tilawa (تلاوة, "recitation") is a [Home Assistant](https://www.home-assistant.io/)
custom integration that downloads Quran recitations from
[mp3quran.net](https://mp3quran.net) into a media folder and tags them so that
[Music Assistant](https://www.music-assistant.io/) shows a clean library:

```
Artists                     Albums (per reciter)            Tracks
──────────────────────      ──────────────────────────      ─────────────────────
محمود خليل الحصري      →    حفص – مرتل                 →   001 الفاتحة
                            ورش – مرتل                      002 البقرة
                            مجود                            …
Mishary Alafasi        →    Hafs – Murattal            →    018 الكهف
```

Searching **الكهف** in Music Assistant lists every downloaded reciter's version of
Al-Kahf; the English transliteration is written to the sort tags.

Music Assistant is never modified. The only contract between the two is **correctly
tagged files in a folder Music Assistant scans**.

> Tilawa is an independent community project. It is **not affiliated with
> mp3quran.net**, Home Assistant or Music Assistant.

## What it does

- Lets you pick reciters and their versions (riwaya and recitation style) from the
  mp3quran catalogue, optionally limited to a surah range such as Juz' Amma (78–114).
- Downloads the MP3 files with resume, retry and verification, two at a time by
  default, with an optional bandwidth limit.
- Strips the inconsistent tags the files ship with and writes clean ID3v2.4 tags:
  artist and album artist = reciter, album = riwaya and style, title = numbered surah,
  track number = surah number out of 114, genre = Quran, English sort tags, and
  private identifiers so Tilawa can recognise its own files later.
- Keeps the library in sync: new surahs published upstream are fetched on the next
  sync, naming changes are applied in place, and files are only ever deleted when you
  ask for it.
- Exposes a device with sensors (status, progress, files, size, last sync, reciters),
  a connectivity sensor for the API, buttons for sync and cancel, four actions, and
  repair issues for the things that need a decision from you.

## Requirements

- Home Assistant **2026.3.0 or newer** (OS, Supervised, Container or Core). No extra
  Python packages: the ID3 tagging library (mutagen) ships with Home Assistant itself.
- Music Assistant with a **Filesystem (local disk)** source pointing at the same folder.
- Disk space: a complete murattal recording of the whole Quran is **1.5 to 2.5 GB**
  (see [Storage](#storage-estimates)).

### Make sure Music Assistant sees the folder

| Setup | Where Tilawa writes | What Music Assistant sees |
|---|---|---|
| HA OS or Supervised with the Music Assistant add-on | `/media/Quran` (the default) | The add-on mounts Home Assistant's media folder read-write, so add a Filesystem (local disk) provider with path `/media/Quran`. |
| Docker (HA and MA in separate containers) | The folder you mount at `/media` in the HA container, e.g. `-v /srv/media:/media` | Mount the same host folder in the MA container, e.g. `-v /srv/media:/media`, and point the provider at `/media/Quran`. |
| HA Core (venv) | Any folder listed in `media_dirs` or `allowlist_external_dirs` | The same absolute path on the same machine, or the share it is exported on. |

Music Assistant rescans its filesystem provider on its own schedule. To see new files
immediately, open Music Assistant → Settings → Providers → your Filesystem provider →
**Sync**. Tilawa does not trigger that sync.

## Installation

### HACS or Marketplace (recommended)

Home Assistant 2026.11 and newer ship HACS built in as **Settings → Marketplace**;
older releases use the HACS integration. Both read the same repositories.

1. **Until Tilawa is in the default catalogue**, add it as a custom repository:
   - HACS: HACS → ⋮ → *Custom repositories* → URL `https://github.com/amaharek/tilawa`,
     type *Integration*.
   - Marketplace: Settings → Marketplace → *Add from link* → `amaharek/tilawa`.

   [![Open your Home Assistant instance and open a repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=amaharek&repository=tilawa&category=integration)
2. Search for **Tilawa**, download it, and restart Home Assistant.
3. Settings → Devices & services → **Add integration** → Tilawa.

   [![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=tilawa)

### Manual

Copy `custom_components/tilawa` from the
[latest release](https://github.com/amaharek/tilawa/releases) into
`<config>/custom_components/tilawa`, restart Home Assistant, then add the integration.

## Configuration

The setup wizard has four screens:

1. **Library folder.** Defaults to `<first media folder>/Quran` (usually
   `/media/Quran`). The folder is created if needed and must be writable; the free
   space of that volume is shown. Paths outside your media folders must be listed in
   `allowlist_external_dirs`.
2. **Names and titles.** Reciter and album names in Arabic or English, and the track
   title format (see [Naming](#naming-and-tags)).
3. **Reciter.** A searchable list of the catalogue's reciters with the number of
   versions each has.
4. **Version.** The reciter's versions with the number of available surahs, and an
   optional surah range (`78-114`, or `1, 36, 55-56`). Leave it empty for everything
   the version offers.

Setup checks that mp3quran.net is reachable. The first selection starts downloading
right away.

### Adding and changing selections

Each reciter version is a **subentry** of the integration. On the integration page:

- **Add reciter** adds another version (same reciter → version → range steps).
- The ⋮ menu of a selection offers **Change surah range**.
- **Delete** removes the selection. Files are kept; a repair issue then lets you
  delete them or keep them.

Adding a selection or widening its range starts a sync.

### Options

Settings → Devices & services → Tilawa → **Configure**:

| Option | Default | Effect |
|---|---|---|
| Reciter and album names | Arabic | Language of `TPE1`/`TPE2`/`TALB` and of the folder names. |
| Track title | Number and Arabic name | `018 الكهف`, `018 Al-Kahf` or `018 الكهف – Al-Kahf`. Also the file name. |
| Parallel downloads | 2 | 1 to 4 simultaneous files. Please stay polite to the free service. |
| Bandwidth limit | 0 (unlimited) | kB/s shared by all downloads. |
| Automatic sync | Off | Daily or weekly at 03:00 local time (weekly on Mondays). |
| Re-download files that changed upstream | Off | Compares every file's ETag with the server on each sync. mp3quran re-uploaded the whole catalogue in September 2026, so this does happen. |

Changing a naming option **retags and renames** the existing files without
downloading anything. Music Assistant treats renamed files as new items: favourites,
playlists and play counts tied to the old paths are lost. Pick your naming before
building a large library, or accept the reset.

### Changing the library folder

Settings → Devices & services → Tilawa → ⋮ → **Reconfigure**. Tick *Move existing
files* to move the downloaded files to the new folder; the move runs as a background
job and survives a restart.

## Naming and tags

```
<library>/<Reciter>/<Album>/<NNN> <Surah>.mp3
/media/Quran/محمود خليل الحصري/حفص – مرتل/018 الكهف.mp3
```

| Tag | Value | Example |
|---|---|---|
| `TPE1`, `TPE2` | Reciter in the chosen language | `محمود خليل الحصري` |
| `TALB` | Riwaya – style, from the catalogue ids | `حفص – مرتل`, `Hafs – Murattal`, `Mujawwad` |
| `TIT2` | Numbered surah in the chosen format | `018 الكهف` |
| `TRCK`, `TPOS` | Surah number out of 114, disc 1/1 | `18/114`, `1/1` |
| `TCON` | `Quran` | |
| `TSOP`, `TSO2`, `TSOA`, `TSOT` | English transliterations for A–Z sorting and search | `Mahmoud Khalil Al-Hussary`, `018 Al-Kahf` |
| `TXXX:TILAWA_*` | Reciter id, version id, surah, source ETag | |

Album names come from the riwaya and style ids, not from parsing display names:
Hafs, Warsh, Qalun, Khalaf, Ad-Duri (Abu Amr), Shu'bah, … combined with Murattal,
Mujawwad, Mu'allim, Featured or "1967 recording". Recordings whose riwaya the
catalogue does not state (the Mujawwad and Mu'allim mushafs) get the style alone as
album name. Two versions of one reciter that would share a name get the version id
appended. Every track of a version carries identical artist and album tags, which is
what keeps Music Assistant from splitting artists or albums.

Folder and file names follow the chosen display language and are made safe for
Windows, Linux, macOS and SMB shares.

## Entities

One device, **Tilawa**, with:

| Entity | Notes |
|---|---|
| `sensor.tilawa_sync_status` | `idle`, `syncing`, `retagging`, `moving`, `error`; attributes show job, current track, processed, total, failed, last error. |
| `sensor.tilawa_sync_progress` | 0–100 %, by bytes when the sizes are known. |
| `sensor.tilawa_files` | Files Tilawa manages (diagnostic). |
| `sensor.tilawa_library_size` | Total size, shown in GB (diagnostic). |
| `sensor.tilawa_last_successful_sync` | Timestamp (diagnostic). |
| `sensor.tilawa_reciters` | Distinct reciters among your selections (diagnostic). |
| `binary_sensor.tilawa_mp3quran_net_reachable` | API connectivity, checked daily and on every sync (diagnostic). |
| `button.tilawa_sync_now`, `button.tilawa_cancel_sync` | |

Library sensors stay available when mp3quran.net is down; their data is local.

## Actions

| Action | Fields | Does |
|---|---|---|
| `tilawa.sync` | `reciter_id`, `moshaf_id` (both optional) | Downloads what is missing for all selections, or for one version. |
| `tilawa.add_selection` | `reciter_id`, `moshaf_id`, `surahs` (optional) | Adds a version and starts downloading it. |
| `tilawa.remove_selection` | `reciter_id`, `moshaf_id`, `delete_files` (default `false`) | Removes a version, optionally deleting its files. |
| `tilawa.retag` | – | Rewrites tags and names from the current options. |

The ids are mp3quran's: the reciter id and the *moshaf* id. Find them in the
[catalogue](https://www.mp3quran.net/api/v3/reciters?language=eng) or in the title
of a selection's diagnostics. Al-Hussary is reciter 118 with versions 118 (Hafs),
119 (Mujawwad), 120 (Warsh), 269 (Ad-Duri) and 270 (Qalun); Mishary Alafasi is
reciter 123 with versions 123 (Hafs) and 124 (Ad-Duri).

## Examples

### Nightly sync

```yaml
automation:
  - alias: Tilawa nightly sync
    triggers:
      - trigger: time
        at: "03:30:00"
    actions:
      - action: tilawa.sync
```

(The built-in *Automatic sync* option does the same without an automation.)

### Bedtime: azkar, then Al-Mulk

```yaml
automation:
  - alias: Bedtime recitation
    triggers:
      - trigger: time
        at: "22:30:00"
    actions:
      - action: music_assistant.play_media
        target:
          entity_id: media_player.bedroom
        data:
          media_type: playlist
          media_id: Evening azkar          # your own playlist in Music Assistant
      - action: music_assistant.play_media
        target:
          entity_id: media_player.bedroom
        data:
          media_type: track
          media_id: "067 الملك"
          artist: محمود خليل الحصري
          album: حفص – مرتل
          enqueue: add
```

### Dashboard button that adds a reciter

```yaml
type: button
name: Add Alafasi (Juz' Amma)
icon: mdi:account-plus
tap_action:
  action: perform-action
  perform_action: tilawa.add_selection
  data:
    reciter_id: 123
    moshaf_id: 123
    surahs: "78-114"
```

## Storage estimates

Measured on 2026-10-19 by summing the server's `Content-Length` for every surah:

| Version | Bitrate | Whole Quran | Juz' Amma (78–114) | Al-Baqarah alone |
|---|---|---|---|---|
| Mishary Alafasi, Hafs Murattal | 128 kbps | 1.60 GiB | 58 MiB | 121 MB |
| Mahmoud Khalil Al-Hussary, Hafs Murattal | 128 kbps | 2.30 GiB | 82 MiB | 191 MB |
| Mahmoud Khalil Al-Hussary, Mujawwad | 96 kbps | 2.50 GiB | 90 MiB | 212 MB |

Tilawa checks the free space before each sync (estimate plus 5 % and 256 MiB) and
raises a repair issue instead of filling the disk.

## How data is updated

- The mp3quran catalogue is fetched when you set the integration up, cached in
  `.storage`, refreshed weekly, and the API is pinged daily for the connectivity
  sensor. A restart never needs the network.
- Syncs run only when you start them (button, action, adding a selection) or on the
  automatic schedule. Each sync compares your selections with the files on disk,
  checks the free space, downloads what is missing, and skips what is present.
- An interrupted sync (restart, power loss) resumes after Home Assistant has started,
  continuing partially downloaded files where they stopped.

## Known limitations

- **No streaming.** Tilawa builds a local library; it does not play or stream anything.
- **Music Assistant rescan timing.** New files appear after Music Assistant's next
  filesystem sync, which Tilawa cannot trigger.
- **No reciter images.** The mp3quran API has none, and Tilawa ships no cover art.
- **Renaming resets Music Assistant history.** Changing the naming language renames
  folders and files; favourites and play counts tied to old paths are lost.
- **Mujawwad and Mu'allim riwaya unknown.** The catalogue does not state which
  riwaya those recordings follow, so their album is the style alone.
- **Icon in HACS before 2026.11.** The HACS dashboard shows a placeholder icon for
  integrations that ship their icon locally; the Integrations page shows it correctly,
  and Marketplace (HA 2026.11+) fixes the dashboard.

## Troubleshooting

- **"Could not reach mp3quran.net" during setup.** The API answers at
  `https://www.mp3quran.net/api/v3/languages`; check DNS and outbound HTTPS.
- **Sync status is `error`.** The status sensor's `error` attribute and the
  diagnostics download list the failing tracks. A `302` redirect error means the
  catalogue listed a surah the server no longer has; it is skipped on purpose rather
  than saving another reciter's file.
- **Music Assistant shows two artists for one reciter.** Some files were tagged
  under an older naming option. Run `tilawa.retag`.
- **Files without tags from another tool in the same folder.** Tilawa never touches
  files that do not carry its `TXXX:TILAWA_*` tags.
- **Enable debug logging:** Settings → Devices & services → Tilawa → ⋮ → *Enable debug
  logging*, or in `configuration.yaml`:

  ```yaml
  logger:
    logs:
      custom_components.tilawa: debug
  ```

## Removing the integration

Settings → Devices & services → Tilawa → ⋮ → **Delete**. This removes the entities and
Tilawa's cached catalogue, index and job state. **Downloaded files are kept.** To
delete them first, remove each selection with `tilawa.remove_selection` and
`delete_files: true`, or answer *Delete the files* in the repair issue that appears
when a selection is deleted. Afterwards remove the folder from Music Assistant's
provider if you no longer want it scanned.

## Content source and attribution

All recitations are downloaded from **[mp3quran.net](https://mp3quran.net)** through
its public API. Their [privacy page](https://www.mp3quran.net/eng/privacy) states
under *Copyrights*: "All rights are available to everyone … we allow any visitor or
developer to copy any material or use any link on the websites." The recordings
themselves remain the work of the reciters. Tilawa is not affiliated with
mp3quran.net; if the library is useful to you, please visit and support the source,
and keep download parallelism modest.

## Development

```sh
uv sync --group dev          # test harness pinned to Home Assistant 2026.3.4
scripts/lint                 # ruff format --check, ruff check, mypy --strict
scripts/test                 # pytest with coverage
scripts/develop              # local Home Assistant Core with this integration
docker compose -f dev/docker-compose.yml up -d   # Music Assistant next to it
```

See `docs/api-notes.md` for what the mp3quran API really returns, `docs/design.md`
for the architecture, and `docs/publishing.md` for the release checklist.

## License

[MIT](LICENSE).
