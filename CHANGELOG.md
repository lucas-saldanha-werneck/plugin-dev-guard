# Changelog

All notable changes to this plugin. Versions follow `.claude-plugin/plugin.json`.

## 0.2.4 (2026-11-13)

- Add a README Examples heading.

## 0.2.3 (2026-11-12)

- Keep state writes working on Windows under contention.

## 0.2.2 (2026-11-12)

- Fix second audit findings.

## 0.2.1 (2026-11-11)

- Guard the plugins folder and its `cache/` and `marketplaces/` folders.

## 0.2.0 (2026-11-11)

- Warn first, then let the same edit through once; the repeat needs a message from the user after the warning.

## 0.1.3 (2026-11-11)

- Maintenance: point to the catalog repo's new name, lucas-tools.

## 0.1.2 (2026-11-11)

- Remind of the source repo when the pass file lets an edit through.

## 0.1.1 (2026-11-11)

- Maintenance: rename the marketplace to lucas-tools.

## 0.1.0 (2026-11-09)

- First release: stop edits to installed plugin copies and point to the source repo, or a fork and a pull request; adds `plugin-dev-check`.
