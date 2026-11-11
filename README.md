# plugin-dev-guard

A Claude Code hook that stops Claude from editing the installed copy of a plugin, and tells
it where the change belongs: your source repo when you have one on this machine, or a clone
or fork of the plugin's repo and a pull request to its author.

Claude Code runs plugins from a copy under `~/.claude/plugins/cache/` (and keeps catalog
clones under `~/.claude/plugins/marketplaces/`). The next plugin update replaces that copy,
so a fix made there is lost, and nobody else ever gets it. Claude still edits it often,
because that is the file it saw running.

The plugin also ships `plugin-dev-check`, a command that lists your source repos next to
their installed copies and says which ones are out of step.

## Example

Claude tries to edit a hook inside the installed copy. The edit is not made; Claude gets this
tool error instead:

```
plugin-dev-guard: this changes the INSTALLED copy of give-up-guard (~/.claude/plugins/cache/lucas-tools/give-up-guard/0.3.1/hooks/guard.py). That copy is replaced on the next plugin update, so the change would be lost.
- give-up-guard: its source repo is on this machine: ~/code/give-up-guard. Make the change there (branch, commit, bump the version in .claude-plugin/plugin.json, push), then update the installed plugin from it.
Exception (a quick test or one-off fix): end your turn and ask the user, saying what this changes. Only after the user answers yes in a new message, make the SAME edit again: it goes through once (within 30 minutes). A repeat before the user's next message is blocked again. For several files at once, run `mkdir -p "~/.claude/state" && touch "~/.claude/state/plugin-dev-guard.pass"` instead (a pass for every installed copy, same time limit).
```

For a plugin with no local source repo (someone else's, or yours on another machine), the
line points to its repo instead:

```
- superpowers: no local source repo found. Clone or fork https://github.com/obra/superpowers, make the change there and open a pull request to its author. Never patch the installed copy.
```

(The real message shows full paths; `~` is used here for short lines.)

`plugin-dev-check` in a terminal:

```
repo              branch  dirty  not pushed  installed                              installed vs main
give-up-guard     main    0      0           give-up-guard@lucas-tools 0.3.1      = main
wait-loop-guard   fix/x   2      1           wait-loop-guard@lucas-tools 0.2.1    behind main by 3

Fix:
  - wait-loop-guard: installed copy 1a2b3c4 is behind main 5d6e7f8 (bump the version, then `claude plugin marketplace update lucas-tools` and `claude plugin update wait-loop-guard@lucas-tools`)
  - wait-loop-guard: 1 commit(s) on fix/x not pushed
```

## Install

In Claude Code:

```
/plugin marketplace add lucas-saldanha-werneck/lucas-tools
/plugin install plugin-dev-guard@lucas-tools
```

Then run `/reload-plugins` or start a new session to load the hook.

## Settings

Your own settings live outside the plugin, in a file that plugin updates never touch:

- `~/.config/plugin-dev-guard/config.json` (or `$XDG_CONFIG_HOME/plugin-dev-guard/config.json` when
  `XDG_CONFIG_HOME` is set; on Windows `~` is your user folder, `%USERPROFILE%`)
- or any file named by the environment variable `PLUGIN_DEV_GUARD_CONFIG` (absolute path; `~` is expanded)

You don't have to create it: the first session after you install the plugin (or the first run
of `plugin-dev-check`) creates it, a copy of [`config.example.json`](config.example.json) with
every key at its default and a `_doc` note on each key. If the file is already there, it is
never rewritten. A missing or broken file, or a value of the wrong type, means the defaults.

With no settings at all the hook already works: it stops edits to every installed plugin and
points Claude to the plugin's repo. Tell it where your source repos are so it can point to
them instead:

```json
{
  "owner": "octocat",
  "sources": "~/code/plugins",
  "install_dirs": {"my-cli": "~/.local/share/my-cli-src"},
  "exempt": ["~/.local/share/my-cli-src/logs"]
}
```

| Key | Default | Effect |
| --- | --- | --- |
| `owner` | `""` | your GitHub account. With `marketplaces` at `"auto"`, a marketplace whose GitHub repo belongs to it counts as yours. `plugin-dev-check` also uses it with `scan_dirs` |
| `marketplaces` | `"auto"` | which marketplaces are yours: `"auto"` (every marketplace added from a local folder, plus the GitHub ones owned by `owner`) or a list of names |
| `guard` | `"all"` | `"all"` stops edits to the installed copy of any plugin; `"mine"` only to plugins from your marketplaces (and your `install_dirs`) |
| `sources` | `[]` | where your source repos live: a folder that holds them, a list of folders, or a map of plugin (or marketplace) name to repo path |
| `install_dirs` | `{}` | other installed copies to protect, outside the plugins folder, such as a CLI installed by cloning its repo: a map of name to path, or a list of paths (name = folder name without `-src`) |
| `exempt` | `[]` | paths inside an install dir that may be written, such as logs or runtime data |
| `pass_minutes` | `30` | how long a warned edit can be repeated, and how long the pass file lets edits through |
| `scan_dirs` | `[]` | `plugin-dev-check` only: folders searched for repos of `owner` that are outside `sources` |
| `tip` | `""` | a line added at the end of the message Claude sees (the block and the reminder after a pass), for example your own follow-up step |

A source repo is matched to an installed plugin by the `name` in its `.claude-plugin/plugin.json`,
by the catalog name in its `.claude-plugin/marketplace.json` (for catalog clones and plugins kept
in a folder of a catalog repo), or by its folder name. Plugins from a marketplace you added from
a local folder point to that folder.

### plugin-dev-check

```
plugin-dev-check [--fetch] [--md]
```

`--fetch` runs `git fetch` in each repo first; `--md` prints a Markdown table. Exit code 1 means
something is listed under "Fix": an installed copy behind the repo's default branch, a catalog
clone or install dir not at it, tracked files edited inside an install dir, commits not pushed,
or sync-conflict files inside `.git`.

Claude can run it as a bare command (Claude Code puts a plugin's `bin/` folder on the Bash
tool's `PATH`). In your own terminal, run it from the installed plugin, for example
`python3 ~/.claude/plugins/cache/lucas-tools/plugin-dev-guard/*/bin/plugin-dev-check`, or
add an alias.

## How it works

`hooks/hooks.json` registers a `PreToolUse` hook on `Edit`, `Write`, `MultiEdit`,
`NotebookEdit` and `Bash`, and a `SessionStart` hook that only creates your settings file when
it is missing.

The hook works out the files the tool call would really write:

- `Edit`/`Write`/`MultiEdit`/`NotebookEdit`: the file path.
- `Bash`: the targets of redirections (`>`, `>>`, `&>`, ...); files edited in place by
  `sed -i`, `perl -i` and `ruby -i`; `tee`, `touch`, `rm`, `mkdir`, `chmod` and similar; the
  destination of `cp`, `install`, `ln`, `rsync`; both sides of `mv`; `dd of=`, `curl -o`,
  `wget -O`, `tar -x`, `unzip`, `patch`; the folder of a `git` command that changes the work
  tree (`git pull --ff-only` and `git fetch` are allowed, since that is how an install is
  updated); the start folders of `find -delete` or `find -exec <writer>`. It follows `cd`,
  `env -C` and wrappers such as `sudo`, `timeout` and `xargs`, and reads `bash -c '...'`,
  `eval` and heredocs fed to a shell the same way. For `python`, `node`, `ruby` and `perl` code
  (`-c`, `-e` or a heredoc), quoted paths count only when the code also calls a write function.

A path that only appears in the text, such as a `sed` script, a commit message, a heredoc
written to a repo file, or a file read with `grep`, `diff` or `cp` from the installed copy, does
not count.

Each target is checked against the plugins folder (`$CLAUDE_CONFIG_DIR/plugins` when that is
set, else `~/.claude/plugins`) and your `install_dirs`. On a hit, the hook looks for the local
source repo, else for the plugin's repo address (from the marketplace entry, the plugin's own
`plugin.json`, or the marketplace in `known_marketplaces.json`), and returns
`permissionDecision: "deny"` with the message above, and notes the file in
`~/.claude/state/plugin-dev-guard.warned.json`. A UserPromptSubmit hook notes when you send a message
in that session (`plugin-dev-guard.prompts.json`, only while a warning waits). The same edit made again
within `pass_minutes`, after a message from you that came after the warning, goes through once; so does any edit while a pass file younger than `pass_minutes`
exists. Either way the call goes through, and Claude is told what it just edited: when the plugin's source repo is
on this machine, to make the same change there too; otherwise, that the change lasts only until
the next update and where to open a pull request. Your `tip` is added to that reminder as well.
Input it can't parse, and other tools, pass untouched.

## Uninstall

```
/plugin uninstall plugin-dev-guard@lucas-tools
```

Your settings file stays; delete `~/.config/plugin-dev-guard/` if you want it gone.

## Limits

- It is a small shell tokenizer, not a full shell. Variables other than `$HOME` are not
  expanded, so `echo x > "$DIR/f"` is not judged, and neither is a script file run with
  `python3 script.py` or `bash script.sh` (only inline code is read).
- In inline Python/Node/Ruby/Perl code, any quoted path counts once the code calls a write
  function anywhere, even if that path is only read.
- `cd` inside a subshell or `$(...)` still changes the folder used for the commands after it.
- Commands that write through stdin lists (`... | xargs rm`) are judged only on the paths
  written in the command.
- The pass file opens every installed copy, not only the one you approved, until it expires.
- The hook sees that you sent a message after the warning, not what it says: a plugin that submits a prompt
  in your place also counts as an answer.
- Tested on macOS in the terminal CLI. The tests also run on Linux and Windows in CI, but I
  have not used the plugin in a real session there.

## Tests

```
python3 -m unittest discover -s tests -v
```

Standard library only (`git` is needed for the `plugin-dev-check` tests). CI runs them on
Ubuntu, macOS and Windows.

## License

MIT. See [LICENSE](LICENSE).

Built with Claude Code
