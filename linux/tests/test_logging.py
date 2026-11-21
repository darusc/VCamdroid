from __future__ import annotations

import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import vcamdroid_linux


class LogFileTests(unittest.TestCase):
    def test_xdg_state_home_is_used(self) -> None:
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": "/custom/state"}, clear=False):
            self.assertEqual(
                vcamdroid_linux.log_file_path(),
                Path("/custom/state/vcamdroid/vcamdroid.log"),
            )

    def test_defaults_to_local_state(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "XDG_STATE_HOME"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(
            Path, "home", return_value=Path("/home/tester")
        ):
            self.assertEqual(
                vcamdroid_linux.log_file_path(),
                Path("/home/tester/.local/state/vcamdroid/vcamdroid.log"),
            )

    def test_setup_logging_writes_file(self) -> None:
        root = logging.getLogger()
        previous_handlers = root.handlers[:]
        previous_level = root.level
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with mock.patch.dict(os.environ, {"XDG_STATE_HOME": tmp}, clear=False):
                    path = vcamdroid_linux.setup_logging()
                    self.assertIsNotNone(path)
                    assert path is not None

                    logging.getLogger("vcamdroid-test").warning("hello log")
                    for handler in root.handlers:
                        handler.flush()

                    self.assertIn("hello log", path.read_text(encoding="utf-8"))
        finally:
            for handler in root.handlers:
                handler.close()
            root.handlers = previous_handlers
            root.setLevel(previous_level)


if __name__ == "__main__":
    unittest.main()
