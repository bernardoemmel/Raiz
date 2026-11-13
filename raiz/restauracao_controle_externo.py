"""Aquisição pública, limitada e conferida do controle externo do leste do Pará."""

from __future__ import annotations

import hashlib
import io
import tempfile
from pathlib import Path

import pandas as pd
import requests

from raiz import restauracao_validacao_regeneracao as V

CAMPO = {
    "url": "https://datadryad.org/downloads/file_stream/4843385",
    "sha256": "fbf6ba6b9e6e219badbcd38a5cea84fbfaf5d0f524f1ea5c4d0991694ede8bc3",
    "bytes": 15219,
    "licenca": "CC0-1.0",
    "atribuicao": "Cardoso et al. (2026), doi:10.5061/dryad.6t1g1jxdp",
}
MALHA = {
    "url": "https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/"
    "malhas_municipais/municipio_2025/UFs/PA/PA_Municipios_2025.zip",
    "sha256": "4005e1839471ecb7a9e94fbcde1e4563e6ad63291ed6a10694fe18a46b14519f",
    "bytes": 2587010,
    "licenca": "CC-BY-4.0",
    "atribuicao": "IBGE, Malha Municipal Digital 2025, Pará",
    "licenca_fonte": "https://www.ibge.gov.br/biblioteca/visualizacao/livros/liv102152.pdf",
}


def _baixar(fonte: dict) -> bytes:
    # Apenas endpoints públicos. Nenhum token, cookie, login ou tentativa de
    # contornar controle de acesso; falhas HTTP viram pendência explícita.
    partes, tamanho = [], 0
    with requests.get(fonte["url"], timeout=(15, 45), stream=True) as resposta:
        resposta.raise_for_status()
        for parte in resposta.iter_content(65536):
            tamanho += len(parte)
            if tamanho > fonte["bytes"]:
                raise ValueError("fonte excede o tamanho ancorado")
            partes.append(parte)
    bruto = b"".join(partes)
    if len(bruto) != fonte["bytes"] or hashlib.sha256(bruto).hexdigest() != fonte["sha256"]:
        raise ValueError("fonte diverge do tamanho ou SHA256 ancorados")
    return bruto


def avaliar(destino: Path) -> dict:
    """Publica resultado real ou impedimento; nunca substitui dados por exemplo."""
    import geopandas as gpd

    fontes = {"campo": CAMPO, "malha": MALHA}
    base = {"fontes": fontes, "modelo_versao": V.versao(), "erro_mg_ha_por_idade": None}
    try:
        campo = _baixar(CAMPO)
        # Nomes pessoais nem chegam à tabela de trabalho ou ao relatório.
        parcelas = pd.read_csv(io.BytesIO(campo), usecols=lambda c: c != "responsible")
        if len(parcelas) != 126:
            raise ValueError("controle requer as 126 parcelas publicadas")
        malha = _baixar(MALHA)
        with tempfile.TemporaryDirectory(prefix="raiz-malha-publica-") as pasta:
            arquivo = Path(pasta) / "PA.zip"
            arquivo.write_bytes(malha)
            municipios = gpd.read_file(f"zip://{arquivo}")
            vinculadas = V.vincular_municipios(parcelas, municipios)
        if vinculadas.cod_ibge.nunique() != 16:
            raise ValueError("vínculo espacial diverge dos 16 municípios publicados")
        resultado = V.validar_municipios(vinculadas, fonte_sha256=CAMPO["sha256"])
        resultado["fontes"] = fontes
        caminho = V.gravar(resultado, destino)
        return {
            **base,
            "status": "validado_fora_do_municipio",
            "arquivo": caminho.name,
            "sha256": hashlib.sha256(caminho.read_bytes()).hexdigest(),
            "erro_mg_ha_por_idade": resultado["metricas_por_idade"],
            "n_parcelas": 126,
            "n_municipios": 16,
        }
    except requests.HTTPError as erro:
        motivo = f"download público HTTP {erro.response.status_code}"
    except requests.RequestException as erro:
        motivo = f"download público indisponível ({type(erro).__name__})"
    except (ValueError, KeyError) as erro:
        # Não registrar conteúdo de linhas, nomes, URLs de redirecionamento ou
        # mensagens de parsers que possam incluir a observação original.
        motivo = f"conferência da fonte ou vínculo municipal falhou ({type(erro).__name__})"
    return {**base, "status": "pendente_fonte_conferida", "motivo": motivo}
