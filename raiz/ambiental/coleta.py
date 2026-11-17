"""Coleta da camada de vegetação e relevo (workflow coletar-ambiental.yml, publica no Release insumos).

  ambiental_vegetacao.parquet  Mapa de Vegetação do IBGE 1:250 000 (versão 2026) já classificado para a reserva
                               legal (floresta, cerrado, campos, transicao) e marcado na Lei da Mata Atlântica
  ambiental_cobertura.json     o que cada fonte entregou nesta coleta (vegetacao, relevo, terraclass)
  terraclass_<bioma>_<ano>*.tif (+ .json da legenda)  só quando houver link direto em ambiental.yaml (terraclass.urls)

O ANADEM não é baixado: a tarefa lê por janela direto do servidor da ANA. A coleta só confere se ele responde.
Sem dado pessoal: são mapas de vegetação, uso da terra e relevo.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import time
from pathlib import Path

import httpx

from raiz.ambiental import vegetacao as VG
from raiz.ambiental.status import NOMES, regra

log = logging.getLogger(__name__)


def _baixar(url: str, destino: Path, tentativas: int = 5) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(destino.suffix + ".tmp")
    for i in range(tentativas):
        try:
            with httpx.stream("GET", url, follow_redirects=True, timeout=600) as r:
                r.raise_for_status()
                with open(tmp, "wb") as o:
                    for ch in r.iter_bytes(1 << 20):
                        o.write(ch)
            tmp.replace(destino)
            return destino
        except (httpx.HTTPError, OSError) as ex:
            if i == tentativas - 1:
                raise
            espera = 30 * 2**i
            log.warning("%s: tentativa %d falhou (%s); espero %d s", url, i + 1, str(ex)[:120], espera)
            time.sleep(espera)
    return destino


def _relevo_responde(r: dict) -> dict:
    url = r["relevo"]["anadem_url"].format(tile="22M")
    try:
        h = httpx.head(url, follow_redirects=True, timeout=60)
        ok = h.status_code == 200
        return {"estado": "consultado" if ok else "indisponivel", "url": url, "http": h.status_code,
                "leitura": "por janela, direto do servidor"}  # fmt: skip
    except httpx.HTTPError as ex:
        return {"estado": "indisponivel", "url": url, "erro": str(ex)[:200]}


def coletar(saida: str | Path, trabalho: str | Path | None = None, zip_ibge: str | Path | None = None) -> dict:
    """Baixa e prepara tudo em `saida`. trabalho: onde guardar o zip do IBGE (padrão: saida/_bruto)."""
    r = regra()
    saida = Path(saida)
    saida.mkdir(parents=True, exist_ok=True)
    trabalho = Path(trabalho) if trabalho else saida / "_bruto"
    hoje = dt.date.today().isoformat()
    fontes: dict[str, dict] = {}
    try:
        z = Path(zip_ibge) if zip_ibge else _baixar(VG.URL_IBGE, trabalho / "vege_area.zip")
        info = VG.preparar(z, saida / NOMES["vegetacao"], r)
        fontes["vegetacao"] = {
            "estado": "consultado", "url": VG.URL_IBGE, "versao": "ibge-250mil-2026", "consultado_em": hoje, **info,
            "lei_mata_atlantica": "proxy_ibge_250mil (o IBGE publica o mapa da lei só em PDF)",
        }  # fmt: skip
    except Exception as ex:  # noqa: BLE001 - registra e segue: sem mapa, a tarefa marca nao_verificado
        fontes["vegetacao"] = {"estado": "indisponivel", "erro": str(ex)[:300], "consultado_em": hoje}
    fontes["relevo"] = {**_relevo_responde(r), "consultado_em": hoje}
    urls = r["terraclass"].get("urls") or []
    tc = []
    for u in urls:
        try:
            nome = u.rsplit("/", 1)[-1]
            _baixar(u, saida / nome)
            tc.append(nome)
        except Exception as ex:  # noqa: BLE001
            log.warning("terraclass %s: %s", u, ex)
    fontes["terraclass"] = (
        {"estado": "consultado", "arquivos": tc, "consultado_em": hoje}
        if tc
        else {
            "estado": "indisponivel",
            "consultado_em": hoje,
            "motivo": "o portal do TerraClass só entrega o arquivo numa sessão do navegador (sem link direto nem "
            "API pública); ver docs/vegetacao-relevo.md",
        }  # fmt: skip
    )
    m = {"gerado_em": hoje, "regra": r["versao"], "fontes": fontes}
    (saida / NOMES["cobertura"]).write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    return m
