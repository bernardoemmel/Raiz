"""Configuração lida do ambiente (e do arquivo .env na raiz do repositório, que nunca vai para o git).

Variáveis:
  ANTHROPIC_API_KEY            chave da API da Anthropic (também aceita RAIZ_ANTHROPIC_API_KEY)
  RAIZ_MODELO_DOCUMENTO        modelo que lê certidão e edital (padrão claude-opus-5-5)
  RAIZ_ESFORCO_DOCUMENTO       esforço do modelo: low, medium, high, xhigh, max (padrão high)
  FIRECRAWL_API_KEY            chave do Firecrawl (opcional): páginas que só abrem no navegador ou bloqueiam o servidor
  RAIZ_DOCUMENTOS_DIR          onde ficam o armazém, as saídas e os documentos gerados (padrão dados/documentos)
  RAIZ_DOCUMENTOS_ENTRADA      pastas com as saídas do motor e do produto, separadas por ":" (padrão motor/saida,
                               dados/estados e dados/amostra)
  RAIZ_CONTATO                 como o dono fala com a Raíz (aparece na folha do dono)
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

MODELO_PADRAO = "claude-opus-5-5"
ESFORCO_PADRAO = "high"
ESFORCOS = ("low", "medium", "high", "xhigh", "max")

UF_POR_CODIGO = {
    "11": "RO",
    "12": "AC",
    "13": "AM",
    "14": "RR",
    "15": "PA",
    "16": "AP",
    "17": "TO",
    "21": "MA",
    "22": "PI",
    "23": "CE",
    "24": "RN",
    "25": "PB",
    "26": "PE",
    "27": "AL",
    "28": "SE",
    "29": "BA",
    "31": "MG",
    "32": "ES",
    "33": "RJ",
    "35": "SP",
    "41": "PR",
    "42": "SC",
    "43": "RS",
    "50": "MS",
    "51": "MT",
    "52": "GO",
    "53": "DF",
}


@lru_cache
def _carregar_env() -> None:
    """Lê o .env da raiz do repositório sem sobrescrever o que já está no ambiente. Nunca imprime valores."""
    arq = REPO / ".env"
    if not arq.is_file():
        return
    for linha in arq.read_text(encoding="utf-8", errors="ignore").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        k, v = linha.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v


def env(nome: str, padrao: str | None = None) -> str | None:
    _carregar_env()
    v = os.environ.get(nome)
    return v if v not in (None, "") else padrao


def chave_anthropic() -> str | None:
    return env("RAIZ_ANTHROPIC_API_KEY") or env("ANTHROPIC_API_KEY")


def chave_firecrawl() -> str | None:
    return env("FIRECRAWL_API_KEY") or env("RAIZ_FIRECRAWL_API_KEY")


def modelo_documento() -> str:
    return env("RAIZ_MODELO_DOCUMENTO", MODELO_PADRAO)


def esforco_documento() -> str:
    e = env("RAIZ_ESFORCO_DOCUMENTO", ESFORCO_PADRAO)
    return e if e in ESFORCOS else ESFORCO_PADRAO


def pasta_dados() -> Path:
    p = Path(env("RAIZ_DOCUMENTOS_DIR") or REPO / "dados" / "documentos")
    p.mkdir(parents=True, exist_ok=True)
    return p


def pastas_entrada() -> list[Path]:
    v = env("RAIZ_DOCUMENTOS_ENTRADA")
    if v:
        return [Path(x) for x in v.split(os.pathsep) if x]
    return [REPO / "motor" / "saida", REPO / "dados" / "estados", REPO / "dados" / "amostra"]


def uf_do_municipio(cod_municipio: int | str) -> str | None:
    return UF_POR_CODIGO.get(str(cod_municipio)[:2])


def municipio_do_imovel(cod_imovel: str) -> int | None:
    """O código do CAR traz o município: PA-1504950-0E3B... -> 1504950."""
    partes = str(cod_imovel).split("-")
    if len(partes) >= 2 and partes[1].isdigit() and len(partes[1]) == 7:
        return int(partes[1])
    return None


def contato() -> str:
    return env("RAIZ_CONTATO", "pelo WhatsApp da Raíz, no número que mandou esta folha")
