"""Shared code for the plugin-dev-guard hook and the plugin-dev-check command.

Settings: $PLUGIN_DEV_GUARD_CONFIG, else $XDG_CONFIG_HOME/plugin-dev-guard/config.json,
else ~/.config/plugin-dev-guard/config.json. Created from config.example.json when missing,
never overwritten.
"""
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = os.path.join(HERE, "..", "config.example.json")
DEFAULTS = {
    "owner": "",
    "marketplaces": "auto",
    "guard": "all",
    "sources": [],
    "install_dirs": {},
    "exempt": [],
    "pass_minutes": 30,
    "scan_dirs": [],
    "tip": "",
}


def home():
    return os.path.expanduser("~")


def expand(p):
    if not isinstance(p, str) or not p.strip():
        return None
    p = os.path.expandvars(os.path.expanduser(p.strip()))
    return p if os.path.isabs(p) else None


def config_path():
    env = expand(os.environ.get("PLUGIN_DEV_GUARD_CONFIG", ""))
    if env:
        return env
    xdg = expand(os.environ.get("XDG_CONFIG_HOME", ""))
    return os.path.join(xdg or os.path.join(home(), ".config"), "plugin-dev-guard", "config.json")


def seed_config():
    """Create the settings file from config.example.json when it is missing. Never overwrites."""
    path = config_path()
    if os.path.exists(path):
        return False
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(EXAMPLE, "rb") as src, open(path, "xb") as dst:
            shutil.copyfileobj(src, dst)
        return True
    except OSError:
        return False


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(config_path(), encoding="utf-8-sig") as f:
            user = json.load(f)
    except (OSError, ValueError):
        user = {}
    if isinstance(user, dict):
        for k, v in user.items():
            if k in DEFAULTS and not k.startswith("_"):
                cfg[k] = v
    if not isinstance(cfg["owner"], str):
        cfg["owner"] = ""
    if cfg["guard"] not in ("all", "mine"):
        cfg["guard"] = "all"
    try:
        cfg["pass_minutes"] = max(0.0, float(cfg["pass_minutes"]))
    except (TypeError, ValueError):
        cfg["pass_minutes"] = 30.0
    if not isinstance(cfg["tip"], str):
        cfg["tip"] = ""
    return cfg


def claude_dir():
    return expand(os.environ.get("CLAUDE_CONFIG_DIR", "")) or os.path.join(home(), ".claude")


def plugins_dir():
    return os.path.join(claude_dir(), "plugins")


def pass_file():
    return os.path.join(claude_dir(), "state", "plugin-dev-guard.pass")


def read_json(path, default):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def known_marketplaces():
    """{name: info}; entries that are not objects are dropped, and a `source` that is not an object
    becomes {}, so odd data never stops the hook."""
    d = read_json(os.path.join(plugins_dir(), "known_marketplaces.json"), {})
    if not isinstance(d, dict):
        return {}
    out = {}
    for name, info in d.items():
        if isinstance(info, dict):
            info = dict(info)
            if not isinstance(info.get("source"), dict):
                info["source"] = {}
            out[name] = info
    return out


def installed_plugins():
    d = read_json(os.path.join(plugins_dir(), "installed_plugins.json"), {})
    d = d.get("plugins", {}) if isinstance(d, dict) else {}
    return d if isinstance(d, dict) else {}


def true_case(p):
    """macOS file systems ignore letter case by default: give each existing part of the path the
    case it has on disk, so ~/.CLAUDE/plugins/cache/THEIRS/... is matched like the real folder."""
    head, parts = p, []
    while True:
        h, t = os.path.split(head)
        if not t:
            break
        parts.append(t)
        head = h
    out = head
    for i, part in enumerate(reversed(parts)):
        try:
            names = os.listdir(out)
        except OSError:
            return os.path.join(out, *list(reversed(parts))[i:])
        if part not in names:
            match = [n for n in names if n.lower() == part.lower()]
            if len(match) == 1:
                part = match[0]
        out = os.path.join(out, part)
    return out


def real(p):
    p = os.path.normcase(os.path.realpath(p))
    return true_case(p) if sys.platform == "darwin" else p


def inside(p, root):
    return p == root or p.startswith(root.rstrip(os.sep) + os.sep)


def as_list(v):
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [x for x in v if isinstance(x, str)]
    return []


def mine(cfg, known):
    """Names of the marketplaces that are yours."""
    m = cfg["marketplaces"]
    if isinstance(m, (list, str)) and m != "auto":
        return set(as_list(m))
    owner = cfg["owner"].lower()
    out = set()
    for name, info in known.items():
        src = info.get("source") or {} if isinstance(info, dict) else {}
        if not isinstance(src, dict):
            continue
        kind = src.get("source")
        if kind == "directory":
            out.add(name)
        elif owner and kind == "github" and str(src.get("repo", "")).lower().startswith(owner + "/"):
            out.add(name)
        elif owner and kind in ("git", "url") and ("github.com/%s/" % owner) in str(src.get("url", "")).lower():
            out.add(name)
    return out


def install_dirs(cfg):
    """{name: path} from install_dirs (a map, or a list of paths; name = folder without -src)."""
    v = cfg["install_dirs"]
    out = {}
    if isinstance(v, dict):
        for k, p in v.items():
            p = expand(p)
            if p:
                out[k] = p
    else:
        for p in as_list(v):
            p = expand(p)
            if p:
                b = os.path.basename(p.rstrip("/\\"))
                out[b[:-4] if b.endswith("-src") else b] = p
    return out


def source_folders(cfg):
    v = cfg["sources"]
    if isinstance(v, dict):
        return []
    return [p for p in (expand(x) for x in as_list(v)) if p and os.path.isdir(p)]


def source_map(cfg):
    v = cfg["sources"]
    if not isinstance(v, dict):
        return {}
    return {k: p for k, p in ((k, expand(p)) for k, p in v.items()) if p}


def source_repos(cfg):
    """[(name, path)] of every source repo you listed."""
    out = []
    for k, p in sorted(source_map(cfg).items()):
        out.append((k, p))
    for folder in source_folders(cfg):
        try:
            subs = sorted(os.listdir(folder), key=str.lower)
        except OSError:
            continue
        for s in subs:
            p = os.path.join(folder, s)
            if os.path.exists(os.path.join(p, ".git")):
                out.append((s, p))
    return out


def plugin_name(repo):
    d = read_json(os.path.join(repo, ".claude-plugin", "plugin.json"), {})
    return d.get("name") if isinstance(d, dict) else None


def catalog(repo):
    d = read_json(os.path.join(repo, ".claude-plugin", "marketplace.json"), {})
    return d if isinstance(d, dict) else {}


def catalog_entry(cat, plugin):
    for e in cat.get("plugins", []) or []:
        if isinstance(e, dict) and e.get("name") == plugin:
            return e
    return None


def marketplace_dir(name, known):
    info = known.get(name) or {}
    loc = info.get("installLocation")
    if loc and os.path.isdir(loc):
        return loc
    p = os.path.join(plugins_dir(), "marketplaces", name)
    return p if os.path.isdir(p) else None


def guarded_below(pd, subs, cfg, known):
    """Sorted names of the guarded marketplaces with a folder in pd/<sub> for sub in subs."""
    names = set()
    for sub in subs:
        root = os.path.join(pd, sub)
        try:
            names.update(n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n)))
        except OSError:
            pass
    if cfg["guard"] == "mine":
        names &= mine(cfg, known)
    return sorted(names)


def classify(path, cfg, known):
    """What installed copy `path` is in: dict(kind, name, marketplace, root) or None."""
    p = real(path)
    for e in as_list(cfg["exempt"]):
        e = expand(e)
        if e and inside(p, real(e)):
            return None
    for name, d in install_dirs(cfg).items():
        if inside(p, real(d)):
            return {"kind": "install", "name": name, "marketplace": None, "root": d}
    pd = real(plugins_dir())
    # the plugins folder itself, or its cache/ or marketplaces/ folder: deleting or moving it
    # takes every installed copy below with it
    subs = {pd: ("cache", "marketplaces"), os.path.join(pd, "cache"): ("cache",),
            os.path.join(pd, "marketplaces"): ("marketplaces",)}.get(p.rstrip(os.sep) or p)
    if subs:
        markets = guarded_below(pd, subs, cfg, known)
        if not markets:
            return None
        return {"kind": "marketplace", "name": markets[0], "marketplace": markets[0], "root": p}
    for sub in ("cache", "marketplaces"):
        root = os.path.join(pd, sub)
        if not inside(p, root):
            continue
        parts = p[len(root):].strip(os.sep).split(os.sep)
        if not parts or not parts[0]:
            return None
        market = parts[0]
        if sub == "cache":
            plugin = parts[1] if len(parts) > 1 else None
            if not plugin:
                return {"kind": "marketplace", "name": market, "marketplace": market,
                        "root": os.path.join(root, market)}
            return {"kind": "plugin", "name": plugin, "marketplace": market,
                    "root": os.path.join(root, market, plugin)}
        return {"kind": "marketplace", "name": market, "marketplace": market,
                "root": os.path.join(root, market)}
    return None


def find_source(hit, cfg, known):
    """Local source folder for a hit, or None."""
    name, market = hit["name"], hit["marketplace"]
    smap = source_map(cfg)
    if name in smap and os.path.isdir(smap[name]):
        return smap[name]
    info = (known.get(market) or {}).get("source") or {} if market else {}
    if info.get("source") == "directory" and info.get("path") and os.path.isdir(info["path"]):
        d = info["path"]
        if hit["kind"] == "marketplace":
            return d
        e = catalog_entry(catalog(d), name)
        if e and isinstance(e.get("source"), str):
            p = os.path.normpath(os.path.join(d, e["source"]))
            if os.path.isdir(p):
                return p
    for folder in source_folders(cfg):
        try:
            subs = sorted(os.listdir(folder))
        except OSError:
            continue
        by_folder = None
        for s in subs:
            p = os.path.join(folder, s)
            if not os.path.isdir(p):
                continue
            if hit["kind"] == "plugin" and plugin_name(p) == name:
                return p
            cat = catalog(p)
            if market and cat.get("name") == market:
                if hit["kind"] == "marketplace":
                    return p
                e = catalog_entry(cat, name)
                if e and isinstance(e.get("source"), str):
                    q = os.path.normpath(os.path.join(p, e["source"]))
                    if os.path.isdir(q):
                        return q
            if s == name and (os.path.exists(os.path.join(p, ".git")) or
                              os.path.isdir(os.path.join(p, ".claude-plugin"))):
                by_folder = p
        if by_folder:
            return by_folder
    return None


def web_url(u):
    if not isinstance(u, str) or not u:
        return None
    u = u.strip()
    m = re.match(r"^git@([^:]+):(.+)$", u)
    if m:
        u = "https://%s/%s" % (m.group(1), m.group(2))
    if u.endswith(".git"):
        u = u[:-4]
    return u if u.startswith("http") else None


def source_url(src):
    if isinstance(src, dict):
        if src.get("source") == "github" and src.get("repo"):
            return "https://github.com/" + src["repo"]
        return web_url(src.get("url") or src.get("repo"))
    return None


def git(d, *args):
    try:
        r = subprocess.run(["git", "-C", d] + list(args), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def find_url(hit, known):
    """The web address of the plugin's repo, or None."""
    if hit["kind"] == "install":
        return web_url(git(hit["root"], "remote", "get-url", "origin"))
    market = hit["marketplace"]
    murl = source_url((known.get(market) or {}).get("source"))
    if hit["kind"] == "marketplace":
        return murl
    mdir = marketplace_dir(market, known)
    e = catalog_entry(catalog(mdir), hit["name"]) if mdir else None
    if e:
        u = source_url(e.get("source"))
        if u:
            return u
        if isinstance(e.get("source"), str) and murl:
            rel = e["source"].strip("./")
            return murl + (" (folder %s)" % rel if rel else "")
    try:
        versions = sorted(os.listdir(hit["root"]))
    except OSError:
        versions = []
    for v in versions[::-1]:
        pj = read_json(os.path.join(hit["root"], v, ".claude-plugin", "plugin.json"), {})
        if isinstance(pj, dict):
            r = pj.get("repository")
            u = web_url(r.get("url") if isinstance(r, dict) else r) or web_url(pj.get("homepage"))
            if u:
                return u
    if e:
        u = web_url(e.get("repository")) or web_url(e.get("homepage"))
        if u:
            return u
    return murl
