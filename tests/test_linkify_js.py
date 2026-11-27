"""Tests for linkify() in web/static/app.js (clickable links in chat), run under Node.

linkify() escapes chat text for HTML and turns any URLs in it into links that
open in a new tab. Skipped when Node.js is not installed.

Run from the repo root:  .venv/bin/python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest

_REPO: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP_JS: str = os.path.join(_REPO, "web", "static", "app.js")
_NODE: str | None = shutil.which("node")

# Loads app.js into a sandbox (with a stub document) and prints linkify() for
# each string read from stdin as a JSON array.
_HARNESS: str = """
const fs = require("fs");
const vm = require("vm");
const ctx = { document: { addEventListener: () => {} }, String, JSON, console };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[process.argv.length - 1], "utf8") + "\\nthis.linkify = linkify;", ctx);
const inputs = JSON.parse(fs.readFileSync(0, "utf8"));
console.log(JSON.stringify(inputs.map((s) => ctx.linkify(s))));
"""

_ATTRS: str = 'target="_blank" rel="noopener noreferrer"'


def _link(href: str, label: str | None = None) -> str:
    """The anchor linkify() is expected to produce."""
    result: str = f'<a class="msg-link" href="{href}" {_ATTRS}>{label if label is not None else href}</a>'
    return result


@unittest.skipIf(_NODE is None, "Node.js is not installed")
class LinkifyTests(unittest.TestCase):
    """linkify() output for chat text with and without links."""

    def _run(self, *inputs: str | None) -> list[str]:
        """Runs linkify() over each input under Node."""
        proc: subprocess.CompletedProcess[str] = subprocess.run(
            [str(_NODE), "-e", _HARNESS, _APP_JS],
            input=json.dumps(list(inputs)),
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        result: list[str] = json.loads(proc.stdout)
        return result

    def test_plain_text_is_escaped_only(self) -> None:
        """Text without links comes back escaped, with no anchors."""
        out: list[str] = self._run("hello <b>mesh</b> & \"friends\"", "", None)
        self.assertEqual(out, ["hello &lt;b&gt;mesh&lt;/b&gt; &amp; &quot;friends&quot;", "", ""])

    def test_http_and_https_links(self) -> None:
        """http:// and https:// URLs become new-tab links; surrounding text stays."""
        out: list[str] = self._run("see https://example.com/a?b=1&c=2 now", "http://10.0.0.5:7331/map")
        self.assertEqual(out[0], "see " + _link("https://example.com/a?b=1&amp;c=2") + " now")
        self.assertEqual(out[1], _link("http://10.0.0.5:7331/map"))

    def test_www_gets_https(self) -> None:
        """A bare www. address links to https:// but shows as typed."""
        out: list[str] = self._run("go to www.meshtastic.org")
        self.assertEqual(out[0], "go to " + _link("https://www.meshtastic.org", "www.meshtastic.org"))

    def test_trailing_punctuation_left_out(self) -> None:
        """Sentence punctuation after a URL is not part of the link."""
        out: list[str] = self._run("Try https://example.com.", "(https://example.com/x)", "https://a.io/b, ok?")
        self.assertEqual(out[0], "Try " + _link("https://example.com") + ".")
        self.assertEqual(out[1], "(" + _link("https://example.com/x") + ")")
        self.assertEqual(out[2], _link("https://a.io/b") + ", ok?")

    def test_balanced_paren_kept(self) -> None:
        """A closing paren that belongs to the URL (Wikipedia style) stays in it."""
        url: str = "https://en.wikipedia.org/wiki/Mesh_(disambiguation)"
        out: list[str] = self._run(url, f"({url})")
        self.assertEqual(out[0], _link(url))
        self.assertEqual(out[1], "(" + _link(url) + ")")

    def test_several_links(self) -> None:
        """Every URL in a message is linked."""
        out: list[str] = self._run("a https://one.io b https://two.io")
        self.assertEqual(out[0], "a " + _link("https://one.io") + " b " + _link("https://two.io"))

    def test_no_script_injection(self) -> None:
        """Quotes and angle brackets can't break out of the link or its href."""
        out: list[str] = self._run('https://x.io/"onmouseover="alert(1)', "https://x.io/<script>")
        self.assertEqual(out[0], _link("https://x.io/") + "&quot;onmouseover=&quot;alert(1)")
        self.assertEqual(out[1], _link("https://x.io/") + "&lt;script&gt;")

    def test_other_schemes_not_linked(self) -> None:
        """Only http(s) and www. are linked, never javascript: or similar."""
        out: list[str] = self._run("javascript:alert(1)", "ftp://files.example.com", "https://", "www.")
        self.assertEqual(out, ["javascript:alert(1)", "ftp://files.example.com", "https://", "www."])


if __name__ == "__main__":
    unittest.main()
