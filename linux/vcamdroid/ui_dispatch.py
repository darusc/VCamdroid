"""Thread-safe dispatch of callables to a GUI main loop.

Tkinter may only be touched from the thread that created it. Background
threads post closures here; the GUI thread drains them from its event loop.
"""

from __future__ import annotations

import queue
from collections.abc import Callable


class UiDispatcher:
    """Collect callables from worker threads and run them on the GUI thread."""

    def __init__(self) -> None:
        self._queue: queue.Queue[Callable[[], None]] = queue.Queue()

    def post(self, task: Callable[[], None]) -> None:
        """Queue a callable from any thread."""
        self._queue.put_nowait(task)

    def drain(self, on_error: Callable[[Exception], None] | None = None) -> int:
        """Run all queued callables. Must be called from the GUI thread."""
        ran = 0
        while True:
            try:
                task = self._queue.get_nowait()
            except queue.Empty:
                return ran
            try:
                task()
            except Exception as exc:
                if on_error is not None:
                    on_error(exc)
            ran += 1
