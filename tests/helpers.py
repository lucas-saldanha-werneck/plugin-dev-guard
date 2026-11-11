"""A fake home folder with installed plugins, marketplaces and source repos."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
HOOK = os.path.join(ROOT, "hooks", "plugin_dev_guard.py")
CHECK = os.path.join(ROOT, "bin", "plugin-dev-check")


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(data if isinstance(data, str) else json.dumps(data, indent=2))


def git(d, *args):
    return subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@example.com",
                           "-c", "commit.gpgsign=false"] + list(args),
                          capture_output=True, text=True, check=True).stdout.strip()


class FakeHome(object):
    def __init__(self):
        self.home = os.path.realpath(tempfile.mkdtemp(prefix="pdg-"))
        self.plugins = os.path.join(self.home, ".claude", "plugins")
        self.config = os.path.join(self.home, "cfg", "config.json")
        self.src = os.path.join(self.home, "src")
        mk = os.path.join(self.plugins, "marketplaces")
        self.local_mkt = os.path.join(self.src, "local-plugins")
        write(os.path.join(self.plugins, "known_marketplaces.json"), {
            "theirs": {"source": {"source": "github", "repo": "author/their-plugins"},
                       "installLocation": os.path.join(mk, "theirs")},
            "mine": {"source": {"source": "github", "repo": "me/my-plugins"},
                     "installLocation": os.path.join(mk, "mine")},
            "local": {"source": {"source": "directory", "path": self.local_mkt},
                      "installLocation": self.local_mkt},
        })
        write(os.path.join(mk, "theirs", ".claude-plugin", "marketplace.json"), {
            "name": "theirs", "plugins": [
                {"name": "tool", "source": {"source": "github", "repo": "author/tool"}},
                {"name": "inner", "source": "./plugins/inner"}]})
        write(os.path.join(mk, "mine", ".claude-plugin", "marketplace.json"), {
            "name": "mine", "plugins": [{"name": "myplug", "source": {"source": "github", "repo": "me/myplug"}}]})
        write(os.path.join(self.local_mkt, ".claude-plugin", "marketplace.json"), {
            "name": "local", "plugins": [{"name": "lp", "source": "./lp"}]})
        os.makedirs(os.path.join(self.local_mkt, "lp"), exist_ok=True)
        for m, pl, v in (("theirs", "tool", "1.0.0"), ("mine", "myplug", "0.1.0"), ("theirs", "inner", "2.0.0"),
                         ("local", "lp", "0.0.1")):
            write(os.path.join(self.plugins, "cache", m, pl, v, ".claude-plugin", "plugin.json"), {"name": pl})
        # the source repo of myplug
        self.myplug = os.path.join(self.src, "myplug")
        write(os.path.join(self.myplug, ".claude-plugin", "plugin.json"), {"name": "myplug", "version": "0.1.0"})
        os.makedirs(os.path.join(self.myplug, ".git"), exist_ok=True)
        self.set_config({"owner": "me", "sources": self.src})

    def set_config(self, cfg):
        write(self.config, cfg)

    def env(self):
        e = dict(os.environ)
        for k in ("CLAUDE_CONFIG_DIR", "XDG_CONFIG_HOME"):
            e.pop(k, None)
        e.update({"HOME": self.home, "USERPROFILE": self.home, "PLUGIN_DEV_GUARD_CONFIG": self.config})
        return e

    def run_hook(self, payload, *args):
        self.note = None
        r = subprocess.run([sys.executable, "-I", HOOK] + list(args), input=json.dumps(payload),
                           capture_output=True, text=True, env=self.env(), timeout=60)
        assert r.returncode == 0, r.stderr
        if not r.stdout.strip():
            return None
        d = json.loads(r.stdout)["hookSpecificOutput"]
        assert d["hookEventName"] == "PreToolUse"
        if "permissionDecision" not in d:  # let through, with a reminder
            self.note = d["additionalContext"]
            return None
        assert d["permissionDecision"] == "deny"
        return d["permissionDecisionReason"]

    def bash(self, cmd, cwd=None):
        return self.run_hook({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd or self.home})

    def edit(self, path, tool="Edit"):
        return self.run_hook({"tool_name": tool, "tool_input": {"file_path": path}, "cwd": self.home})

    def check(self, *args):
        r = subprocess.run([sys.executable, CHECK] + list(args), capture_output=True, text=True,
                           env=self.env(), timeout=120)
        return r.returncode, r.stdout + r.stderr

    def cleanup(self):
        shutil.rmtree(self.home, ignore_errors=True)
