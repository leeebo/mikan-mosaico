"""Application decisions only: no model, crop or measurement changes."""

CAT, OVERLAY, RAW = 0, 1, 2
MODE_NAMES = ('CAT', 'OVERLAY', 'RAW')


def change_mode(mode, held_ms):
    return CAT if held_ms >= 650 else (mode + 1) % 3


def safe_mode(mode, tracking, diagnostics=False):
    # Diagnostics are an explicitly enabled developer view, never a button mode.
    if diagnostics:
        return CAT
    return CAT if mode == OVERLAY and not tracking else mode


def eye_states(gaps, close_gap):
    """Each current valid measurement maps directly; no history or coupling."""
    return tuple(1. if gap is not None and gap <= close_gap else 0. for gap in gaps)
