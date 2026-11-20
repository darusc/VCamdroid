"""Tests for marshaling background callbacks onto the GUI thread."""

from __future__ import annotations

import threading
import unittest

from vcamdroid.ui_dispatch import UiDispatcher


class UiDispatcherTests(unittest.TestCase):
    def test_tasks_run_in_post_order_on_drain(self) -> None:
        dispatcher = UiDispatcher()
        results: list[str] = []
        dispatcher.post(lambda: results.append("first"))
        dispatcher.post(lambda: results.append("second"))

        self.assertEqual(dispatcher.drain(), 2)
        self.assertEqual(results, ["first", "second"])
        self.assertEqual(dispatcher.drain(), 0)

    def test_posts_from_worker_threads_are_serialized(self) -> None:
        dispatcher = UiDispatcher()
        results: list[int] = []
        threads = [
            threading.Thread(target=lambda i=i: dispatcher.post(lambda: results.append(i)))
            for i in range(5)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(dispatcher.drain(), 5)
        self.assertEqual(sorted(results), [0, 1, 2, 3, 4])

    def test_failing_task_does_not_block_later_tasks(self) -> None:
        dispatcher = UiDispatcher()
        errors: list[Exception] = []
        results: list[str] = []

        def fail() -> None:
            raise RuntimeError("bad callback")

        dispatcher.post(fail)
        dispatcher.post(lambda: results.append("ok"))
        count = dispatcher.drain(on_error=errors.append)

        self.assertEqual(count, 2)
        self.assertEqual(results, ["ok"])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)


if __name__ == "__main__":
    unittest.main()
