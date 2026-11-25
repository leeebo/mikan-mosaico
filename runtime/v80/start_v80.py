"""Explicit v80 entry: each launch starts with the private cat view."""
import gc
import sys

for directory in ('/flash/mikan-v60', '/flash/mikan-v80-direct'):
    if directory not in sys.path:
        sys.path.insert(0, directory)
for module in ('pfld_app', 'pfld_tracking', 'screen_ui', 'product_policy', 'raw_video'):
    sys.modules.pop(module, None)
gc.collect()

from pfld_app import run
from pfld_tracking import DENSE_EYE_MODEL

run(model=DENSE_EYE_MODEL, follow_pitch=False, reuse_static_center=True,
    use_eyelids=True, spatial_eyelids=True, recover_faces=True, responsive=True)
