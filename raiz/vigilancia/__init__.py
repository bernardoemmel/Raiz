"""Vigilância das fazendas e dos projetos da Raíz.

Todo dia: lê os alertas públicos (MapBiomas Alerta, FIRMS NOAA-20/21, embargos do Ibama, DETER e PRODES), cruza com os
polígonos do CAR publicados no Release `dados` e com os polígonos dos projetos, e guarda cada alerta com a versão da
regra que o gerou. Perda dentro da área de um projeto vira evento de perda com o prazo da Verra (aviso em 30 dias e
relatório em 2 anos da descoberta), rascunho do relatório de perda e aviso ao cliente. Cada alerta pode ser marcado
depois como verdadeiro ou falso (campo, cliente, imagem nova ou fonte oficial), e a confiança dos próximos alertas
aprende com essas marcações.

Ver raiz/vigilancia/README.md.
"""

from pathlib import Path

PASTA = Path(__file__).resolve().parent
REPO = PASTA.parents[1]

__version__ = "0.1.0"
