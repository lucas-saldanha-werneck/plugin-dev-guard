"""Find the files a Bash command would write to.

Only real write targets count, never a path that merely appears in the text:
  - redirection targets: > >> >| &> &>> <> and >&FILE
  - in-place editors: sed -i, perl -i, ruby -i
  - tee, touch, truncate, rm, rmdir, mkdir, chmod, chown, chgrp, unlink, shred
  - cp / install / ln / rsync / ditto destinations (-t DIR too), mv sources and destination
  - dd of=, curl -o, wget -O, tar -x (-C), unzip (-d), patch (-d / file)
  - git commands that change the work tree (target: the -C folder or the current folder)
  - find ... -delete / -exec <writer>: the folders find starts from
  - bash/sh/zsh -c '...', eval '...' and heredocs fed to a shell are parsed the same way
  - python/node/ruby/perl code (-c / -e / heredoc): quoted paths, only when the code
    also calls a write function (open(..., 'w'), write_text, shutil, fs.writeFile ...)

It is a small tokenizer, not a full shell. Variables other than $HOME are not
expanded, so a target such as "$DIR/file" is not judged.
"""
import os
import re

OPS = ["&>>", "<<<", "<<-", "&>", ">>", ">|", ">&", "<&", "<>", "<<", "<(", ">(", "&&", "||",
       "|&", ";;", "$(", ";", "&", "|", "(", ")", ">", "<", "\n", "`"]
SEPARATORS = {"&&", "||", "|&", ";;", "$(", ";", "&", "|", "(", ")", "\n", "`", "<(", ">("}
WRITE_REDIRS = {">", ">>", ">|", "&>", "&>>", "<>", ">&"}
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[[^\]]*\])?\+?=")
KEYWORDS = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!", "{", "}",
            "time", "esac", "in"}
SKIP_COMMANDS = {"for", "case", "select", "function"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "ash"}
INTERPRETERS = {"python", "python2", "python3", "node", "nodejs", "deno", "bun", "ruby", "perl"}
WRITE_CODE = re.compile(
    r"\bopen\s*\([^)]*['\"][rwabxt+]*[wax+][rwabxt+]*['\"]"
    r"|\.write_(?:text|bytes)\s*\(|\bshutil\.\w+|\bos\.(?:remove|unlink|rename|replace|rmdir|removedirs"
    r"|makedirs|mkdir|chmod|truncate|symlink|link)\b|\.(?:unlink|rename|touch|mkdir|rmdir|symlink_to)\s*\("
    r"|\b(?:write|append)File(?:Sync)?\b|\bfs\.(?:rm|rmSync|unlink\w*|rename\w*|copyFile\w*|cp\w*|mkdir\w*"
    r"|truncate\w*|createWriteStream|writev?\w*|appendFile\w*)\b|\bFile\.(?:write|delete|rename)\b"
    r"|\bFileUtils\.\w+|\bDeno\.(?:write\w*|remove|rename|mkdir)\b|\bBun\.write\b"
    r"|\bunlink\b|\brename\b|\bopen\s*\(\s*\w+\s*,\s*['\"][>+]")
QUOTED = re.compile(r"'([^'\n]*)'|\"([^\"\n]*)\"")
PATHLIKE = re.compile(r"[/\\]|^~|^[\w.-]+\.\w+$")


class Heredoc(object):
    def __init__(self, delim, strip_tabs):
        self.delim = delim
        self.strip_tabs = strip_tabs
        self.body = ""


def tokenize(text):
    """Tokens: ('w', word), ('op', op) or ('hd', Heredoc). Quotes are removed."""
    toks, pending = [], []
    word, has_word = [], False
    i, n = 0, len(text)

    def flush():
        if has_word:
            toks.append(("w", "".join(word)))
        del word[:]

    while i < n:
        c = text[i]
        if c == "\\":
            if i + 1 < n and text[i + 1] == "\n":
                i += 2
                continue
            word.append(text[i + 1] if i + 1 < n else "")
            has_word = True
            i += 2
            continue
        if c == "'":
            j = text.find("'", i + 1)
            j = n if j < 0 else j
            word.append(text[i + 1:j])
            has_word = True
            i = j + 1
            continue
        if c == "$" and text.startswith("'", i + 1):
            j = text.find("'", i + 2)
            j = n if j < 0 else j
            word.append(text[i + 2:j])
            has_word = True
            i = j + 1
            continue
        if c == '"':
            j, buf = i + 1, []
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n and text[j + 1] in '$`"\\\n':
                    if text[j + 1] != "\n":
                        buf.append(text[j + 1])
                    j += 2
                    continue
                buf.append(text[j])
                j += 1
            word.append("".join(buf))
            has_word = True
            i = j + 1
            continue
        if c == "$" and text.startswith("((", i + 1):  # arithmetic: part of the word
            depth, j = 0, i + 1
            while j < n:
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            word.append(text[i:j + 1])
            has_word = True
            i = j + 1
            continue
        if c == "$" and text.startswith("{", i + 1):
            j = text.find("}", i)
            j = n if j < 0 else j
            word.append(text[i:j + 1])
            has_word = True
            i = j + 1
            continue
        if c == "#" and not has_word:
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if c in " \t\r":
            flush()
            has_word = False
            i += 1
            continue
        op = next((o for o in OPS if text.startswith(o, i)), None)
        if op:
            if op[0] in "<>" and has_word and "".join(word).isdigit():
                del word[:]  # file descriptor number such as 2>
                has_word = False
            flush()
            has_word = False
            i += len(op)
            if op in ("<<", "<<-"):
                while i < n and text[i] in " \t":
                    i += 1
                m = re.match(r"(['\"]?)([^\s'\";&|<>()]+)\1", text[i:])
                if m:
                    hd = Heredoc(m.group(2), op == "<<-")
                    pending.append(hd)
                    toks.append(("hd", hd))
                    i += m.end()
                continue
            toks.append(("op", op))
            if op == "\n" and pending:
                for hd in pending:
                    lines = []
                    while i < n:
                        j = text.find("\n", i)
                        j = n if j < 0 else j
                        line = text[i:j]
                        i = j + 1
                        if line.strip() == hd.delim:
                            break
                        lines.append(line)
                    hd.body = "\n".join(lines)
                pending = []
            continue
        word.append(c)
        has_word = True
        i += 1
    flush()
    return toks


def commands(toks):
    """Split tokens into simple commands: dicts with words, redirs, heredocs, piped (from previous)."""
    out, cur, piped = [], None, False
    for kind, val in toks:
        if cur is None:
            cur = {"words": [], "redirs": [], "heredocs": [], "piped": piped}
            piped = False
        if kind == "op" and val in SEPARATORS:
            if cur["words"] or cur["redirs"] or cur["heredocs"]:
                out.append(cur)
            cur = None
            piped = val in ("|", "|&")
            continue
        if kind == "op":
            cur["redirs"].append([val, None])
        elif kind == "hd":
            cur["heredocs"].append(val)
        elif cur["redirs"] and cur["redirs"][-1][1] is None:
            cur["redirs"][-1][1] = val
        else:
            cur["words"].append(val)
    if cur and (cur["words"] or cur["redirs"] or cur["heredocs"]):
        out.append(cur)
    return out


def opts(args, with_arg="", long_with_arg=()):
    """Split options from operands. Returns (list of (opt, value), operands)."""
    found, operands, i = [], [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            operands.extend(args[i + 1:])
            break
        if a.startswith("--") and len(a) > 2:
            if "=" in a:
                k, v = a.split("=", 1)
                found.append((k, v))
            elif a in long_with_arg and i + 1 < len(args):
                found.append((a, args[i + 1]))
                i += 1
            else:
                found.append((a, None))
        elif a.startswith("-") and len(a) > 1:
            j = 1
            while j < len(a):
                ch = a[j]
                if ch in with_arg:
                    rest = a[j + 1:]
                    if rest:
                        found.append(("-" + ch, rest))
                    elif i + 1 < len(args):
                        found.append(("-" + ch, args[i + 1]))
                        i += 1
                    else:
                        found.append(("-" + ch, None))
                    break
                found.append(("-" + ch, None))
                j += 1
        else:
            operands.append(a)
        i += 1
    return found, operands


def opt_values(found, *names):
    return [v for k, v in found if k in names and v is not None]


WRAPPERS = {
    "sudo": ("ugpCUrtThD", ("--user", "--group", "--prompt")),
    "doas": ("uC", ()),
    "nice": ("n", ("--adjustment",)),
    "ionice": ("cnp", ()),
    "stdbuf": ("ioe", ()),
    "xargs": ("IinPdLsEa", ("--max-args", "--max-procs", "--delimiter", "--arg-file")),
    "nohup": ("", ()), "command": ("", ()), "builtin": ("", ()), "exec": ("", ()),
    "chronic": ("", ()), "caffeinate": ("tw", ()), "time": ("", ()),
}


def strip_wrappers(words, cwd):
    """Remove assignments and wrapper commands; may change cwd (env -C)."""
    while words:
        while words and ASSIGN.match(words[0]):
            words = words[1:]
        if not words:
            break
        name = base(words[0])
        if name in KEYWORDS:
            words = words[1:]
            continue
        if name in ("timeout", "gtimeout"):
            found, rest = opts_until_operand(words[1:], "sk", ("--signal", "--kill-after"))
            words = rest[1:]  # drop the duration
            continue
        if name == "env":
            found, rest = opts_until_operand(words[1:], "uCS", ("--unset", "--chdir", "--split-string"))
            for d in opt_values(found, "-C", "--chdir"):
                cwd = resolve(d, cwd)
            while rest and ASSIGN.match(rest[0]):
                rest = rest[1:]
            words = rest
            continue
        if name in WRAPPERS:
            short, long_ = WRAPPERS[name]
            found, rest = opts_until_operand(words[1:], short, long_)
            words = rest
            continue
        break
    return words, cwd


def opts_until_operand(args, with_arg, long_with_arg):
    """Like opts(), but stops at the first operand (the wrapped command)."""
    i = 0
    while i < len(args) and args[i].startswith("-") and args[i] != "-":
        if args[i] == "--":
            return [], args[i + 1:]
        a = args[i]
        if a.startswith("--"):
            if "=" not in a and a in long_with_arg:
                i += 1
        elif a[-1] in with_arg and len(a) == 2:
            i += 1
        i += 1
    found, _ = opts(args[:i], with_arg, long_with_arg)
    return found, args[i:]


def base(word):
    b = re.split(r"[\\/]", word)[-1]
    return b[:-4] if b.lower().endswith(".exe") else b


def expand(word):
    home = os.path.expanduser("~")
    w = word.replace("${HOME}", home).replace("$HOME", home)
    if w == "~" or w.startswith("~/") or w.startswith("~\\"):
        w = home + w[1:]
    if os.name == "nt":
        m = re.match(r"^/([a-zA-Z])(/|$)", w)
        if m:
            w = m.group(1) + ":/" + w[3:]
    return w


def resolve(word, cwd):
    """Absolute path for word, or None when it can't be known (variables, remote)."""
    if word is None or word == "" or word == "-":
        return None
    w = expand(word)
    if "$" in w or "`" in w:
        return None
    if re.match(r"^[\w.-]+@?[\w.-]*:", w) and not re.match(r"^[a-zA-Z]:[\\/]", w):
        return None  # host:path or URL
    if not os.path.isabs(w):
        w = os.path.join(cwd, w)
    return os.path.normpath(w)


def targets(cmd, cwd, depth=0):
    """List of absolute paths the Bash command would write to."""
    if depth > 4:
        return []
    out = []
    stdin_bodies = []
    for c in commands(tokenize(cmd)):
        found, cwd = command_targets(c, cwd, stdin_bodies if c["piped"] else [], depth)
        out.extend(found)
        stdin_bodies = [h.body for h in c["heredocs"]]
    return out


def code_paths(code, cwd):
    """Quoted paths in interpreter code, when the code calls a write function."""
    if not WRITE_CODE.search(code):
        return []
    out = []
    for m in QUOTED.finditer(code):
        s = m.group(1) if m.group(1) is not None else m.group(2)
        if s and PATHLIKE.search(s) and "\n" not in s:
            p = resolve(s, cwd)
            if p:
                out.append(p)
    return out


def command_targets(c, cwd, stdin_bodies, depth):
    out = []
    for op, t in c["redirs"]:
        if op in WRITE_REDIRS and t is not None:
            if op == ">&" and (t.isdigit() or t == "-"):
                continue
            p = resolve(t, cwd)
            if p:
                out.append(p)
    words, cwd2 = strip_wrappers(list(c["words"]), cwd)
    bodies = [h.body for h in c["heredocs"]] or stdin_bodies
    if not words:
        return out, cwd
    name, args = base(words[0]), words[1:]
    res = lambda w: resolve(w, cwd2)  # noqa: E731

    def add(*ws):
        for w in ws:
            p = res(w)
            if p:
                out.append(p)

    if name in ("cd", "pushd"):
        a = [x for x in args if not x.startswith("-")]
        new = resolve(a[0], cwd) if a else os.path.expanduser("~")
        return out, (new or cwd)
    if name in SKIP_COMMANDS:
        return out, cwd
    if name in SHELLS:
        found, operands = opts(args, "co", ())
        code = opt_values(found, "-c")
        if code:
            out.extend(targets(code[0], cwd2, depth + 1))
        elif not operands:
            for b in bodies:
                out.extend(targets(b, cwd2, depth + 1))
    elif name == "eval":
        out.extend(targets(" ".join(args), cwd2, depth + 1))
    elif name in ("sed", "gsed"):
        inplace, script_given, files, i = False, False, [], 0
        while i < len(args):
            a = args[i]
            if a == "--":
                files.extend(args[i + 1:])
                break
            if a.startswith("--in-place"):
                inplace = True
            elif a in ("--expression", "--file"):
                script_given = True
                i += 1
            elif a.startswith("--expression=") or a.startswith("--file="):
                script_given = True
            elif a.startswith("--"):
                pass
            elif a.startswith("-") and len(a) > 1:
                for j, ch in enumerate(a[1:], 1):
                    if ch == "i":
                        inplace = True
                        if j == len(a) - 1 and i + 1 < len(args) and (
                                args[i + 1] == "" or re.match(r"^\.\w+$", args[i + 1])):
                            i += 1  # BSD suffix: sed -i '' / sed -i .bak
                        break
                    if ch in "ef":
                        script_given = True
                        if j == len(a) - 1:
                            i += 1
                        break
                    if ch == "l":
                        if j == len(a) - 1:
                            i += 1
                        break
            else:
                files.append(a)
            i += 1
        if inplace:
            add(*(files if script_given else files[1:]))
    elif name in ("perl", "ruby") or (name in INTERPRETERS and name.startswith("python")) \
            or name in ("node", "nodejs", "deno", "bun"):
        inplace, code, operands, i = False, [], [], 0
        code_flags = {"perl": "eE", "ruby": "e"}.get(name, "")
        if name.startswith("python"):
            code_flags = "c"
        if name in ("node", "nodejs", "bun"):
            code_flags = "ep"
        while i < len(args):
            a = args[i]
            if a in ("--eval", "--print") and i + 1 < len(args):
                code.append(args[i + 1])
                i += 2
                continue
            if a.startswith("--eval="):
                code.append(a.split("=", 1)[1])
            elif a == "--":
                operands.extend(args[i + 1:])
                break
            elif a.startswith("-") and len(a) > 1 and not a.startswith("--") and not operands:
                for j, ch in enumerate(a[1:], 1):
                    if ch == "i" and name in ("perl", "ruby"):
                        inplace = True
                        break
                    if ch in code_flags:
                        rest = a[j + 1:]
                        if rest:
                            code.append(rest)
                        elif i + 1 < len(args):
                            code.append(args[i + 1])
                            i += 1
                        break
                    if ch in "mMIlx0Cdm" and name in ("perl", "ruby"):
                        break
                    if ch == "m" and name.startswith("python"):
                        operands.append("-m")
                        break
            else:
                operands.append(a)
                if name.startswith("python") or name in ("node", "nodejs", "deno", "bun"):
                    operands.extend(args[i + 1:])
                    break
            i += 1
        if inplace:
            add(*(operands if code else operands[1:]))
        else:
            blobs = code or ([] if operands and operands[0] != "-" else bodies)
            for b in blobs:
                out.extend(code_paths(b, cwd2))
    elif name == "tee":
        found, operands = opts(args, "", ())
        add(*operands)
    elif name in ("rm", "rmdir", "unlink", "shred", "mkdir"):
        found, operands = opts(args, "mnuZ" if name in ("mkdir", "shred") else "", ("--mode",))
        add(*operands)
    elif name == "touch":
        found, operands = opts(args, "rdtA", ("--reference", "--date"))
        add(*operands)
    elif name == "truncate":
        found, operands = opts(args, "sr", ("--size", "--reference"))
        add(*operands)
    elif name in ("chmod", "chown", "chgrp", "chflags"):
        found, operands = opts(args, "", ("--reference",))
        if not any(k == "--reference" for k, _ in found):
            operands = operands[1:]
        add(*operands)
    elif name in ("cp", "install", "ln", "rsync", "ditto", "scp", "gcp", "ginstall"):
        with_arg = {"cp": "St", "gcp": "St", "install": "mogtS", "ginstall": "mogtS", "ln": "St",
                    "rsync": "efBTM", "scp": "cFiJlOoPS", "ditto": ""}[name]
        found, operands = opts(args, with_arg, ("--target-directory", "--suffix", "--mode", "--owner",
                                                 "--group", "--exclude", "--include", "--rsh",
                                                 "--filter", "--temp-dir", "--backup-dir"))
        tdir = opt_values(found, "-t", "--target-directory")
        if tdir and name not in ("rsync", "scp"):
            add(*tdir)
        elif name in ("install", "ginstall") and any(k in ("-d", "--directory") for k, _ in found):
            add(*operands)
        elif len(operands) >= 2:
            add(operands[-1])
        if name == "rsync" and any(k == "--remove-source-files" for k, _ in found):
            add(*operands[:-1])
    elif name in ("mv", "gmv"):
        found, operands = opts(args, "St", ("--target-directory", "--suffix"))
        add(*(opt_values(found, "-t", "--target-directory") + operands))
    elif name == "dd":
        add(*[a[3:] for a in args if a.startswith("of=")])
    elif name == "curl":
        found, operands = opts(args, "oHdXuAeEFKrTwxyzbcDmY", ("--output", "--header", "--data", "--request",
                                                              "--user", "--cookie", "--cookie-jar",
                                                              "--config", "--dump-header", "--form"))
        add(*opt_values(found, "-o", "--output", "-c", "--cookie-jar", "-D", "--dump-header"))
    elif name == "wget":
        found, operands = opts(args, "OPoaU", ("--output-document", "--directory-prefix"))
        add(*opt_values(found, "-O", "--output-document", "-P", "--directory-prefix"))
    elif name in ("tar", "gtar", "bsdtar"):
        first = args[0] if args else ""
        extract = (bool(first) and not first.startswith("-") and "x" in first) or any(
            a in ("--extract", "--get") or (a.startswith("-") and not a.startswith("--") and "x" in a)
            for a in args)
        if extract:
            found, _ = opts(args, "Cf", ("--directory", "--file"))
            dirs = opt_values(found, "-C", "--directory")
            if dirs:
                add(*dirs)
            else:
                out.append(cwd2)
    elif name == "unzip":
        found, _ = opts(args, "dx", ())
        dirs = opt_values(found, "-d")
        if dirs:
            add(*dirs)
        else:
            out.append(cwd2)
    elif name in ("patch", "gpatch"):
        found, operands = opts(args, "dDiopFrBVYzg", ("--directory", "--input", "--output"))
        dirs = opt_values(found, "-d", "--directory")
        outs = opt_values(found, "-o", "--output")
        if outs:
            add(*outs)
        elif operands:
            add(operands[0])
        else:
            add(*dirs) if dirs else out.append(cwd2)
    elif name == "git":
        gdir, i = cwd2, 0
        while i < len(args) and args[i].startswith("-"):
            a = args[i]
            if a == "-C" and i + 1 < len(args):
                gdir = resolve(args[i + 1], gdir) or gdir
                i += 1
            elif a == "-c" and i + 1 < len(args):
                i += 1
            elif a.startswith("--work-tree="):
                gdir = resolve(a.split("=", 1)[1], gdir) or gdir
            i += 1
        sub = args[i] if i < len(args) else ""
        rest = args[i + 1:]
        writes = {"apply", "am", "checkout", "restore", "reset", "commit", "stash", "switch", "merge",
                  "rebase", "pull", "cherry-pick", "revert", "clean", "rm", "mv"}
        if sub == "pull" and "--ff-only" in rest:
            pass  # updating from the remote is how an install is meant to change
        elif sub in writes:
            out.append(gdir)
        elif sub == "clone":
            found, operands = opts(rest, "objuc", ("--origin", "--branch", "--depth", "--reference",
                                                    "--template", "--config", "--separate-git-dir"))
            if len(operands) >= 2:
                p = resolve(operands[1], gdir)
                if p:
                    out.append(p)
    elif name == "find":
        starts = []
        for a in args:
            if a.startswith("-") or a in ("(", "!", ")"):
                break
            starts.append(a)
        starts = [resolve(s, cwd2) for s in starts] or [cwd2]
        starts = [s for s in starts if s]
        hit = "-delete" in args
        for k, a in enumerate(args):
            if a in ("-exec", "-execdir", "-ok", "-okdir"):
                sub = []
                for b in args[k + 1:]:
                    if b in (";", "+", "\\;"):
                        break
                    sub.append(b)
                for s in starts:
                    words2 = [s if w == "{}" else w for w in sub]
                    sc = {"words": words2, "redirs": [], "heredocs": [], "piped": False}
                    found2, _ = command_targets(sc, cwd2, [], depth + 1)
                    if found2:
                        out.extend(found2)
        if hit:
            out.extend(starts)
    return out, cwd
