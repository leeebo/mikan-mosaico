"""Installed as /flash/main.py only after the complete candidate is verified."""
import sys

try:
    exec(open('/flash/mikan-v80-direct/start.py').read())
except KeyboardInterrupt:
    raise
except Exception as error:
    # A missing asset or failed model must never launch a raw-camera example.
    import uvc
    uvc.reset()
    sys.print_exception(error)
    print('MIKAN_SAFE_STOP')
    try:
        from screen_ui import safe_idle
        reason = 'CAMERA UNAVAILABLE' if 'camera' in str(error).lower() else 'APP UNAVAILABLE'
        safe_idle('/flash/mikan-v80-direct/mikan-ui.pack', reason)
    except KeyboardInterrupt:
        raise
    except Exception as display_error:
        uvc.reset()
        sys.print_exception(display_error)
        print('MIKAN_SAFE_NO_DISPLAY')
