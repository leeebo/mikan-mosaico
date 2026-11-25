"""Portable checks for direct current-eye mapping and three product modes."""
import json
from product_policy import CAT, OVERLAY, RAW, eye_states, change_mode, safe_mode

checks = []


def expect(name, actual, expected):
    assert actual == expected, (name, actual, expected)
    checks.append(name)


mode = CAT
for index, expected in enumerate((OVERLAY, RAW, CAT, OVERLAY)):
    mode = change_mode(mode, 100)
    expect('short-cycle-' + str(index), mode, expected)
for mode in (CAT, OVERLAY, RAW):
    expect('long-private-' + str(mode), change_mode(mode, 650), CAT)
    expect('tracked-output-' + str(mode), safe_mode(mode, True), mode)
    expect('diagnostic-default-' + str(mode), safe_mode(mode, True, True), CAT)
expect('overlay-loss-private', safe_mode(OVERLAY, False), CAT)
expect('raw-is-explicit', safe_mode(RAW, False), RAW)

# Each call stands alone. A first observation is sufficient on either side.
for name, gaps, expected in (
    ('both-open', (.2, .2), (0., 0.)),
    ('both-closed', (.03, .04), (1., 1.)),
    ('left-first-frame', (.03, .2), (1., 0.)),
    ('right-first-frame', (.2, .03), (0., 1.)),
    ('left-unknown-right-closed', (None, .03), (0., 1.)),
    ('right-unknown-left-closed', (.03, None), (1., 0.)),
    ('both-unknown-neutral', (None, None), (0., 0.)),
    ('old-deadband-now-open', (.098, .03), (0., 1.)),
    ('at-closed-threshold', (.096, .096), (1., 1.)),
    ('just-above-threshold', (.096001, .096001), (0., 0.)),
    ('nan-neutral-independent', (float('nan'), .03), (0., 1.)),
    ('release-immediately', (.2, .2), (0., 0.)),
    ('repeat-close-no-wait', (.03, .03), (1., 1.)),
    ('opposite-next-call', (.2, .03), (0., 1.)),
):
    expect(name, eye_states(gaps, .096), expected)
print('PRODUCT_POLICY_PASS', json.dumps({'checks': len(checks), 'names': checks}))
