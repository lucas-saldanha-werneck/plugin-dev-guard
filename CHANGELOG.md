# Changelog

All notable changes to this plugin. Versions follow `.claude-plugin/plugin.json`.

## 0.2.4 (2026-11-13)

- Add a README Examples heading.

## 0.2.3 (2026-11-12)

- Keep state writes working on Windows under contention: retry the lock and the file replace instead of going on without them.

## 0.2.2 (2026-11-12)

- Claude cannot give itself a pass: writing the pass file needs the user's answer, and tools cannot write the hook's state files.
- A repeat goes through only for the same call in the same session; state files are written atomically under a lock.
- Better parsing (`$(...)` and backticks inside double quotes) and case-insensitive path matching on macOS.
- `plugin-dev-check` checks every installation of a plugin.

## 0.2.1 (2026-11-11)

- Guard the plugins folder and its `cache/` and `marketplaces/` folders.
- The repeat needs a message from the user after the warning.

## 0.2.0 (2026-11-11)

- Warn first, then let the same edit through once.

## 0.1.3 (2026-11-11)

- Points to the catalog repo's new name, `lucas-tools`.

## 0.1.2 (2026-11-11)

- Remind of the source repo when the pass file lets an edit through.

## 0.1.1 (2026-11-11)

- Catalog renamed to `lucas-tools`.

## 0.1.0 (2026-11-09)

- First release: stop edits to installed plugin copies and point to the source repo, or a fork and a pull request; adds `plugin-dev-check`.
