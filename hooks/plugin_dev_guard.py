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
repeats the same call in the same session: it goes through once. Creating the pass file follows the same
rule (Claude cannot give itself a pass); while a pass is valid (pass_minutes) edits to installed copies go
through with a reminder: make the same change in the source repo. The hook's own state files cannot be
written by a tool at all. `--seed` (SessionStart) creates the settings file when it is missing.
"""
import contextlib
import hashlib
import json
import os
import sys
import tempfile
import time

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
try:
    import msvcrt
except ImportError:
    msvcrt = None

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


def state_dir():
    return os.path.dirname(pdg.pass_file())


def warned_file():
    return os.path.join(state_dir(), "plugin-dev-guard.warned.json")


@contextlib.contextmanager
def state_lock():
    """One hook at a time reads and rewrites the state files (parallel tool calls run in parallel)."""
    f = None
    try:
        os.makedirs(state_dir(), exist_ok=True)
        f = open(os.path.join(state_dir(), "plugin-dev-guard.lock"), "a+")
        if fcntl:
            fcntl.flock(f, fcntl.LOCK_EX)
        elif msvcrt:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
    except OSError:
        pass
    try:
        yield
    finally:
        if f:
            try:
                if not fcntl and msvcrt:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            f.close()


def read_warned(minutes):
    """Warnings still inside the pass window: {path: {"t": time, "sid": session, "call": key}}."""
    now = time.time()
    data = pdg.read_json(warned_file(), {})
    if not isinstance(data, dict):
        return {}
    return {p: w for p, w in data.items() if isinstance(w, dict) and isinstance(w.get("t"), (int, float))
            and now - w["t"] < minutes * 60}


def write_json(path, data):
    """Atomic: a temp file in the same folder, then os.replace."""
    tmp = None
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".pdg-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
        tmp = None
    except OSError:
        pass
    finally:
        if tmp:
            try:
                os.remove(tmp)
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
    with state_lock():
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


def call_key(tool, inp):
    """What makes two tool calls "the same": the command for Bash, else the whole input (without a
    description). Stored as a short hash."""
    if not isinstance(inp, dict):
        inp = {"input": inp}
    what = {"command": inp.get("command")} if tool == "Bash" else {k: v for k, v in inp.items() if k != "description"}
    raw = json.dumps({"tool": tool, "input": what}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def pass_command():
    pf = pdg.pass_file()
    return 'mkdir -p "%s" && touch "%s"' % (os.path.dirname(pf).replace(os.sep, "/"), pf.replace(os.sep, "/"))


def same_file(a, b):
    return pdg.real(a) == pdg.real(b)


def state_files():
    return [warned_file(), prompts_file(), os.path.join(state_dir(), "plugin-dev-guard.lock")]


def mentions_guarded(data, cfg):
    """The raw tool input names the plugins folder or an install dir (used when it cannot be parsed)."""
    text = json.dumps(data.get("tool_input"), default=str).replace("\\\\", "/").lower()
    needles = [".claude/plugins", pdg.plugins_dir().replace(os.sep, "/").lower()]
    needles += [d.replace(os.sep, "/").lower() for d in pdg.install_dirs(cfg).values()]
    return any(n and n in text for n in needles)


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason}}))


def allow_with(note):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": note}}))


def pass_message(cfg):
    return ("plugin-dev-guard: this creates or changes the plugin-dev-guard pass file (%s). A pass lets every "
            "edit to an installed plugin copy through for %g minutes, so Claude may not give itself one. End your "
            "turn and ask the user, saying what you want to change and why. Only after the user answers yes in a "
            "new message, run the SAME command again: it goes through once."
            % (pdg.pass_file().replace(os.sep, "/"), cfg["pass_minutes"]))


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
    lines.append("Exception (a quick test or one-off fix): end your turn and ask the user, saying what this changes. "
                 "Only after the user answers yes in a new message, make the SAME edit again in this session: it goes "
                 "through once (within %g minutes). A repeat before the user's next message is blocked again. For "
                 "several files at once, ask for a pass instead and, after the user's yes, run "
                 "`%s` (a pass for every installed copy, same time limit)."
                 % (cfg["pass_minutes"], pass_command()))
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
    cfg = pdg.load_config()
    try:
        decide(data, cfg)
    except Exception:
        # Input or a file the hook cannot read: refuse only a call that names a guarded folder.
        if mentions_guarded(data, cfg):
            deny("plugin-dev-guard: could not read this tool call, and it names the plugins folder or an "
                 "install dir, so it is refused to be safe. Write it in a plain form (a string command, or a "
                 "file path), or make the change in the plugin's source repo.")


def decide(data, cfg):
    paths = [p for p in write_targets(data) if p]
    if not paths:
        return
    if any(same_file(p, f) for p in paths for f in state_files()):
        deny("plugin-dev-guard: tools may not write the hook's own state files in %s (warnings, answers, "
             "lock); the hook keeps them itself." % state_dir().replace(os.sep, "/"))
        return
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
    pf = pdg.pass_file()
    wants_pass = any(same_file(p, pf) for p in paths)
    if not hits and not wants_pass:
        return
    sid = str(data.get("session_id") or "")
    tool = data.get("tool_name", "")
    key = call_key(tool, data.get("tool_input"))
    guarded = [h["path"] for h in hits] + ([pf] if wants_pass else [])
    with state_lock():
        warned = read_warned(cfg["pass_minutes"])
        rest = {p: w for p, w in warned.items() if p not in guarded}
        if not wants_pass and pass_valid(cfg["pass_minutes"]):
            write_json(warned_file(), rest)
            allow_with(reminder(hits, cfg, known))
            return
        same = all(p in warned and warned[p].get("sid") == sid and warned[p].get("call") == key for p in guarded)
        if sid and same and answered_since(sid, max(warned[p]["t"] for p in guarded)):
            # the same call again, in the same session, after a message from the user
            write_json(warned_file(), rest)
            if hits:
                allow_with(reminder(hits, cfg, known, "the repeat after the user's answer"))
            else:
                allow_with("plugin-dev-guard: pass allowed after the user's answer. It lets edits to every "
                           "installed copy through for %g minutes; still make each change in the source repo."
                           % cfg["pass_minutes"])
            return
        now = time.time()
        for p in guarded:
            w = warned.get(p)
            keep = w and w.get("sid") == sid and w.get("call") == key
            warned[p] = {"t": w["t"] if keep else now, "sid": sid, "call": key}
        if hits and not wants_pass:
            # after the user's yes, the pass command from the message goes through once too
            warned[pf] = {"t": now, "sid": sid, "call": call_key("Bash", {"command": pass_command()})}
        write_json(warned_file(), warned)
    deny(message(hits, cfg, known) if hits else pass_message(cfg))


if __name__ == "__main__":
    main()
