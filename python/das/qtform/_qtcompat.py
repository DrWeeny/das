"""
das.qtform._qtcompat  -  compatibility re-export
================================================
The Qt binding shim moved to :mod:`das._qtcompat` when das.qtui started
sharing it (one binding ladder for both renderers).  This module keeps the old
import path working:

    from das.qtform._qtcompat import app_exec      # still fine

New code should import from ``das._qtcompat`` directly.
"""

from das._qtcompat import *          # noqa: F401,F403
from das._qtcompat import (          # noqa: F401  (names the star import skips)
    _BINDING, qt_py, QtCompat,
)