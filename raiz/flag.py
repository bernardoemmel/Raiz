"""O modelo congelado de 2026 ainda faz `from raiz.flag import _mb`. O código vive em medicao/flag.py."""

import sys

from raiz.medicao import flag as _modulo
from raiz.medicao.flag import *  # noqa: F403

sys.modules[__name__] = _modulo
