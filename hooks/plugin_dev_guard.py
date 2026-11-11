#!/usr/bin/env python3
"""PreToolUse hook: stop edits to the INSTALLED copy of a plugin.

An installed copy (~/.claude/plugins/cache/<marketplace>/<plugin>/..., the marketplace
clones in ~/.claude/plugins/marketplaces/<marketplace>/..., and any install dirs you list)
is replaced on the next update, so a change there is lost. The hook tells Claude where to
make the change instead: your local source repo, or a clone/fork of the plugin's repo and
a pull request to its author.

Only real write targets are judged: Edit/Write file paths, and for Bash the files the
command writes (see shellwrites.py), never a path that only appears in the text.

Exception: Claude asks, the user answers in a new message (UserPromptSubmit, `--prompt`), and Claude
repeats the same edit: it goes through once. Or Claude touches the pass file (valid pass_minutes). While the
pass is valid the edit goes through with a reminder: make the same change in the source repo.
`--seed` (SessionStart) creates the settings file when it is missing.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pdg  # noqa: E402
import shellwrites  # noqa: E402

EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def write_targets(data):
    tool = data.get("tool_name", "")
    inp = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()
    if tool in EDIT_TOOLS:
        p = inp.get("file_path") or inp.get("notebook_path") or ""
        return [shellwrites.resolve(p, cwd)] if p else []
    if tool == "Bash":
        return shellwrites.targets(inp.get("command", "") or "", cwd)
    return []


def pass_valid(minutes):
    try:
        return time.time() - os.path.getmtime(pdg.pass_file()) < minutes * 60
    except OSError:
        return False


def warned_file():
    return os.path.join(os.path.dirname(pdg.pass_file()), "plugin-dev-guard.warned.json")


def read_warned(minutes):
    """Paths Claude was warned about, still inside the pass window: {path: time}."""
    now = time.time()
    data = pdg.read_json(warned_file(), {})
    if not isinstance(data, dict):
        return {}
    return {p: t for p, t in data.items() if isinstance(t, (int, float)) and now - t < minutes * 60}


def write_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def write_warned(data):
    write_json(warned_file(), data)


def prompts_file():
    return os.path.join(os.path.dirname(pdg.pass_file()), "plugin-dev-guard.prompts.json")


def record_prompt(data):
    """UserPromptSubmit: note when the user last sent a message in this session (only while a warning waits)."""
    sid = str((data or {}).get("session_id") or "")
    if not sid or not pdg.read_json(warned_file(), {}):
        return
    seen = pdg.read_json(prompts_file(), {})
    if not isinstance(seen, dict):
        seen = {}
    now = time.time()
    seen = {s: t for s, t in seen.items() if isinstance(t, (int, float)) and now - t < 86400}
    seen[sid] = now
    write_json(prompts_file(), seen)


def answered_since(sid, since):
    """The user sent a message in this session after `since` (the time of the warning)."""
    seen = pdg.read_json(prompts_file(), {})
    t = seen.get(sid) if isinstance(seen, dict) and sid else None
    return isinstance(t, (int, float)) and t > since


def message(hits, cfg, known):
    names = ", ".join(sorted({h["name"] for h in hits}))
    lines = ["plugin-dev-guard: this changes the INSTALLED copy of %s (%s). That copy is replaced "
             "on the next plugin update, so the change would be lost." % (names, hits[0]["path"])]
    seen = set()
    for h in hits:
        if h["name"] in seen:
            continue
        seen.add(h["name"])
        src = pdg.find_source(h, cfg, known)
        if src:
            lines.append("- %s: its source repo is on this machine: %s. Make the change there "
                         "(branch, commit, bump the version in .claude-plugin/plugin.json, push), "
                         "then update the installed plugin from it." % (h["name"], src))
        else:
            url = pdg.find_url(h, known)
            where = url or "its repo (the plugin's homepage in /plugin)"
            lines.append("- %s: no local source repo found. Clone or fork %s, make the change there "
                         "and open a pull request to its author. Never patch the installed copy."
                         % (h["name"], where))
    pf = pdg.pass_file()
    lines.append("Exception (a quick test or one-off fix): end your turn and ask the user, saying what this changes. "
                 "Only after the user answers yes in a new message, make the SAME edit again: it goes through once "
                 "(within %g minutes). A repeat before the user's next message is blocked again. For several files "
                 "at once, run "
                 "`mkdir -p \"%s\" && touch \"%s\"` instead (a pass for every installed copy, same time limit)."
                 % (cfg["pass_minutes"], os.path.dirname(pf).replace(os.sep, "/"), pf.replace(os.sep, "/")))
    if cfg["tip"].strip():
        lines.append(cfg["tip"].strip())
    return "\n".join(lines)


def reminder(hits, cfg, known, why="the pass file"):
    """What Claude is told when the pass file, or a repeat after the warning, lets the edit through."""
    names = ", ".join(sorted({h["name"] for h in hits}))
    lines = ["plugin-dev-guard: allowed by %s. This edits the INSTALLED copy of %s (%s), "
             "which the next plugin update replaces." % (why, names, hits[0]["path"])]
    seen = set()
    for h in hits:
        if h["name"] in seen:
            continue
        seen.add(h["name"])
        src = pdg.find_source(h, cfg, known)
        if src:
            lines.append("- %s: its source repo is on this machine: %s. Make the same change there too "
                         "(branch, commit, bump the version in .claude-plugin/plugin.json, push), or it "
                         "is lost on the next update. Tell the user it is still to do if you do not do "
                         "it now." % (h["name"], src))
        else:
            url = pdg.find_url(h, known)
            where = url or "its repo (the plugin's homepage in /plugin)"
            lines.append("- %s: no local source repo found. The change lasts only until the next update; "
                         "to keep it, open a pull request at %s. Tell the user." % (h["name"], where))
    if cfg["tip"].strip():
        lines.append(cfg["tip"].strip())
    return "\n".join(lines)


def main():
    if "--seed" in sys.argv:
        pdg.seed_config()
        return
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    if not isinstance(data, dict):
        return
    if "--prompt" in sys.argv:
        record_prompt(data)
        return
    try:
        paths = [p for p in write_targets(data) if p]
    except Exception:
        return
    if not paths:
        return
    cfg = pdg.load_config()
    known = pdg.known_marketplaces()
    mine = pdg.mine(cfg, known)
    hits = []
    for p in paths:
        h = pdg.classify(p, cfg, known)
        if not h:
            continue
        if cfg["guard"] == "mine" and h["marketplace"] and h["marketplace"] not in mine:
            continue
        h["path"] = p
        hits.append(h)
    if not hits:
        return
    warned = read_warned(cfg["pass_minutes"])
    paths = [h["path"] for h in hits]
    if pass_valid(cfg["pass_minutes"]):
        write_warned({p: t for p, t in warned.items() if p not in paths})
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": reminder(hits, cfg, known)}}))
        return
    sid = str(data.get("session_id") or "")
    if all(p in warned for p in paths) and answered_since(sid, max(warned[p] for p in paths)):
        # the same edit again, after a message from the user that came after the warning
        write_warned({p: t for p, t in warned.items() if p not in paths})
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": reminder(hits, cfg, known, "the repeat after the user's answer")}}))
        return
    warned.update({p: warned.get(p) or time.time() for p in paths})
    write_warned(warned)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": message(hits, cfg, known)}}))


if __name__ == "__main__":
    main()
