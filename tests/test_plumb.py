"""Behavioural tests over the fixture repo. Stdlib unittest, zero deps."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plumb.extract import extract_file
from plumb.ground_truth import RepoIndex
from plumb.model import Kind, Status
from plumb.verify import verify_all

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "stale_repo"
CTX = ROOT / "CLAUDE.md"


def _results():
    claims = extract_file(str(CTX))
    index = RepoIndex(str(ROOT))
    results = verify_all(claims, index)
    return {(r.claim.kind, r.claim.raw): r.status for r in results}


class ExtractTests(unittest.TestCase):
    def test_finds_expected_kinds(self):
        kinds = {c.kind for c in extract_file(str(CTX))}
        self.assertIn(Kind.PATH, kinds)
        self.assertIn(Kind.SYMBOL, kinds)
        self.assertIn(Kind.DEPENDENCY, kinds)
        self.assertIn(Kind.URL, kinds)

    def test_no_false_path_from_prose(self):
        # "and/or" style tokens must not become path claims.
        claims = extract_file(str(CTX))
        raws = {c.raw for c in claims}
        self.assertNotIn("and/or", raws)

    def test_slash_command_not_path(self):
        from plumb.extract import _is_path_token
        # Slash-commands are not filesystem paths.
        self.assertFalse(_is_path_token("/impeccable"))
        self.assertFalse(_is_path_token("/tdd"))
        # API routes and web asset paths are not filesystem paths.
        self.assertFalse(_is_path_token("/api/auth/verify-otp"))
        self.assertFalse(_is_path_token("/photos/wild-1.jpg"))
        # Real absolute paths and home paths are.
        self.assertTrue(_is_path_token("/Users/x/y"))
        self.assertTrue(_is_path_token("/tmp/foo"))
        self.assertTrue(_is_path_token("~/projects/x"))


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.r = _results()

    def test_present_path_verified(self):
        self.assertEqual(self.r[(Kind.PATH, "./src/app.py")], Status.VERIFIED)

    def test_missing_relative_path_stale(self):
        self.assertEqual(self.r[(Kind.PATH, "./src/deleted.py")], Status.STALE)

    def test_missing_home_path_stale(self):
        self.assertEqual(self.r[(Kind.PATH, "~/definitely/missing/xyz123")], Status.STALE)

    def test_defined_symbol_verified(self):
        self.assertEqual(self.r[(Kind.SYMBOL, "build_app")], Status.VERIFIED)

    def test_removed_symbol_stale(self):
        self.assertEqual(self.r[(Kind.SYMBOL, "removed_helper")], Status.STALE)

    def test_declared_dependency_verified(self):
        self.assertEqual(self.r[(Kind.DEPENDENCY, "requests")], Status.VERIFIED)

    def test_missing_dependency_stale(self):
        self.assertEqual(self.r[(Kind.DEPENDENCY, "flask")], Status.STALE)

    def test_referenced_but_undefined_symbol_unverifiable(self):
        # `req` appears in code (a param) but is defined nowhere -> not stale.
        self.assertEqual(self.r[(Kind.SYMBOL, "req")], Status.UNVERIFIABLE)

    def test_url_unverifiable(self):
        self.assertEqual(self.r[(Kind.URL, "https://example.com/docs")], Status.UNVERIFIABLE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
