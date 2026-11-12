#!/usr/bin/env python3
"""plugin-dev-check against real git repos in a fake home folder."""
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import FakeHome, git, write  # noqa: E402


class Check(unittest.TestCase):
    def setUp(self):
        self.f = FakeHome()
        repo = self.f.myplug
        shutil.rmtree(os.path.join(repo, ".git"))
        git(repo, "init", "-q", "-b", "main")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "one")
        self.first = git(repo, "rev-parse", "HEAD")
        write(os.path.join(repo, "a.txt"), "a")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "two")
        self.head = git(repo, "rev-parse", "HEAD")

    def tearDown(self):
        self.f.cleanup()

    def install(self, sha):
        write(os.path.join(self.f.plugins, "installed_plugins.json"), {"version": 2, "plugins": {
            "myplug@mine": [{"scope": "user", "version": "0.1.0", "gitCommitSha": sha,
                             "installPath": os.path.join(self.f.plugins, "cache", "mine", "myplug", "0.1.0")}]}})

    def test_behind_main_exits_1(self):
        self.install(self.first)
        code, out = self.f.check()
        self.assertEqual(code, 1, out)
        self.assertIn("behind main by 1", out)
        self.assertIn("claude plugin update myplug@mine", out)

    def test_up_to_date_exits_0(self):
        self.install(self.head)
        code, out = self.f.check()
        self.assertEqual(code, 0, out)
        self.assertIn("= main", out)
        self.assertIn("Fix: nothing", out)

    def test_markdown(self):
        self.install(self.head)
        code, out = self.f.check("--md")
        self.assertIn("| repo | branch |", out)
        self.assertIn("| myplug | main | 0 |", out)

    def test_install_dir_with_edits(self):
        inst = os.path.join(self.f.home, ".local", "share", "my-cli-src")
        src = os.path.join(self.f.src, "my-cli")
        os.makedirs(src)
        git(src, "init", "-q", "-b", "main")
        write(os.path.join(src, "main.py"), "print(1)\n")
        git(src, "add", "-A")
        git(src, "commit", "-qm", "init")
        git(self.f.home, "clone", "-q", src, inst)
        write(os.path.join(inst, "main.py"), "print(2)\n")
        self.f.set_config({"sources": self.f.src, "install_dirs": {"my-cli": "~/.local/share/my-cli-src"}})
        self.install(self.head)
        code, out = self.f.check()
        self.assertEqual(code, 1, out)
        self.assertIn("1 tracked file(s) edited in the install dir", out)

    def test_every_installation_is_checked(self):  # PDG-04
        cache = os.path.join(self.f.plugins, "cache", "mine", "myplug", "0.1.0")
        write(os.path.join(self.f.plugins, "installed_plugins.json"), {"version": 2, "plugins": {
            "myplug@mine": [{"scope": "user", "version": "0.1.0", "gitCommitSha": self.head, "installPath": cache},
                            {"scope": "project", "version": "0.1.0", "gitCommitSha": self.first,
                             "installPath": cache, "projectPath": "/p"}]}})
        code, out = self.f.check()
        self.assertEqual(code, 1, out)
        self.assertIn("behind main by 1", out)

    def test_no_sources(self):
        self.f.set_config({})
        code, out = self.f.check()
        self.assertEqual(code, 0, out)
        self.assertIn("No source repos found", out)


if __name__ == "__main__":
    unittest.main()
