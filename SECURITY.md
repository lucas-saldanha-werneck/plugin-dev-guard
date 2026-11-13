# Security policy

## Reporting a vulnerability

Please report security problems privately: open the **Security** tab of this repository and choose
**Report a vulnerability** (GitHub private vulnerability reporting). Please do not open a public issue
for a security problem. You will get an answer in the same thread.

## Supported versions

Only the latest release is supported. Fixes land in a new release; older versions are not patched.

## What this plugin accesses

- **What it does:** a PreToolUse hook on Edit, Write, MultiEdit, NotebookEdit and Bash that refuses (denies) a call that would write into an installed plugin copy under `~/.claude/plugins/` (or an install dir you list), or into its own state files. It lets the same call through once after you answer in a new message, or for `pass_minutes` after you approve a pass file. A UserPromptSubmit hook only records when you last sent a message (session id and time, not the text).
- **Files it reads:** the path or command of those tool calls, the plugin records under `~/.claude/plugins/` (`known_marketplaces.json`, `installed_plugins.json`, catalog and `plugin.json` files), your source repos listed in `sources`, and its settings file `~/.config/plugin-dev-guard/config.json` (or `$XDG_CONFIG_HOME/...`, or `PLUGIN_DEV_GUARD_CONFIG`). `CLAUDE_CONFIG_DIR` replaces `~/.claude`.
- **Files it writes:** its settings file (created once when missing) and state files under `~/.claude/state/` (a warned list, a list of prompt times per session, a lock). The pass file there is created only by a command you approve.
- **Programs it starts:** the hook runs `git -C <folder> remote get-url origin` (60 second timeout) to find a plugin's repo. The `plugin-dev-check` command, which you run yourself, runs read-only `git` commands in your source repos and install dirs and walks the folders in `scan_dirs`.
- **Network:** the hook makes none; a plugin's GitHub address is read from local records and only printed in the message to Claude. `plugin-dev-check --fetch` runs `git fetch` in each source repo, which contacts that repo's remote.
