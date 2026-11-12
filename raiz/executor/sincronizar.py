"""O back-end lê o armazém: espelha os arquivos do motor numa pasta local e carrega no banco o que mudou (todo o
estado, ou um município sob demanda quando alguém pede um imóvel que ainda não foi carregado)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from raiz.executor.armazem import Armazem, sha256_arquivo


def espelho_local() -> Path:
    from raiz import RAIZ_REPO
    from raiz.config import config

    p = Path(getattr(config(), "armazem_espelho_dir", None) or RAIZ_REPO / "dados" / "armazem_local")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _indice(destino: Path) -> dict:
    f = destino / ".indice.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def _gravar_indice(destino: Path, ind: dict) -> None:
    f = destino / ".indice.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(ind), encoding="utf-8")
    tmp.replace(f)


def sincronizar(armazem: Armazem, destino: Path | None = None, ufs: list[str] | None = None,
                filtro: re.Pattern | None = None) -> list[str]:  # fmt: skip
    """Baixa para destino/saida/<UF>/ o que mudou no armazém (compara o sha256 dos metadados). Devolve as chaves."""
    destino = Path(destino or espelho_local())
    destino.mkdir(parents=True, exist_ok=True)
    ind = _indice(destino)
    mudou = []
    prefixos = [f"saida/{u.upper()}/" for u in ufs] if ufs else ["saida/"]
    for pre in prefixos:
        for chave in armazem.listar(pre):
            if filtro is not None and not filtro.search(chave):
                continue
            meta = armazem.meta(chave) or {}
            sha = meta.get("sha256")
            local = destino / chave
            if sha and ind.get(chave) == sha and local.exists():
                continue
            if armazem.baixar(chave, local):
                ind[chave] = sha or sha256_arquivo(local)
                mudou.append(chave)
    _gravar_indice(destino, ind)
    return mudou


def carregar(engine, armazem: Armazem, ufs: list[str] | None = None, destino: Path | None = None,
             congelar: bool = True) -> dict:  # fmt: skip
    """Sincroniza e leva ao banco cada município que mudou (a carga contínua compara a assinatura dos arquivos)."""
    from raiz.carga_continua import varrer

    destino = Path(destino or espelho_local())
    mudou = sincronizar(armazem, destino, ufs)
    r = varrer(engine, destino / "saida", ufs, congelar=congelar, estavel_s=0)
    r["baixados"] = len(mudou)
    return r


def sob_demanda(engine, armazem: Armazem, cod_ibge: int, destino: Path | None = None) -> bool:
    """Carrega um município do armazém para o banco na hora em que alguém pede (True se carregou)."""
    import datetime as dt

    from raiz.carga import carregar_municipio, depois_da_carga
    from raiz.executor.tarefas import COD_UF

    uf = next((u for u, c in COD_UF.items() if str(cod_ibge).startswith(str(c))), None)
    if uf is None:
        return False
    destino = Path(destino or espelho_local())
    mudou = sincronizar(armazem, destino, [uf], re.compile(rf"_{int(cod_ibge)}\.[a-z]+$"))
    pasta = destino / "saida" / uf
    if not (pasta / f"imoveis_{int(cod_ibge)}.csv").exists():
        return False
    with engine.begin() as con:
        carregar_municipio(con, pasta, int(cod_ibge), dt.date.today())
    depois_da_carga(engine, int(cod_ibge))
    return bool(mudou) or True
