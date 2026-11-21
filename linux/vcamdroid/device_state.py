"""Pure helpers for device-selection state (no Tk dependencies)."""

from __future__ import annotations

from .server import ClientSession


def device_label(session: ClientSession) -> str:
    return f"[{session.client_id}] {session.descriptor.name}"


def device_labels(sessions: dict[int, ClientSession]) -> list[str]:
    return [device_label(session) for session in sessions.values()]


def resolve_selection(
    active_client_id: int | None,
    sessions: dict[int, ClientSession],
) -> tuple[int | None, str]:
    """Return the active id and its dropdown label.

    Keeps the current selection when it is still connected, otherwise falls
    back to the first available session, otherwise to no selection.
    """
    if active_client_id in sessions:
        return active_client_id, device_label(sessions[active_client_id])
    if sessions:
        first_id = next(iter(sessions))
        return first_id, device_label(sessions[first_id])
    return None, ""
