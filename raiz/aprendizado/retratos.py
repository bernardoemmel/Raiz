"""Retratos imutáveis das chamadas reais, antes de existir conexão com PostgreSQL.

O nome é o SHA-256 do JSON canônico descomprimido; gzip tem relógio zero. Somente
colunas normalizadas pelo contrato público chegam ao disco. A hora é capturada
por este processo, nunca pelo ano da fonte ou pelo mtime de uma saída antiga.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import os
import re
import tempfile
import zlib
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import from_wkt

from raiz import RAIZ_REPO
from raiz.aprendizado.arquivo_historico import _normalizar
from raiz.aprendizado.reexecucao import FONTES, HistoricoInsuficiente

FORMATO = 1
MAX_DESCOMPRIMIDO = 512 * 1024 * 1024
MAX_COMPRIMIDO = 64 * 1024 * 1024 - 128 * 1024


def pasta_padrao() -> Path:
    return Path(os.environ.get("RAIZ_HISTORICO_DIR", RAIZ_REPO / "dados" / "historico_aprendizado"))


def canonico(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def descomprimir(dados: bytes, limite: int) -> bytes:
    """Um único membro gzip, sem nome/comentário/extra/relógio nem bytes ocultos."""
    if len(dados) < 18 or dados[:8] != b"\x1f\x8b\x08\x00\x00\x00\x00\x00":
        raise HistoricoInsuficiente("gzip com formato ou metadados proibidos")
    dec = zlib.decompressobj(wbits=31)
    try:
        bruto = dec.decompress(dados, limite + 1)
    except zlib.error:
        raise HistoricoInsuficiente("gzip inválido") from None
    if len(bruto) > limite or dec.unconsumed_tail:
        raise HistoricoInsuficiente("gzip ultrapassa o limite descomprimido")
    if not dec.eof or dec.unused_data:
        raise HistoricoInsuficiente("gzip truncado ou com conteúdo adicional")
    return bruto


def quadros(dados: dict) -> dict[str, pd.DataFrame]:
    """Reconstrói apenas as colunas do contrato, inclusive em fontes vazias."""
    out = {}
    for nome, linhas in dados.items():
        if nome not in FONTES or not isinstance(linhas, list):
            raise HistoricoInsuficiente("fonte inválida no retrato")
        esp = FONTES[nome]
        campos = [*esp.campos, *(["geom"] if esp.geometria else [])]
        esperados = {*campos, "_chave", "_linha_hash"}
        if any(not isinstance(li, dict) or set(li) != esperados for li in linhas):
            raise HistoricoInsuficiente("campos inválidos no retrato")
        df = pd.DataFrame(linhas, columns=campos)
        if esp.geometria:
            geom = [from_wkt(v) for v in df.pop("geom")]
            df = gpd.GeoDataFrame(df, geometry=geom, crs=4674)
        out[nome] = df
    return out


def validar_retrato(caminho: Path) -> dict:
    """Confere formato, integridade e lista positiva de dados antes de usar/publicar."""
    if caminho.stat().st_size > MAX_COMPRIMIDO:
        raise HistoricoInsuficiente("retrato ultrapassa o limite de transporte")
    bruto = descomprimir(caminho.read_bytes(), MAX_DESCOMPRIMIDO)
    h = hashlib.sha256(bruto).hexdigest()
    if caminho.name != f"{h}.json.gz":
        raise HistoricoInsuficiente("hash do retrato não corresponde ao nome")
    obj = json.loads(bruto)
    esperados = {
        "formato",
        "uf",
        "municipio",
        "observado_em",
        "tarefa",
        "tarefa_versao",
        "captura_versao",
        "dados",
        "indisponiveis",
    }
    if not isinstance(obj, dict) or set(obj) != esperados or obj["formato"] != FORMATO:
        raise HistoricoInsuficiente("formato de retrato desconhecido")
    from raiz.executor.tarefas import COD_UF, CODIGO

    if obj["uf"] not in COD_UF or not re.fullmatch(r"\d{7}", str(obj["municipio"])):
        raise HistoricoInsuficiente("município ou UF inválido no retrato")
    if str(obj["municipio"])[:2] != str(COD_UF[obj["uf"]]):
        raise HistoricoInsuficiente("município não pertence à UF do retrato")
    if obj["tarefa"] not in CODIGO or not re.fullmatch(r"[a-z_]+-[a-f0-9]{12}", obj["tarefa_versao"]):
        raise HistoricoInsuficiente("versão da tarefa inválida no retrato")
    if not re.fullmatch(r"[a-f0-9]{64}", obj["captura_versao"]):
        raise HistoricoInsuficiente("versão da captura inválida no retrato")
    instante = dt.datetime.fromisoformat(obj["observado_em"])
    if instante.tzinfo is None or instante.utcoffset() != dt.timedelta(0):
        raise HistoricoInsuficiente("observação sem data UTC")
    if not isinstance(obj["indisponiveis"], list) or set(obj["indisponiveis"]) - set(FONTES):
        raise HistoricoInsuficiente("fontes indisponíveis inválidas no retrato")
    normalizado = _normalizar(quadros(obj["dados"]), exigir_completo=False)
    normalizado = {n: sorted(rs, key=lambda x: x["_chave"]) for n, rs in normalizado.items()}
    if canonico({**obj, "dados": normalizado}) != bruto:
        raise HistoricoInsuficiente("retrato fora do contrato público canônico")
    return obj


def guardar(captura, tarefa: str, pasta: Path | None = None) -> dict:
    from raiz.executor.tarefas import versao

    dados = captura.fontes_validas()
    if not dados:
        return {"situacao": "sem_captura", "indisponiveis": sorted(captura.indisponiveis)}
    normalizado = _normalizar(dados, exigir_completo=False)
    arquivos = ("retratos.py", "captura.py", "arquivo_historico.py", "reexecucao.py")
    codigo = b"".join((Path(__file__).parent / nome).read_bytes() for nome in arquivos)
    obj = {
        "formato": FORMATO,
        "uf": captura.uf.upper(),
        "municipio": captura.municipio,
        "observado_em": dt.datetime.now(dt.UTC).isoformat(),
        "tarefa": tarefa,
        "tarefa_versao": versao(tarefa),
        "captura_versao": hashlib.sha256(codigo).hexdigest(),
        "dados": {n: sorted(rs, key=lambda x: x["_chave"]) for n, rs in normalizado.items()},
        "indisponiveis": sorted(captura.indisponiveis),
    }
    bruto = canonico(obj)
    if len(bruto) > MAX_DESCOMPRIMIDO:
        raise HistoricoInsuficiente("retrato ultrapassa o limite descomprimido")
    comprimido = gzip.compress(bruto, mtime=0)
    if len(comprimido) > MAX_COMPRIMIDO:
        raise HistoricoInsuficiente("retrato ultrapassa o limite de transporte")
    h = hashlib.sha256(bruto).hexdigest()
    destino = (pasta or pasta_padrao()) / obj["uf"] / str(obj["municipio"]) / f"{h}.json.gz"
    destino.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destino.parent, suffix=".tmp", delete=False) as f:
        temp = Path(f.name)
        f.write(comprimido)
        f.flush()
        os.fsync(f.fileno())
    try:
        # link não substitui um retrato existente, mesmo entre processos.
        try:
            os.link(temp, destino)
        except FileExistsError:
            validar_retrato(destino)
    finally:
        temp.unlink(missing_ok=True)
    return {
        "situacao": "guardado",
        "retrato_hash": h,
        "observado_em": obj["observado_em"],
        "contagens": {n: len(rs) for n, rs in normalizado.items()},
        "indisponiveis": obj["indisponiveis"],
    }
