from __future__ import annotations

import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which("fzf"), "real fzf binary not installed")
class RealFzfIntegrationTests(unittest.TestCase):
    def test_with_nth_keeps_original_token_in_output(self) -> None:
        line = "entry:vocab:奇跡\t/tmp/preview\t[單字] 奇跡 きせき／N1\tki se ki kiseki\n"
        proc = subprocess.run(
            [
                "fzf",
                "--delimiter=\t",
                "--with-nth=3",
                "--filter=奇跡",
            ],
            input=line,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(proc.stdout.startswith("entry:vocab:奇跡\t"))


if __name__ == "__main__":
    unittest.main()
