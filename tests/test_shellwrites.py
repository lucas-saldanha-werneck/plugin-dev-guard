#!/usr/bin/env python3
"""Which files does a Bash command write? Only real targets, never paths in the text.

Run: python3 -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hooks"))
import shellwrites  # noqa: E402

CWD = os.path.abspath(os.path.join(os.sep, "work", "repo"))
HOME = os.path.expanduser("~")
CACHE = "~/.claude/plugins/cache/mkt/tool/1.0.0"


def t(cmd, cwd=CWD):
    return shellwrites.targets(cmd, cwd)


def p(*parts):
    return os.path.normpath(os.path.join(*parts))


def h(rel):
    return p(HOME, rel)


CACHED = h(".claude/plugins/cache/mkt/tool/1.0.0")


class TextIsNotATarget(unittest.TestCase):
    """The known false positive: a cache path in the text, while the write goes to the repo."""

    def test_sed_script_mentions_cache(self):
        self.assertEqual(t("sed -i 's|%s/x|repo|' README.md" % CACHE), [p(CWD, "README.md")])

    def test_bsd_sed_script_mentions_cache(self):
        self.assertEqual(t("sed -i '' -e 's#%s#x#' docs/a.md" % CACHE), [p(CWD, "docs/a.md")])

    def test_heredoc_text_mentions_cache(self):
        cmd = "cat > notes.md <<'EOF'\nnever edit %s/hooks.json\nEOF\necho ok" % CACHE
        self.assertEqual(t(cmd), [p(CWD, "notes.md")])

    def test_commit_message_mentions_cache(self):
        self.assertEqual(t("git commit -m 'do not edit %s'" % CACHE), [CWD])

    def test_read_cache_then_write_repo(self):
        cmd = "grep -rn foo %s && sed -i s/a/b/ src/a.py" % CACHE
        self.assertEqual(t(cmd), [p(CWD, "src/a.py")])

    def test_copy_from_cache_into_repo(self):
        self.assertEqual(t("cp %s/a.py src/" % CACHE), [p(CWD, "src")])

    def test_diff_and_echo(self):
        self.assertEqual(t("diff -rq %s . ; echo '%s > x'" % (CACHE, CACHE)), [])

    def test_command_substitution_reads_only(self):
        self.assertEqual(t('x=$(ls %s); echo "$x" > out.txt' % CACHE), [p(CWD, "out.txt")])

    def test_find_exec_copies_out(self):
        self.assertEqual(t("find %s -name '*.py' -exec cp {} /tmp/x/ \\;" % CACHE), [p("/tmp/x")])

    def test_python_reads_cache(self):
        self.assertEqual(t("python3 -c \"print(open('%s/a.py').read())\"" % CACHE), [])


class RealTargets(unittest.TestCase):
    def test_redirect(self):
        self.assertEqual(t("echo hi > %s/f.txt 2>&1" % CACHE), [p(CACHED, "f.txt")])

    def test_append_and_ampersand_redirect(self):
        self.assertEqual(t("echo a >> x.log; ls &> y.log"), [p(CWD, "x.log"), p(CWD, "y.log")])

    def test_fd_duplication_is_not_a_file(self):
        self.assertEqual(t("ls 2>&1 >&2"), [])

    def test_sed_in_place(self):
        self.assertEqual(t("sed -i.bak -e s/a/b/ %s/a.py" % CACHE), [p(CACHED, "a.py")])

    def test_sed_without_in_place(self):
        self.assertEqual(t("sed s/a/b/ %s/a.py > out" % CACHE), [p(CWD, "out")])

    def test_perl_in_place(self):
        self.assertEqual(t("perl -pi -e 's/a/b/' %s/a.py" % CACHE), [p(CACHED, "a.py")])

    def test_tee(self):
        self.assertEqual(t("echo x | sudo tee -a %s/a" % CACHE), [p(CACHED, "a")])

    def test_cp_destination(self):
        self.assertEqual(t("cp -r src/. %s/" % CACHE), [CACHED])

    def test_cp_target_directory(self):
        self.assertEqual(t("cp -t %s a b" % CACHE), [CACHED])

    def test_mv_moves_source_away(self):
        self.assertEqual(t("mv %s/a.py /tmp/" % CACHE), [p(CACHED, "a.py"), p("/tmp")])

    def test_rm_touch_chmod(self):
        self.assertEqual(t("rm -rf %s/x; touch y; chmod +x z" % CACHE),
                         [p(CACHED, "x"), p(CWD, "y"), p(CWD, "z")])

    def test_cd_changes_where_relative_paths_go(self):
        self.assertEqual(t("cd %s && sed -i s/a/b/ x.py" % CACHE), [p(CACHED, "x.py")])

    def test_wrappers(self):
        self.assertEqual(t("FOO=1 timeout 5 nice -n 3 rm -f a"), [p(CWD, "a")])

    def test_env_chdir(self):
        self.assertEqual(t("env -C /a BAR=2 touch b"), [p("/a/b")])

    def test_bash_c(self):
        self.assertEqual(t("bash -c 'echo x >> %s/f'" % CACHE), [p(CACHED, "f")])

    def test_heredoc_fed_to_shell(self):
        self.assertEqual(t("bash <<'EOF'\nrm %s/f\nEOF" % CACHE), [p(CACHED, "f")])

    def test_heredoc_piped_to_shell(self):
        self.assertEqual(t("cat <<'EOF' | sh\ntouch %s/f\nEOF" % CACHE), [p(CACHED, "f")])

    def test_python_heredoc_writes(self):
        cmd = "python3 - <<'EOF'\nopen('%s/f', 'w').write('1')\nEOF" % CACHE
        self.assertEqual(t(cmd), [p(CACHED, "f")])

    def test_node_writes(self):
        self.assertEqual(t("node -e \"require('fs').writeFileSync('%s/b.txt','x')\"" % CACHE),
                         [p(CACHED, "b.txt")])

    def test_git_changes_work_tree(self):
        self.assertEqual(t("git -C ~/.claude/plugins/marketplaces/mkt reset --hard"),
                         [h(".claude/plugins/marketplaces/mkt")])

    def test_git_update_is_allowed(self):
        self.assertEqual(t("git -C ~/.claude/plugins/marketplaces/mkt pull --ff-only; git status"), [])

    def test_find_delete(self):
        self.assertEqual(t("find %s -name '*.pyc' -delete" % CACHE), [CACHED])

    def test_find_exec_sed(self):
        self.assertEqual(t("find %s -name '*.py' -exec sed -i s/a/b/ {} +" % CACHE), [CACHED])

    def test_curl_dd_tar(self):
        self.assertEqual(t("curl -sL -o o.json https://x/y; dd if=a of=b; tar -xzf a.tgz -C /d"),
                         [p(CWD, "o.json"), p(CWD, "b"), p("/d")])

    def test_home_variable(self):
        self.assertEqual(t('echo x > "$HOME/.claude/plugins/cache/mkt/tool/1.0.0/f"'), [p(CACHED, "f")])

    def test_unknown_variable_is_skipped(self):
        self.assertEqual(t('echo x > "$DIR/f"'), [])

    def test_comment_is_ignored(self):
        self.assertEqual(t("ls # > %s/f" % CACHE), [])


if __name__ == "__main__":
    unittest.main()
