"""Quiet fixed-width activity chrome; never reads pixels or queues render work."""
from __future__ import annotations

from time import monotonic


ACTIVITY_WIDTH = 5
ACTIVITY_INTERVAL = .125


def activity_fragments(viewer, *, now: float | None = None) -> list[tuple[str, str]]:
    """Three ASCII dots with one moving bead, occupying five cells even when idle.

    The phase uses elapsed time, not repaint count or Z/T index. Fast retargeting
    cannot reset it or widen the title. ASCII is deliberate: the indicator also
    works with strict-ASCII artwork, one-bit terminals and non-Unicode encodings.
    """
    if not viewer.activity_pending:
        return [("class:activity", " " * ACTIVITY_WIDTH)]
    phase = int((monotonic() if now is None else now) / ACTIVITY_INTERVAL) % 4
    active = (0, 1, 2, 1)[phase]
    return [("class:activity", " "),
            *(("class:activity" if index == active else "class:activity.dim",
               "o" if index == active else ".") for index in range(3)),
            ("class:activity", " ")]
