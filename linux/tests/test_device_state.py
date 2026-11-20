"""Tests for device-selection state used by the GUI dropdown."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from vcamdroid.device_state import device_labels, resolve_selection


def _session(client_id: int, name: str) -> SimpleNamespace:
    return SimpleNamespace(client_id=client_id, descriptor=SimpleNamespace(name=name))


class DeviceStateTests(unittest.TestCase):
    def test_first_device_becomes_selected(self) -> None:
        sessions = {7: _session(7, "Pixel 8")}
        active, label = resolve_selection(None, sessions)
        self.assertEqual(active, 7)
        self.assertEqual(label, "[7] Pixel 8")
        self.assertEqual(device_labels(sessions), ["[7] Pixel 8"])

    def test_existing_selection_is_kept_when_another_device_connects(self) -> None:
        sessions = {7: _session(7, "Pixel 8"), 8: _session(8, "Pixel 9")}
        active, label = resolve_selection(8, sessions)
        self.assertEqual(active, 8)
        self.assertEqual(label, "[8] Pixel 9")
        self.assertEqual(device_labels(sessions), ["[7] Pixel 8", "[8] Pixel 9"])

    def test_disconnected_active_falls_back_to_remaining_device(self) -> None:
        sessions = {8: _session(8, "Pixel 9")}
        active, label = resolve_selection(7, sessions)
        self.assertEqual(active, 8)
        self.assertEqual(label, "[8] Pixel 9")

    def test_no_devices_clears_selection(self) -> None:
        active, label = resolve_selection(7, {})
        self.assertIsNone(active)
        self.assertEqual(label, "")


if __name__ == "__main__":
    unittest.main()
