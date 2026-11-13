"""O back-end lê o armazém: espelha os arquivos do motor numa pasta local e carrega no banco o que mudou (todo o
estado, ou um município sob demanda quando alguém pede um imóvel que ainda não foi carregado)."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from raiz.executor.armazem import Armazem, ArmazemRelease, sha256_arquivo


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
    with tempfile.NamedTemporaryFile(dir=destino, suffix=".indice.tmp", mode="w", delete=False) as arquivo:
        arquivo.write(json.dumps(ind))
        tmp = Path(arquivo.name)
    try:
        tmp.replace(f)
    finally:
        tmp.unlink(missing_ok=True)


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
            if not local.resolve().is_relative_to(destino.resolve()):
                raise ValueError("chave do armazém fora do espelho")
            if sha and ind.get(chave) == sha and local.exists() and sha256_arquivo(local) == sha:
                continue
            local.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=local.parent, suffix=".download", delete=False) as f:
                temporario = Path(f.name)
            try:
                if not armazem.baixar(chave, temporario):
                    raise FileNotFoundError("arquivo listado não foi disponibilizado pelo armazém")
                recebido = sha256_arquivo(temporario)
                if sha and recebido != sha:
                    raise ValueError("conteúdo do armazém diverge do SHA256")
                temporario.replace(local)
                ind[chave] = recebido
                mudou.append(chave)
            finally:
                temporario.unlink(missing_ok=True)
    _gravar_indice(destino, ind)
    return mudou


def _ufs_privadas(armazem: Armazem, ufs: list[str] | None) -> list[str]:
    if isinstance(armazem, ArmazemRelease):
        armazem._exigir_privado()
        disponiveis = armazem.manifesto(fresco=True).get("estados", {})
    else:
        disponiveis = {c.split("/")[1] for c in armazem.listar("saida/") if len(c.split("/")) >= 3}
    escolhidas = ufs if ufs is not None else disponiveis
    if any(not re.fullmatch(r"[A-Z]{2}", str(u).upper()) for u in escolhidas):
        raise ValueError("sigla de estado inválida")
    return sorted({u.upper() for u in escolhidas})


def carregar(engine, armazem: Armazem, ufs: list[str] | None = None, destino: Path | None = None,
             congelar: bool = True, reprocessar: bool = False) -> dict:  # fmt: skip
    """Sincroniza e leva ao banco cada município que mudou (a carga contínua compara a assinatura dos arquivos)."""
    from raiz.carga_continua import varrer
    from raiz.prospeccao_cobertura import reindexar

    destino = Path(destino or espelho_local())
    selecionadas = _ufs_privadas(armazem, ufs)
    r = {"carregados": [], "pulados": 0, "esperando": [], "falhas": [], "resumos": [], "baixados": 0}
    for uf in selecionadas:
        try:
            if isinstance(armazem, ArmazemRelease):
                # Uma instância longa não pode manter o pacote da primeira volta para sempre.
                armazem.garantir_uf(uf, forcar=True)
            mudou = sincronizar(armazem, destino, [uf])
            parte = varrer(
                engine,
                destino / "saida",
                [uf],
                congelar=congelar,
                estavel_s=0,
                reprocessar=reprocessar,
                reindexar_fontes=False,
            )
            r["baixados"] += len(mudou)
            r["pulados"] += parte.get("pulados", 0)
            for campo in ("carregados", "esperando", "falhas", "resumos"):
                r[campo].extend(parte.get(campo, []))
        except Exception as ex:  # noqa: BLE001 - a UF incompleta não entra; as demais continuam
            r["falhas"].append({"chave": uf, "erro": type(ex).__name__})
    from raiz.aprendizado.importacao import receber

    try:
        r["historico_aprendizado"] = receber(engine, armazem, destino / "historico", ufs)
    except Exception as ex:  # noqa: BLE001 - os retratos têm checkpoint próprio e serão retomados
        r["historico_aprendizado"] = {"pendente": True}
        r["falhas"].append({"chave": "historico_aprendizado", "erro": type(ex).__name__})
    r["fichas"] = reindexar(engine)
    return r


def sob_demanda(engine, armazem: Armazem, cod_ibge: int, destino: Path | None = None) -> bool:
    """Carrega um município do armazém para o banco na hora em que alguém pede (True se carregou)."""
    import datetime as dt

    from raiz.carga import carregar_municipio, depois_da_carga
    from raiz.executor.tarefas import COD_UF

    uf = next((u for u, c in COD_UF.items() if str(cod_ibge).startswith(str(c))), None)
    if uf is None:
        return False
    _ufs_privadas(armazem, [uf])
    if isinstance(armazem, ArmazemRelease):
        armazem.garantir_uf(uf, forcar=True)
    destino = Path(destino or espelho_local())
    mudou = sincronizar(armazem, destino, [uf], re.compile(rf"_{int(cod_ibge)}\.[a-z]+$"))
    pasta = destino / "saida" / uf
    if not (pasta / f"imoveis_{int(cod_ibge)}.csv").exists():
        return False
    with engine.begin() as con:
        carregar_municipio(con, pasta, int(cod_ibge), dt.date.today())
    depois_da_carga(engine, int(cod_ibge), estrito=True)
    return bool(mudou) or True
