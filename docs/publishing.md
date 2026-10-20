# Publishing checklist

Tilawa is distributed through the HACS catalogue, which Home Assistant 2026.11+ reads
as **Settings → Marketplace** and older releases read through the HACS integration.
Publishing requirements are documented at
<https://contributors.home-assistant.io/marketplace/> (catalogue:
<https://contributors.home-assistant.io/marketplace/guides/catalog/>).

## Before the first release

- [x] Placeholders filled in (owner `amaharek`, licence holder Abdelrahman Maharek):
      `manifest.json` (`codeowners`, `documentation`, `issue_tracker`), `const.py`
      (`REPO_URL`), `lib/api.py` (User-Agent), `README.md`, `README.ar.md`, `LICENSE`,
      `docs/design.md`, this file.
- [ ] Create the **public GitHub repository**, with:
  - a description (e.g. "Home Assistant integration that builds a tagged Quran
    recitation library for Music Assistant from mp3quran.net");
  - **Issues enabled**;
  - topics: `home-assistant`, `hacs`, `hacs-integration`, `quran`, `music-assistant`;
  - the MIT licence detected by GitHub (the `LICENSE` file is a verbatim MIT text, so
    GitHub shows "MIT", not `NOASSERTION`).
- [ ] Push `main`; confirm the **Validate** workflow (HACS action + hassfest) and the
      **Tests** workflow are green with no `ignore` inputs.
- [ ] Bump `version` in `manifest.json`, commit, and tag `vX.Y.Z` (same number). The
      **Release** workflow checks the match and creates a full GitHub release with
      generated notes. A bare tag is not enough for HACS/Marketplace.
- [ ] Install from the release on a real Home Assistant through *Add from link* /
      custom repository and run the manual test plan in `docs/design.md`.

## Default catalogue (HACS / Marketplace)

The catalogue is still maintained in <https://github.com/hacs/default>.

1. Fork `hacs/default`, create a branch from `master`.
2. Add `amaharek/tilawa` to the `integration` file in alphabetical order.
3. Open the pull request **from a personal account** (not an organisation) so the HACS
   team can edit it, and complete the whole template: checklist, link to the latest
   release, link to a passing HACS action run (no `ignore`), link to a passing hassfest
   run.
4. Automated checks cover brands (the local `brand/icon.png` satisfies it), manifest,
   HACS validation, archive status, releases, ownership and repository settings. Expect
   the human review to take months; the backlog is public.
5. Until then users add the repository from the My link badge in the README
   (`hacs_repository`, works on HACS and Marketplace).

## What hassfest and the HACS action check here

- `manifest.json` keys sorted (`domain`, `name`, then alphabetical), `version` present,
  `documentation` and `issue_tracker` URLs, requirements resolvable.
- `translations/en.json` consistent with the flows, `services.yaml` matching the
  registered actions, `icons.json` valid.
- `hacs.json` with `name`; `brand/icon.png` present; repository description, topics,
  issues, licence.
- Domain `tilawa` must not collide with a core integration (it does not today).

## Releasing updates

1. Change code, update `docs/` if behaviour changed, run `scripts/lint` and
   `scripts/test`.
2. Bump `manifest.json` `version`, tag `vX.Y.Z`, push the tag.
3. The catalogue data is regenerated every few hours; custom-repository users get the
   update through GitHub within two days.
