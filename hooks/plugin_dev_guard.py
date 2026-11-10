#!/usr/bin/env python3
"""PreToolUse hook: stop edits to the INSTALLED copy of a plugin.

An installed copy (~/.claude/plugins/cache/<marketplace>/<plugin>/..., the marketplace
clones in ~/.claude/plugins/marketplaces/<marketplace>/..., and any install dirs you list)
is replaced on the next update, so a change there is lost. The hook tells Claude where to
make the change instead: your local source repo, or a clone/fork of the plugin's repo and
a pull request to its author.

Only real write targets are judged: Edit/Write file paths, and for Bash the files the
command writes (see shellwrites.py), never a path that only appears in the text.

Exception: the user approves, Claude touches the pass file (valid pass_minutes).
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
    lines.append("Exception (a quick test or one-off fix): only if the user asked for this exact edit "
                 "or approves it now (ask first), run `mkdir -p \"%s\" && touch \"%s\"` (valid %g minutes) "
                 "and retry." % (os.path.dirname(pf).replace(os.sep, "/"), pf.replace(os.sep, "/"),
                                 cfg["pass_minutes"]))
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
    if not hits or pass_valid(cfg["pass_minutes"]):
        return
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": message(hits, cfg, known)}}))


if __name__ == "__main__":
    main()
