# mp3quran.net API notes

Live findings for the Tilawa integration, captured on **2026-10-19** with a read-only probe
script (aiohttp + mutagen, run with `uv run --with aiohttp --with mutagen`). Every statement
below comes from a recorded request; the `curl` equivalents are at the end so anyone can
re-check. Raw responses are trimmed into `tests/fixtures/`.

Nothing here is official documentation. The public API page is
<https://www.mp3quran.net/eng/api>; it lists endpoints and parameters but no terms, limits
or schema guarantees.

## 1. Transport

| Item | Finding |
|---|---|
| Base URL | `https://www.mp3quran.net/api/v3/` |
| Bare host | `https://mp3quran.net/api/v3/...` answers **301** to the `www.` host. Use `www.` directly. |
| Format | JSON, `content-type: application/json`. Top-level key names the collection (`reciters`, `suwar`, `riwayat`, `language`). |
| `language` | Codes from `/languages`: `ar` (default), `eng`, `fr`, `ru`, `de`, `es`, `tr`, `cn`, `th`, `ur`, `bn`, `bs`, `ug`, `fa`, `tg`, `ml`, `tl`, `id`, `pt`, `ha`, `sw`. `en` also returns English (undocumented alias); use `eng`. |
| Latency / size | 12–40 ms behind Cloudflare. `/reciters` is 161 KB (eng) / 193 KB (ar). Everything else is under 13 KB. |
| Caching | `/reciters`: `cache-control: public, max-age=86400, must-revalidate`. Others: `private, max-age=86400`. **No `ETag`**, so conditional GETs are not possible. |
| Errors | Unknown filter values are ignored, not rejected: `reciter=999999` returns all 243 reciters with HTTP 200. |

## 2. Endpoints

| Endpoint | Params | Returns |
|---|---|---|
| `/languages` | – | `language[]`: `id`, `language`, `native`, `locale`, plus per-language URLs for `surah`, `rewayah`, `reciters`, `radios`, `tafasir` |
| `/suwar` | `language` | `suwar[]`: `id`, `name`, `start_page`, `end_page`, `makkia`, `type` |
| `/riwayat` | `language` | `riwayat[]`: `id`, `name` |
| `/moshaf` | `language` | `riwayat[]`: `id`, `moshaf_type`, `moshaf_id`, `name` (undocumented; see 2.3) |
| `/reciters` | `language`, `reciter`, `rewaya`, `sura`, `last_updated_date` | `reciters[]`: `id`, `name`, `letter`, `date`, `moshaf[]` |

### 2.1 `/suwar`

- 114 entries, `id` 1…114 in order, identical ids in `ar` and `eng`.
- `makkia` is 1 for Makki, 0 for Madani; `type` is the inverse (0 Makki, 1 Madani). Counts: 86 Makki, 28 Madani.
- **English names need cleaning.** 109 of 114 have a trailing space (`"Al-Kahf "`), and five contain a
  **soft hyphen U+00AD** instead of a hyphen: `Ta­Ha`, `Ar­Room`, `As­Sajdah`, `Al­Ahzab`,
  `Ya­Sin`. Rule: strip, replace U+00AD with `-`, collapse double spaces.
- Arabic names are clean (`الفاتحة`, `البقرة`, `الكهف`, `يس`, `النبأ`, `الإخلاص`, `الناس`).

| id | ar | eng (raw) | pages |
|---|---|---|---|
| 1 | الفاتحة | `Al-Fatihah ` | 1–1 |
| 2 | البقرة | `Al-Baqarah ` | 2–49 |
| 18 | الكهف | `Al-Kahf ` | 293–304 |
| 36 | يس | `Ya­Sin ` | 440–445 |
| 78 | النبأ | `An-Naba' ` | 582–583 |
| 112 | الإخلاص | `Al-Ikhlas ` | 604–604 |
| 114 | الناس | `An-Nas` | 604–604 |

### 2.2 `/riwayat`

20 entries. Ids 14 and 17 do not exist. **Ids 21 and 22 are not riwayat**: they are mushaf
styles used as a stand-in when the recording's riwaya is not stated.

| id | eng (raw) | ar |
|---|---|---|
| 1 | Rewayat Hafs A'n Assem | حفص عن عاصم |
| 2 | Rewayat Warsh A'n Nafi' | ورش عن نافع |
| 3 | Rewayat Khalaf A'n Hamzah | خلف عن حمزة |
| 4 | Rewayat Albizi A'n Ibn Katheer | البزي عن ابن كثير |
| 5 | Rewayat Qalon A'n Nafi' | قالون عن نافع |
| 6 | Rewayat Qunbol A'n Ibn Katheer | قنبل عن ابن كثير |
| 7 | Rewayat Assosi A'n Abi Amr | السوسي عن أبي عمرو |
| 8 | Rewayat Qalon A'n Nafi' Men Tariq Abi Nasheet | قالون عن نافع من طريق أبي نشيط |
| 9 | `Rewayat Rowis and Rawh A'n Yakoob Al Hadrami ` (trailing space) | قراءة يعقوب الحضرمي بروايتي رويس وروح |
| 10 | `Rewayat Warsh A'n Nafi' Men  Tariq Abi Baker Alasbahani` (double space) | ورش عن نافع من طريق أبي بكر الأصبهاني |
| 11 | Rewayat Albizi and Qunbol A'n Ibn Katheer | البزي وقنبل عن ابن كثير |
| 12 | Rewayat AlDorai A'n Al-Kisa'ai | الدوري عن الكسائي |
| 13 | Rewayat Aldori A'n Abi Amr | الدوري عن أبي عمرو |
| 15 | Sho'bah A'n Asim | `شعبة  عن عاصم` (double space) |
| 16 | Ibn Thakwan A'n Ibn Amer | ابن ذكوان عن ابن عامر |
| 18 | Rewayat Warsh A'n Nafi' Men Tariq Alazraq | ورش عن نافع من طريق الأزرق |
| 19 | Hesham A'n Abi A'mer | هشام عن ابي عامر |
| 20 | Ibn Jammaz A'n Abi Ja'far | ابن جماز عن أبي جعفر |
| 21 | Almusshaf Al Mo'lim | المصحف المعلم |
| 22 | Almusshaf Al Mojawwad | المصحف المجود |

### 2.3 `/moshaf` (undocumented)

Returns `riwayat[]` with 27 rows. This is the lookup table for a reciter's `moshaf_type`:

- `id` here **equals `moshaf[].moshaf_type`** in `/reciters` (all 289 moshafs matched, and
  all 289 `name` values are identical to this table's `name`).
- The field confusingly called `moshaf_type` here is the **riwaya id** (`/riwayat.id`).
- `moshaf_id` is the **style id**: 1 Murattal, 2 Mujawwad, 3 Mu'allim, 4 Featured recitation,
  20 "Recorded in 1387 AH (1967 CE)".
- `id` is the decimal concatenation of the riwaya id and the style id (1+1 → 11, 1+20 → 120,
  22+2 → 222), so it is a lookup key, not something to compute from.
- `name` is `"<riwaya> - <style>"`, except styles 21/22 where both halves repeat the style.

| id | riwaya | style | eng | ar |
|---|---|---|---|---|
| 11 | 1 | 1 | Rewayat Hafs A'n Assem - Murattal | حفص عن عاصم - مرتل |
| 12 | 1 | 2 | Rewayat Hafs A'n Assem - Almusshaf Al Mojawwad | حفص عن عاصم - المصحف المجود |
| 13 | 1 | 3 | Rewayat Hafs A'n Assem - Almusshaf Al Mo'lim | حفص عن عاصم - المصحف المعلم |
| 14 | 1 | 4 | Rewayat Hafs A'n Assem - Featured Recitation | حفص عن عاصم - تلاوة مميزة |
| 120 | 1 | 20 | Rewayat Hafs A'n Assem - Recorded in 1387 AH (1967 CE) | حفص عن عاصم - تسجيل عام 1387 هـ - 1967م |
| 21 | 2 | 1 | Rewayat Warsh A'n Nafi' - Murattal | ورش عن نافع - مرتل |
| 31 | 3 | 1 | Rewayat Khalaf A'n Hamzah - Murattal | خلف عن حمزة - مرتل |
| 41 | 4 | 1 | Rewayat Albizi A'n Ibn Katheer - Murattal | البزي عن ابن كثير - مرتل |
| 51 | 5 | 1 | Rewayat Qalon A'n Nafi' - Murattal | قالون عن نافع - مرتل |
| 52 | 5 | 2 | Rewayat Qalon A'n Nafi' - Almusshaf Al Mojawwad | قالون عن نافع - المصحف المجود |
| 61 | 6 | 1 | Rewayat Qunbol A'n Ibn Katheer - Murattal | قنبل عن ابن كثير - مرتل |
| 71 | 7 | 1 | Rewayat Assosi A'n Abi Amr - Murattal | السوسي عن أبي عمرو - مرتل |
| 81 | 8 | 1 | Rewayat Qalon A'n Nafi' Men Tariq Abi Nasheet - Murattal | قالون عن نافع من طريق أبي نشيط - مرتل |
| 91 | 9 | 1 | Rewayat Rowis and Rawh A'n Yakoob Al Hadrami  - Murattal | قراءة يعقوب الحضرمي بروايتي رويس وروح - مرتل |
| 101 | 10 | 1 | Rewayat Warsh A'n Nafi' Men  Tariq Abi Baker Alasbahani - Murattal | ورش عن نافع من طريق أبي بكر الأصبهاني - مرتل |
| 111 | 11 | 1 | Rewayat Albizi and Qunbol A'n Ibn Katheer - Murattal | البزي وقنبل عن ابن كثير - مرتل |
| 121 | 12 | 1 | Rewayat AlDorai A'n Al-Kisa'ai - Murattal | الدوري عن الكسائي - مرتل |
| 131 | 13 | 1 | Rewayat Aldori A'n Abi Amr - Murattal | الدوري عن أبي عمرو - مرتل |
| 132 | 13 | 2 | Rewayat Aldori A'n Abi Amr - Almusshaf Al Mojawwad | الدوري عن أبي عمرو - المصحف المجود |
| 151 | 15 | 1 | Sho'bah A'n Asim - Murattal | شعبة  عن عاصم - مرتل |
| 152 | 15 | 2 | Sho'bah A'n Asim - Almusshaf Al Mojawwad | شعبة  عن عاصم - المصحف المجود |
| 161 | 16 | 1 | Ibn Thakwan A'n Ibn Amer - Murattal | ابن ذكوان عن ابن عامر - مرتل |
| 181 | 18 | 1 | Rewayat Warsh A'n Nafi' Men Tariq Alazraq - Murattal | ورش عن نافع من طريق الأزرق - مرتل |
| 191 | 19 | 1 | Hesham A'n Abi A'mer - Murattal | هشام عن ابي عامر - مرتل |
| 201 | 20 | 1 | Ibn Jammaz A'n Abi Ja'far - Murattal | ابن جماز عن أبي جعفر - مرتل |
| 213 | 21 | 3 | Almusshaf Al Mo'lim - Almusshaf Al Mo'lim | المصحف المعلم - المصحف المعلم |
| 222 | 22 | 2 | Almusshaf Al Mojawwad - Almusshaf Al Mojawwad | المصحف المجود - المصحف المجود |

Rows 12, 52, 132 and 152 exist in the table but no reciter uses them today. The 23 types
in use and their counts (eng): 11 ×216, 21 ×13, 51 ×11, 222 ×7, 121 ×6, 213 ×5, 131 ×5,
14 ×3, 151 ×3, 181 ×2, 161 ×2, 31 ×2, 71 ×2, 41 ×2, 91 ×2, and one each of 13, 61, 81, 101,
111, 120, 191, 201.

### 2.4 `/reciters`

- 243 reciters, 289 moshafs. Reciter ids and moshaf ids are **identical across languages**,
  so selections can be stored by id and names re-fetched in either language.
- Reciter fields: `id` (int), `name`, `letter` (first letter of the name in that language),
  `date` (ISO 8601 UTC, e.g. `2026-01-14T08:26:55.000000Z`), `moshaf[]`.
- Moshaf fields: `id` (int, globally unique, not per reciter), `name`, **`rewaya_id`** (int,
  `/riwayat.id`; not in the original spec), `server` (URL prefix), `surah_total` (int),
  `moshaf_type` (int, `/moshaf.id`), `surah_list` (comma-separated ascending surah numbers as
  one string, e.g. `"1,78,79,…"`). `len(surah_list.split(",")) == surah_total` for all 289.
- No image, photo or avatar fields anywhere. Confirmed: the API has no reciter images.
- `server`: 288 of 289 match `https://cdn.mp3quran.net/audio/<slug>/r<N>/`; the remaining one
  is `https://server15.mp3quran.net/a-rushdi/Almusshaf-Al-Mo-lim/` (Ayman Rushdi Swaid,
  moshaf 10925). **All 289 end with `/`** today. Still join defensively.
- **Partial moshafs are common**: 86 of 289 have fewer than 114 surahs (203 are complete,
  5 have 113, the rest range from 1 to 111). Example: Maher Al Meaqli moshaf 103 has 38
  surahs: `1,78,…,114`.
- No reciter has two moshafs with the same `(rewaya_id, moshaf_type)`, so album-name
  collisions are theoretical; a deterministic fallback is still needed.
- Names: English reciter names are pure ASCII with `-` and one `( )`. English moshaf names
  use `'` (327×) and `-`. One Arabic reciter name has a trailing space (`"ياسر المزروعي "`).
  Two English and one Arabic moshaf names contain double spaces. No `;`, `/`, " feat. " or
  similar separators appear in any reciter name, so Music Assistant will not split artists.
- Example, reciter 118 (eng `Mahmoud Khalil Al-Hussary`, ar `محمود خليل الحصري`), 5 moshafs:

| moshaf id | moshaf_type | rewaya_id | eng name | server |
|---|---|---|---|---|
| 118 | 11 | 1 | Rewayat Hafs A'n Assem - Murattal | `…/mahmoud-husary/r1/` |
| 119 | 222 | 22 | Almusshaf Al Mojawwad - Almusshaf Al Mojawwad | `…/mahmoud-husary/r2/` |
| 120 | 21 | 2 | Rewayat Warsh A'n Nafi' - Murattal | `…/mahmoud-husary/r3/` |
| 269 | 131 | 13 | Rewayat Aldori A'n Abi Amr - Murattal | `…/mahmoud-husary/r4/` |
| 270 | 51 | 5 | Rewayat Qalon A'n Nafi' - Murattal | `…/mahmoud-husary/r5/` |

Filters (all return the same shape):

| Query | Result |
|---|---|
| `reciter=118` | 1 reciter |
| `reciter=999999` | all 243 (unknown id is ignored, not an error) |
| `rewaya=2` | 13 reciters, 13 moshafs, all with `rewaya_id == 2`; other moshafs of those reciters are omitted |
| `sura=18` | 200 reciters / 232 moshafs, every one lists surah 18 |
| `last_updated_date=2020-01-01` | all 243 (oldest `date` in the catalogue is 2025-08-30) |
| `last_updated_date=2026-01-01` | 27 reciters, min `date` 2026-01-10 |
| `last_updated_date=2026-10-01` | 5 reciters, min `date` 2026-10-07 |

`last_updated_date` filters on the reciter-level `date` (inclusive, `>=`). Whether `date`
moves when a moshaf gains surahs could not be observed in one day. Because the full
`/reciters` response is under 200 KB, the integration should do a **full weekly fetch** and
diff locally; the filter is an optional optimisation only, and removals can only be detected
by a full fetch.

## 3. Audio files

### 3.1 URL pattern

`{server}{surah:03d}.mp3`, e.g. `https://cdn.mp3quran.net/audio/mahmoud-husary/r1/018.mp3`.

| Probe | Result |
|---|---|
| `…/r1/018.mp3` | 200 |
| `…/r1/18.mp3` (no zero padding) | 301 → `018.mp3` |
| `…/r1/000.mp3`, `…/r1/115.mp3` | 404 (`text/html`) |
| `https://server8.mp3quran.net/afs/018.mp3` (spec example) | 301 → `https://cdn.mp3quran.net/audio/mishary-alafasy/r1/018.mp3` |

### 3.2 Redirect trap for surahs outside `surah_list`

On the CDN, requesting a surah that a moshaf does **not** list returns a **302 to a
different reciter's file**. Verified on four partial moshafs:

| Moshaf | Missing surah requested | Response |
|---|---|---|
| Maher Al Meaqli 103 (`maher-muaiqly/r2`) | 002, 018 | 302 → `muhammad-minshawi/r3/…` |
| Majed Al-Enezi 100 (`majed-anazi/r1`) | 002 | 302 → `muhammad-minshawi/r1/002.mp3` |
| Mohammad Al-Airawy 104 (`muhammad-iraoui/r1`) | 005 | 302 → `mahmoud-husary/r3/005.mp3` |
| Mohammed Al-Barrak 105 (`muhammad-barrak/r1`) | 002 | 302 → `muhammad-minshawi/r1/002.mp3` |

Listed surahs on the same moshafs return 200 directly. Rules for the downloader:

1. Only request surahs present in `surah_list`.
2. Fetch audio with `allow_redirects=False`. Treat 302/303/307 as an error. Follow 301/308
   only when the target path ends with the same `NNN.mp3`, and log it.

### 3.3 Response headers (CDN)

```
HTTP/2 200
content-type: audio/mpeg
content-length: 45935480
accept-ranges: bytes
etag: "627d4144d263f3c53cb3b8382d97fcde"
last-modified: Sun, 27 Sep 2026 17:08:24 GMT
cache-control: public, max-age=31536000, immutable
server: cloudflare
```

- No `transfer-encoding: chunked` and no `content-encoding`, so `Content-Length` is the exact
  file size and can be verified after download.
- `Last-Modified` of 2026-09-27 on every CDN sample shows the whole catalogue was re-uploaded
  recently. **Files do change upstream**; storing the `ETag` per file allows change detection.
- The legacy host `server15.mp3quran.net` differs: nginx-style `etag: "6acb6ca4-2ba72d2"`,
  `cache-control: public, max-age=180`, `Last-Modified` 2026-10-11. Range works there too (206).

### 3.4 Range and conditional requests (Hussary Hafs 018, 45,935,480 bytes)

| Request | Response |
|---|---|
| `Range: bytes=0-1023` | 206, `content-range: bytes 0-1023/45935480`, 1024 bytes |
| `Range: bytes=1000000-` | 206, `content-range: bytes 1000000-45935479/45935480` |
| `Range: bytes=0-1023` + `If-Range: <etag>` | 206 (resume is safe when the ETag still matches) |
| `If-None-Match: <etag>` | 304 |
| `Range: bytes=999999999-` | 416, `content-range: bytes */45935480` |

Resumable downloads are fully supported: resume with `Range: bytes=<have>-` plus
`If-Range: <etag>`; a 200 instead of 206 means the file changed and must restart.

### 3.5 Existing ID3 tags in the source files (first 256 KiB, mutagen)

| Sample | ID3 | Frames | MPEG |
|---|---|---|---|
| Mishary Alafasi, Hafs (`mishary-alafasy/r1/018`) | v2.4.0 | `TIT2=Al-Kahf`, `TPE1=Mishary Alafasi`, `TALB=Mishary Alafasi Musshaf`, `TCON=Quran`, `TDRC=2007`, `TSSE=Lavf59.27.100`, `TXXX:comment=www.mp3quran.net`, `APIC` 6.6 KB PNG | 128 kbps, 44.1 kHz, stereo |
| Al-Hussary, Hafs (`mahmoud-husary/r1/018`) | v2.3.0 | `TIT2=Al-Kahf`, `TPE1=Mahmoud Khalil Al-Hussary`, **`TPE2=www.mp3quran.net`**, `TALB=Mahmoud Khalil Al-Hussary Musshaf`, `TCON=Quran`, `TDRC=2013`, `COMM=www.mp3quran.net`, `APIC` 23 KB JPEG | 128 kbps, 44.1 kHz, stereo |
| Al-Hussary, Mujawwad (`mahmoud-husary/r2/018`) | v2.4.0 | `TIT2=Al-Kahf`, `TPE1=Mahmmoud  Khalil Al-Husary` (sic), `TALB=… Musshaf Mojawad`, `TCON=Quran`, `TDRC=2008`, `APIC` 6.6 KB PNG | 96 kbps, 24 kHz, stereo |
| Ayman Swaid, Mu'allim (`server15…/018`) | v2.3.0 | `TIT2=018 - Al-Kahf (The Cave) سورة الكهف`, `TPE1=Ayman Rushdi Swaid - القارئ أيمن رشدي سويد`, `TALB=Musshaf Mo'lim - المصحف المعلم`, `TPOS=" "`, `TDRC=1447`, `TCOP=www.islamway.net@2020`, `TXXX:Engineer=…`, `APIC` 23 KB JPEG | VBR ≈118 kbps, 48 kHz, stereo |

Consequences: tags are inconsistent (v2.3 vs v2.4, bilingual vs English, misspellings),
`TPE2` is sometimes the website name (Music Assistant would create an album artist
"www.mp3quran.net"), titles have no surah number, and every file carries an embedded
cover (the site's logo). The integration must **strip all existing tags** and write its own,
as the spec requires. No `TRCK`, `TPOS` (except a blank), `TXXX` identifiers or sort tags exist.

### 3.6 Storage measurements (sum of `Content-Length` over all listed surahs)

| Moshaf | Files | Bitrate | Total | Juz' Amma (78–114) | Largest (Al-Baqarah) | Smallest |
|---|---|---|---|---|---|---|
| Mishary Alafasi, Hafs Murattal (123) | 114 | 128 kbps | 1,718,021,595 B = **1.60 GiB** | 58.1 MiB | 120.6 MB | 354 KB (112) |
| Al-Hussary, Hafs Murattal (118) | 114 | 128 kbps | 2,470,339,875 B = **2.30 GiB** | 82.1 MiB | 191.3 MB | 546 KB (108) |
| Al-Hussary, Mujawwad (119) | 114 | 96 kbps | 2,689,038,859 B = **2.50 GiB** | 89.7 MiB | 211.5 MB | 577 KB (108) |

Rule of thumb for the README: a complete murattal moshaf is 1.5–2.5 GiB, Juz' Amma alone
60–90 MiB, and Al-Baqarah is 7–8 % of the total. 342 HEAD requests at concurrency 4
completed with zero errors and no throttling signs.

## 4. Naming data for the album derivation (input to step 2)

Raw material the design must map to short album names. The riwaya part comes from
`rewaya_id`, the style part from `moshaf_type % 10` (or the `/moshaf` row), never from
parsing the display name, which is only a fallback.

| rewaya_id | Short (eng) | Short (ar) |
|---|---|---|
| 1 | Hafs | حفص |
| 2 | Warsh | ورش |
| 3 | Khalaf | خلف |
| 4 | Al-Bazzi | البزي |
| 5 | Qalun | قالون |
| 6 | Qunbul | قنبل |
| 7 | As-Susi | السوسي |
| 8 | Qalun (Abu Nashit) | قالون (أبي نشيط) |
| 9 | Ruways & Rawh | رويس وروح |
| 10 | Warsh (Al-Asbahani) | ورش (الأصبهاني) |
| 11 | Al-Bazzi & Qunbul | البزي وقنبل |
| 12 | Ad-Duri (Al-Kisa'i) | الدوري (الكسائي) |
| 13 | Ad-Duri (Abu Amr) | الدوري (أبي عمرو) |
| 15 | Shu'bah | شعبة |
| 16 | Ibn Dhakwan | ابن ذكوان |
| 18 | Warsh (Al-Azraq) | ورش (الأزرق) |
| 19 | Hisham | هشام |
| 20 | Ibn Jammaz | ابن جماز |
| 21 | *(none; style Mu'allim)* | – |
| 22 | *(none; style Mujawwad)* | – |

| style id | Short (eng) | Short (ar) |
|---|---|---|
| 1 | Murattal | مرتل |
| 2 | Mujawwad | مجود |
| 3 | Mu'allim | معلم |
| 4 | Featured | تلاوة مميزة |
| 20 | 1967 recording | تسجيل 1967 |

Examples this yields: `Hafs – Murattal`, `Warsh – Murattal`, `Mujawwad` (riwaya unknown,
type 222), `Mu'allim` (type 213), `Hafs – Mu'allim` (type 13), `Hafs – Featured` (type 14),
`Hafs – 1967 recording` (type 120). The spec's example "Hafs – Mujawwad" is only correct for
type 12, which no reciter currently uses; type 222 must not claim Hafs. Final spellings are a
step-2 decision; the unit tests will use the 23 raw names above as input.

Normalisation rules derived from the data: `str.strip()`, collapse runs of spaces, replace
U+00AD with `-`, apply to reciter names, moshaf names and surah names in both languages.

## 5. Terms of use and attribution

- The API page <https://www.mp3quran.net/eng/api> publishes no terms, rate limits or
  attribution rules.
- The privacy page <https://www.mp3quran.net/eng/privacy> states under **Copyrights**:
  "All rights are available to everyone … we allow any visitor or developer to copy any
  material or use any link on the websites." The Arabic version says the same.
- The About pages (eng/ar) contain no licensing statement; the site advertises "direct
  download links for the Quranic surahs in high quality".
- The source files' own tags point at `www.mp3quran.net` (and one at `www.islamway.net`),
  i.e. the site redistributes recordings whose rights sit with the reciters or original
  publishers. The README should attribute mp3quran.net, link the policy above, state that
  Tilawa is not affiliated with mp3quran.net, and ask users to support the source.

## 6. Implementation rules distilled from the above

1. Use `https://www.mp3quran.net/api/v3/` and `language=ar|eng`; follow redirects for the
   API only.
2. Store selections as `(reciter_id, moshaf_id)`; look names up in the chosen language.
3. Album naming keys on `rewaya_id` and `moshaf_type`; `/moshaf` is the authoritative table.
4. Clean every display string: strip, collapse spaces, replace U+00AD.
5. Build file URLs as `{server.rstrip('/')}/{n:03d}.mp3`, only for `n` in `surah_list`.
6. Audio requests: `allow_redirects=False`; reject 302/303/307; accept 301/308 only to the
   same `NNN.mp3`; verify `Content-Length`; resume with `Range` + `If-Range: <etag>`.
7. Store `etag` and `content-length` per file (in `TXXX` and the `.storage` index) to detect
   upstream replacements.
8. Strip all existing ID3 frames before writing ours (covers included).
9. Weekly full `/reciters` fetch (both languages, under 400 KB total) and local diff; the
   `last_updated_date` filter is optional.
10. Send a descriptive `User-Agent` and keep default concurrency at 2.

## 7. Open points not verifiable in one session

- Whether reciter `date` changes when a moshaf gains surahs (needed for "new surahs appear
  upstream"); the full-fetch diff covers it regardless.
- CDN rate limits under sustained full-moshaf downloads (none seen at 4 concurrent HEADs).
- Longevity of the single legacy `server15` host; the code treats it like any other prefix.
- Quality of the other 19 languages' names; Tilawa exposes `ar` and `eng` only.
- Music Assistant's behaviour on these specific tags is checked in the manual test plan.

## 8. Reproduce with curl

```sh
B=https://www.mp3quran.net/api/v3
curl -sI https://mp3quran.net/api/v3/suwar | grep -i -E '^(HTTP|location)'          # 301 to www
curl -s "$B/languages" | python3 -c 'import json,sys;[print(l["locale"]) for l in json.load(sys.stdin)["language"]]'
curl -s "$B/suwar?language=eng"   | python3 -c 'import json,sys;print([s["name"] for s in json.load(sys.stdin)["suwar"] if s["id"] in (18,36)])'
curl -s "$B/riwayat?language=eng" | python3 -m json.tool
curl -s "$B/moshaf?language=eng"  | python3 -m json.tool
curl -s "$B/reciters?language=eng&reciter=118" | python3 -m json.tool
curl -s "$B/reciters?language=eng&last_updated_date=2026-10-01" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["reciters"]))'
U=https://cdn.mp3quran.net/audio/mahmoud-husary/r1/018.mp3
curl -sI "$U"                                   # 200, content-length, accept-ranges, etag, last-modified
curl -s -r 0-1023 -o /dev/null -w '%{http_code}\n' "$U"    # 206
curl -sI https://cdn.mp3quran.net/audio/maher-muaiqly/r2/002.mp3 | grep -i -E '^(HTTP|location)'   # 302 to another reciter
curl -sI https://server8.mp3quran.net/afs/018.mp3 | grep -i -E '^(HTTP|location)'                   # legacy 301 to CDN
curl -s -r 0-262143 "$U" -o /tmp/head.mp3 && uv run --with mutagen python -c 'from mutagen.id3 import ID3;print(ID3("/tmp/head.mp3").pprint())'
```

## 9. Fixtures

`tests/fixtures/` holds trimmed copies generated from the raw responses captured on
2026-10-19: `suwar_ar.json`, `suwar_eng.json`, `riwayat_ar.json`, `riwayat_eng.json`,
`moshaf_ar.json`, `moshaf_eng.json`, `languages.json` (ar and eng rows only), and
`reciters_ar.json` / `reciters_eng.json` limited to reciters 100 (partial, 113 surahs),
102 (partial, 38 surahs), 118 (five moshafs), 123 (Alafasi) and 21203 (legacy host).
