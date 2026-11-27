"""O modelo congelado de 2026 ainda faz `from raiz import vazamento`. O código vive em protecao/vazamento.py."""

import sys

from raiz.protecao import vazamento as _modulo
from raiz.protecao.vazamento import *  # noqa: F403

sys.modules[__name__] = _modulo
