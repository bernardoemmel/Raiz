"""O modelo congelado de 2026 ainda faz `from raiz import restauracao_geo`. O código vive em restauracao/geo.py."""

import sys

from raiz.restauracao import geo as _modulo
from raiz.restauracao.geo import *  # noqa: F403

sys.modules[__name__] = _modulo
