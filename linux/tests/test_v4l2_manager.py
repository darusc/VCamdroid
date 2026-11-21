import subprocess
import unittest
from unittest import mock

from vcamdroid.v4l2_manager import refresh_pipewire_cameras


class RefreshPipewireCamerasTests(unittest.TestCase):
    @mock.patch("vcamdroid.v4l2_manager.subprocess.run")
    def test_success(self, run: mock.Mock) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, "", "")

        ok, detail = refresh_pipewire_cameras()

        self.assertTrue(ok)
        self.assertEqual(detail, "")
        run.assert_called_once_with(
            ["systemctl", "--user", "restart", "wireplumber.service"],
            capture_output=True,
            text=True,
            timeout=15,
        )

    @mock.patch("vcamdroid.v4l2_manager.subprocess.run")
    def test_systemctl_failure(self, run: mock.Mock) -> None:
        run.return_value = subprocess.CompletedProcess([], 1, "", "no session bus")

        ok, detail = refresh_pipewire_cameras()

        self.assertFalse(ok)
        self.assertIn("no session bus", detail)

    @mock.patch(
        "vcamdroid.v4l2_manager.subprocess.run",
        side_effect=OSError("systemctl not found"),
    )
    def test_missing_systemctl(self, run: mock.Mock) -> None:
        ok, detail = refresh_pipewire_cameras()

        self.assertFalse(ok)
        self.assertIn("systemctl not found", detail)


if __name__ == "__main__":
    unittest.main()
