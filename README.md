# Tilawa

**Quran recitations from mp3quran.net, downloaded and tagged for Music Assistant.**

[![Release](https://img.shields.io/github/v/release/amaharek/tilawa)](https://github.com/amaharek/tilawa/releases)
[![Tests](https://github.com/amaharek/tilawa/actions/workflows/tests.yml/badge.svg)](https://github.com/amaharek/tilawa/actions/workflows/tests.yml)
[![HACS](https://img.shields.io/badge/HACS-custom%20repository-41BDF5)](https://github.com/hacs/integration)

[العربية](README.ar.md)

Tilawa (تلاوة, "recitation") is a [Home Assistant](https://www.home-assistant.io/)
integration. You choose reciters, it downloads their recordings from
[mp3quran.net](https://mp3quran.net) into your media folder and writes clean tags, and
[Music Assistant](https://www.music-assistant.io/) shows them like any music library:

- **Artist** is the reciter, for example Abdul Basit Abdul Samad.
- **Album** is the riwaya and style, for example Hafs – Murattal or Mujawwad.
- **Track** is the surah, numbered 001 to 114.

Searching for **الكهف** or **Al-Kahf** in Music Assistant finds Surah Al-Kahf in every
version you have downloaded. The files live on your disk, play offline, and are never
deleted unless you ask.

> Tilawa is an independent community project. It is not affiliated with mp3quran.net,
> Home Assistant or Music Assistant.

## Requirements

- Home Assistant 2026.3.0 or newer. No extra Python packages are needed.
- Music Assistant with a **Filesystem (local disk)** provider pointing at the library
  folder. Setting that up is described below.
- Disk space: a complete recording of the Quran takes 1.5 to 2.5 GB. Juz' Amma alone
  (surahs 78 to 114) takes 60 to 90 MB.

## Installation

**With HACS**

1. In HACS open ⋮ → **Custom repositories** and add `https://github.com/amaharek/tilawa`
   with type *Integration*, or click the badge below.
2. Search for **Tilawa**, download it, and restart Home Assistant.
3. Go to Settings → Devices & services → **Add integration** → Tilawa.

[![Open this repository in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=amaharek&repository=tilawa&category=integration)

From Home Assistant 2026.11, HACS is built in as Settings → **Marketplace**. Use
*Add from link* with `amaharek/tilawa`, then continue with step 3.

**Manually**: copy `custom_components/tilawa` from the
[latest release](https://github.com/amaharek/tilawa/releases) into
`config/custom_components/` and restart Home Assistant.

## Setup

The wizard has four steps:

1. **Library folder.** `/media/Quran` by default. Tilawa creates it if needed and shows
   the free space. A folder outside your media folders has to be listed in
   `allowlist_external_dirs`.
2. **Names.** Arabic or English for reciter and album names, the track title format,
   and what goes between the number and the name (`018 الكهف`, `018- الكهف` or
   `018 - الكهف`).
3. **Reciter.** Pick one from the full mp3quran catalogue.
4. **Version.** Pick the riwaya and style. The number in brackets is how many surahs
   that version offers. **Download all surahs** is on by default. Switch it off to
   enter a range such as `78-114` for Juz' Amma or `1, 36, 67`.

Downloading starts as soon as you finish.

### Connect Music Assistant

Tilawa only writes files. Music Assistant has to be told once where they are:

1. In Music Assistant open Settings → Providers → **Add provider** → Filesystem
   (local disk).
2. Enter the path `/media/Quran` and save.
3. Press **Sync** on that provider. Music Assistant also rescans on its own schedule,
   but it does not notice new files instantly, and Tilawa cannot trigger it.

Where the folder is, depending on your setup:

- **HA OS or Supervised with the Music Assistant add-on.** The add-on already sees
  `/media`, so `/media/Quran` works on both sides.
- **Docker.** Mount the same host folder at `/media` in both the Home Assistant and the
  Music Assistant container.
- **HA Core in a venv.** Use a folder listed under `media_dirs` and give Music Assistant
  the same absolute path.

## Everyday use

**More reciters.** On the Tilawa integration page press **Add reciter**. Each reciter
version is its own entry with its own surah range. Its ⋮ menu offers **Change surah
range**. Deleting the entry keeps the files and opens a Repair that lets you delete them.

**Options.** Settings → Devices & services → Tilawa → **Configure**:

- Reciter and album names, track title and separator, as in setup. Changing any of
  these retags and renames the files in place without downloading again. Music
  Assistant then sees them as new items, so favourites and play counts tied to the old
  names are lost.
- Parallel downloads (2 by default, up to 4) and a bandwidth limit in kB/s. Please keep
  both modest; mp3quran is a free service.
- Automatic sync: off, daily, or weekly at 03:00 local time (weekly runs on Mondays).
- Re-download files that changed upstream. Off by default.

**Moving the library.** ⋮ → **Reconfigure** changes the folder and can move the existing
files. The move runs in the background and survives a restart.

**Entities.** One device named Tilawa with:

- Sync status (idle, syncing, retagging, moving or error) with the current track and
  counts as attributes, and Sync progress in percent.
- Files, Library size, Last successful sync and Reciters as diagnostic sensors, plus a
  connectivity sensor for mp3quran.net.
- Buttons Sync now and Cancel sync.

**Actions.** `tilawa.sync`, `tilawa.add_selection`, `tilawa.remove_selection` (with
`delete_files`) and `tilawa.retag`. They use mp3quran's reciter and version ids, listed
in the [catalogue](https://www.mp3quran.net/api/v3/reciters?language=eng). Some examples:

- Abdul Basit Abdul Samad is reciter 51 with versions 53 (Hafs – Murattal),
  52 (Warsh – Murattal) and 51 (Mujawwad).
- Mahmoud Khalil Al-Hussary is reciter 118 with versions 118 (Hafs), 119 (Mujawwad),
  120 (Warsh), 269 (Ad-Duri) and 270 (Qalun).
- Mahmoud Ali Al-Banna is reciter 121 with versions 121 (Hafs) and 122 (Mujawwad).

```yaml
# Add Juz' Amma recited by Mahmoud Ali Al-Banna
action: tilawa.add_selection
data:
  reciter_id: 121
  moshaf_id: 121
  surahs: "78-114"
```

```yaml
# Bedtime: queue Surah Al-Mulk through Music Assistant
action: music_assistant.play_media
target:
  entity_id: media_player.bedroom
data:
  media_type: track
  media_id: "067 الملك"
  artist: عبدالباسط عبدالصمد
  album: حفص – مرتل
  enqueue: add
```

## Files and tags

```
/media/Quran/عبدالباسط عبدالصمد/حفص – مرتل/018 الكهف.mp3
```

Every file carries ID3v2.4 tags. Artist and album artist are the reciter, album is the
riwaya and style, title is the numbered surah, track number is the surah out of 114,
and genre is Quran. English transliterations go into the sort tags, so A to Z ordering
and English search work even with Arabic display names. Tilawa also stores its own ids
in private tags. That is how it recognises its files after a rename, and why it never
touches files it did not create.

Album names come from the catalogue's riwaya and style ids: Hafs, Warsh, Qalun, Khalaf,
Ad-Duri and others, combined with Murattal, Mujawwad, Mu'allim or Featured. Where the
catalogue does not state the riwaya, as for Mujawwad and Mu'allim recordings, the style
alone is used.

## Good to know

- Tilawa downloads only what a reciter actually recorded. Partial recordings are
  common, and the surah count is shown next to each version.
- It builds a local library and does not stream. A Home Assistant media player that
  accepts a URL can still play a file straight from `https://cdn.mp3quran.net/…`
  without Tilawa.
- mp3quran occasionally replaces files. Enable *Re-download files that changed
  upstream* if you want those picked up.
- Before Home Assistant 2026.11 the HACS dashboard shows a placeholder icon for Tilawa.
  The Integrations page shows the right one.
- Deleting the integration removes its entities and cached data and keeps the files.

## Troubleshooting

- **Setup says mp3quran.net cannot be reached.** The API lives at
  `https://www.mp3quran.net/api/v3/`. Check DNS and outbound HTTPS from Home Assistant.
- **The folder is "not allowed".** Add it to `allowlist_external_dirs` in
  `configuration.yaml` and restart.
- **Nothing shows in Music Assistant.** Check the provider path and press Sync on it.
- **Sync status is error.** The status sensor's `error` attribute and ⋮ → Download
  diagnostics name the failing tracks. Repair issues appear for a full disk or an
  unwritable folder.
- **Two artists for one reciter in Music Assistant.** Some files still carry an older
  naming option. Run `tilawa.retag`.
- **Debug logging.** Tilawa → ⋮ → Enable debug logging.

## Source and attribution

All recitations come from [mp3quran.net](https://mp3quran.net) through its public API.
Its [privacy page](https://www.mp3quran.net/eng/privacy) states under *Copyrights* that
any visitor or developer may copy its material and use its links. The recordings remain
the work of the reciters. If the library is useful to you, visit and support the source,
and keep download parallelism modest.

## Development

```sh
uv sync --group dev   # test harness pinned to Home Assistant 2026.3.4
scripts/lint          # ruff format --check, ruff check, mypy --strict
scripts/test          # pytest with coverage
scripts/develop       # local Home Assistant Core with this integration
```

Design notes are in `docs/design.md`, API findings in `docs/api-notes.md`, and the
release checklist in `docs/publishing.md`.

## License

[MIT](LICENSE)
