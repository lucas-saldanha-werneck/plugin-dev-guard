#!/usr/bin/env python3
"""Feed PreToolUse JSON to the hook in a fake home folder and check allow/deny and the message."""
import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import FakeHome, write  # noqa: E402

TOOL = "~/.claude/plugins/cache/theirs/tool/1.0.0"
MINE = "~/.claude/plugins/cache/mine/myplug/0.1.0"


class Hook(unittest.TestCase):
    def setUp(self):
        self.f = FakeHome()

    def tearDown(self):
        self.f.cleanup()

    def cached(self, rel):
        return os.path.join(self.f.plugins, "cache", *rel.split("/"))

    # --- what is stopped -------------------------------------------------
    def test_edit_installed_copy_with_local_source(self):
        msg = self.f.edit(self.cached("mine/myplug/0.1.0/hooks/x.py"))
        self.assertIn("INSTALLED copy of myplug", msg)
        self.assertIn(self.f.myplug, msg)
        self.assertNotIn("fork", msg)

    def test_write_third_party_plugin_points_to_fork_and_pr(self):
        msg = self.f.edit(self.cached("theirs/tool/1.0.0/a.md"), tool="Write")
        self.assertIn("https://github.com/author/tool", msg)
        self.assertIn("fork", msg)
        self.assertIn("pull request", msg)
        self.assertIn("Never patch the installed copy", msg)

    def test_relative_plugin_in_third_party_marketplace(self):
        msg = self.f.edit(self.cached("theirs/inner/2.0.0/a.md"))
        self.assertIn("https://github.com/author/their-plugins (folder plugins/inner)", msg)

    def test_marketplace_clone(self):
        msg = self.f.bash("rm -rf ~/.claude/plugins/marketplaces/theirs/plugins")
        self.assertIn("https://github.com/author/their-plugins", msg)

    def test_directory_marketplace_points_to_its_folder(self):
        msg = self.f.edit(self.cached("local/lp/0.0.1/x"))
        self.assertIn(os.path.join(self.f.local_mkt, "lp"), msg)

    def test_bash_redirect_into_cache(self):
        self.assertIsNotNone(self.f.bash("echo x >> %s/hooks.json" % MINE))

    def test_bash_sed_in_place_in_cache(self):
        self.assertIsNotNone(self.f.bash("sed -i 's/a/b/' %s/x.py" % TOOL))

    def test_bash_relative_target_after_cd(self):
        self.assertIsNotNone(self.f.bash("cd %s && rm x.py" % TOOL))

    def test_relative_target_inside_cache_cwd(self):
        self.assertIsNotNone(self.f.bash("touch x.py", cwd=self.cached("theirs/tool/1.0.0")))

    def test_install_dir(self):
        inst = os.path.join(self.f.home, ".local", "share", "my-cli-src")
        os.makedirs(inst)
        self.f.set_config({"sources": self.f.src, "install_dirs": ["~/.local/share/my-cli-src"],
                           "exempt": ["~/.local/share/my-cli-src/logs"]})
        msg = self.f.bash("echo x > ~/.local/share/my-cli-src/main.py")
        self.assertIn("INSTALLED copy of my-cli", msg)
        self.assertIsNone(self.f.bash("echo x >> ~/.local/share/my-cli-src/logs/run.log"))

    def test_tip_is_added(self):
        self.f.set_config({"tip": "Then add a to-do."})
        self.assertTrue(self.f.edit(self.cached("theirs/tool/1.0.0/a")).endswith("Then add a to-do."))

    # --- the known false positive ----------------------------------------
    def test_text_mentions_cache_but_writes_repo(self):
        cmd = "sed -i 's|%s/hooks|hooks|' ~/src/myplug/README.md" % MINE
        self.assertIsNone(self.f.bash(cmd))

    def test_heredoc_mentions_cache_but_writes_repo(self):
        cmd = "cat > ~/src/myplug/NOTES.md <<'EOF'\nThe installed copy is %s.\nEOF" % MINE
        self.assertIsNone(self.f.bash(cmd))

    def test_copy_out_of_cache_and_compare(self):
        cmd = "cp %s/a.py ~/src/myplug/ && diff -rq %s ~/src/myplug" % (MINE, MINE)
        self.assertIsNone(self.f.bash(cmd))

    def test_commit_message_mentions_cache(self):
        cmd = "git -C ~/src/myplug commit -am 'stop editing %s'" % MINE
        self.assertIsNone(self.f.bash(cmd))

    # --- what passes -----------------------------------------------------
    def test_edit_source_repo(self):
        self.assertIsNone(self.f.edit(os.path.join(self.f.myplug, "README.md")))

    def test_update_from_remote(self):
        self.assertIsNone(self.f.bash("git -C ~/.claude/plugins/marketplaces/mine pull --ff-only"))

    def test_guard_mine_skips_third_party(self):
        self.f.set_config({"owner": "me", "guard": "mine"})
        self.assertIsNone(self.f.edit(self.cached("theirs/tool/1.0.0/a")))
        self.assertIsNotNone(self.f.edit(self.cached("mine/myplug/0.1.0/a")))

    def test_explicit_marketplace_list(self):
        self.f.set_config({"guard": "mine", "marketplaces": ["theirs"]})
        self.assertIsNotNone(self.f.edit(self.cached("theirs/tool/1.0.0/a")))
        self.assertIsNone(self.f.edit(self.cached("mine/myplug/0.1.0/a")))

    def test_pass_file(self):
        msg = self.f.edit(self.cached("theirs/tool/1.0.0/a"))
        self.assertIn("plugin-dev-guard.pass", msg)
        pf = os.path.join(self.f.home, ".claude", "state", "plugin-dev-guard.pass")
        write(pf, "")
        self.assertIsNone(self.f.edit(self.cached("theirs/tool/1.0.0/a")))
        old = time.time() - 31 * 60
        os.utime(pf, (old, old))
        self.assertIsNotNone(self.f.edit(self.cached("theirs/tool/1.0.0/a")))

    def test_bad_input_passes(self):
        self.assertIsNone(self.f.run_hook("not json"))
        self.assertIsNone(self.f.run_hook({"tool_name": "Read", "tool_input": {"file_path": TOOL}}))

    def test_broken_config_means_defaults(self):
        write(self.f.config, "{not json")
        self.assertIsNotNone(self.f.edit(self.cached("theirs/tool/1.0.0/a")))

    # --- settings file ---------------------------------------------------
    def test_seed_creates_and_never_overwrites(self):
        os.remove(self.f.config)
        self.f.run_hook({}, "--seed")
        with open(self.f.config, encoding="utf-8") as fh:
            cfg = json.load(fh)
        self.assertEqual(cfg["guard"], "all")
        write(self.f.config, {"owner": "x"})
        self.f.run_hook({}, "--seed")
        with open(self.f.config, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"owner": "x"})


if __name__ == "__main__":
    unittest.main()
