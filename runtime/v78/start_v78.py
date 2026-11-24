"""Explicit v78 entry point; the v77 rollback files and model paths stay intact."""
import gc
import sys

for directory in ('/flash/mikan-v60', '/flash/mikan-v78-ui'):
    if directory not in sys.path:
        sys.path.insert(0, directory)
for module in ('pfld_app', 'pfld_tracking', 'screen_ui'):
    sys.modules.pop(module, None)
gc.collect()

from pfld_app import run
from pfld_tracking import DENSE_EYE_MODEL

run(model=DENSE_EYE_MODEL, follow_pitch=False, reuse_static_center=True,
    use_eyelids=True, spatial_eyelids=True, recover_faces=True, responsive=True)
