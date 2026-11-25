# Changelog

What changed in each release of RWE Workbench, newest first. A release is a `vX.Y.Z` tag on `main` with a GitHub release; [Deploy the app](infra/terraform/README.md#deploy-the-app) says how one is cut. Merged work waiting for the next release is under Unreleased. Everything before `v0.1.0` was deployed from `main` without tags; [How it got here](docs/HISTORY.md) covers it.

## Unreleased

### Added

- This changelog, linked from the README; the version-bump pull request moves Unreleased under the new version (#77).
- The README links the live demo (#79).

### Changed

- The deploy runbook deploys releases: a `vX.Y.Z` tag and a GitHub release, the image built from the tag, and rollback to the image tag recorded in the previous release's notes (#76).

## v0.1.0 (2026-11-24)

First tagged release, with help for visitors on every page. Image `e2ce8d8`.

### Added

- A "?" beside each page title, figure, and table explains that part of the page in a panel docked at the right. With help on, the panel opens on the page's own note at the start of a visit, follows to each page, and closes from its X or the header help switch (#71, #72, #73).
- Acronyms in the notes are glossary terms: hover, focus, or tap shows the full name and a short definition, and each note lists its terms at the end (#73, #75).
- A one-time hint on a first visit points at the help switch (#74).
- The footer shows the release date in the visitor's timezone (#71).

### Changed

- The header and section tabs stay at the top while the page scrolls (#73).
- Each "?" is sized to the text beside it, with a 24px tap area (#74).
- The lab notebook subtitle no longer implies the page shows the OMOP and FHIR writes (#72).

### Fixed

- Variant curation: the "differ from panel" filter compared class spellings; it now compares the three agreement tiers. The public demo says up front that decisions are off (#71).
- Synthetic data: the noise-floor wording, the AWS commands in empty states, and readable spec headings (#71).
- Trial emulation: "not estimable" wording covers models that fail to converge; the module doc has the right negative control counts and the current estimates (#71).
- Data quality: shows DQD 2.9.1, the version installed (#71).
