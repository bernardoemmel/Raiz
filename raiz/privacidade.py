"""O modelo congelado de 2026 ainda importa raiz.privacidade. O código vive em protecao/privacidade.py."""

import sys

from raiz.protecao import privacidade as _modulo
from raiz.protecao.privacidade import *  # noqa: F403

sys.modules[__name__] = _modulo
