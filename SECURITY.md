# Security policy

## Reporting a vulnerability

Please report security problems privately: open the **Security** tab of this repository and choose
**Report a vulnerability** (GitHub private vulnerability reporting). Please do not open a public issue
for a security problem. You will get an answer in the same thread.

## Supported versions

Only the latest release is supported. Fixes land in a new release; older versions are not patched.

## What this plugin accesses

- **Files it reads:** the path or command of each Edit, Write or Bash tool call, the plugin install records under `~/.claude/plugins/`, and its settings file `~/.config/plugin-dev-guard/config.json`.
- **Files it writes:** its settings file (created once when missing) and small state files (a pass file, a warned list, a lock) under `~/.claude/state/`.
- **Programs it starts:** `git -C <folder>` with a 60 second timeout, to find the source repo of a plugin. Nothing else.
- **Network:** none. A plugin's GitHub address is read from local install records and only printed in the message to Claude.
