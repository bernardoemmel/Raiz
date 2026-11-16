"""Conferência atual do SICAR somente das fazendas selecionadas para um lote.

O retrato nacional não é alterado. Um desenho novo só entra na oferta depois
de recalcular o município numa pasta isolada; falha preserva o insumo recebido
e impede usar créditos calculados sobre o desenho anterior.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from raiz.coleta.car_nacional import trava

COLUNAS = (
    "cod_imovel",
    "id",
    "status_imovel",
    "dat_criacao",
    "data_atualizacao",
    "area",
    "condicao",
    "uf",
    "municipio",
    "cod_municipio_ibge",
    "m_fiscal",
    "tipo_imovel",
    "geometry",
)
MARCAS = ("car_conferido_em", "car_conferencia", "car_situacao", "car_geometria_alterada")


class ConferenciaPendente(RuntimeError):
    """O lote não pode usar cálculos anteriores a uma alteração no CAR."""


def consultar(uf: str, codigos: set[str]) -> gpd.GeoDataFrame:
    """Consulta paginada por códigos, sem baixar todo o município e sem dados de pessoas."""
    from raiz import MOTOR_DIR
    from raiz.coleta import wfs

    if not re.fullmatch(r"[A-Z]{2}", uf) or any(
        not re.fullmatch(rf"{uf}-\d{{7}}-[A-Za-z0-9.\-]{{1,64}}", c) for c in codigos
    ):
        raise ValueError("Código CAR inválido para a conferência")
    if str(MOTOR_DIR) not in sys.path:
        sys.path.insert(0, str(MOTOR_DIR))
    import raiz_estado as R

    partes = []
    ordenados = sorted(codigos)
    for inicio in range(0, len(ordenados), 50):
        lista = ",".join("'" + c + "'" for c in ordenados[inicio : inicio + 50])
        g = wfs.ler(
            R.S, wfs.Camada(R.CAR_WFS, f"sicar:sicar_imoveis_{uf.lower()}"), "cod_imovel", f"cod_imovel IN ({lista})"
        )
        if len(g):
            partes.append(g[[c for c in COLUNAS if c in g]])
    if not partes:
        return gpd.GeoDataFrame({"cod_imovel": []}, geometry=[], crs=4674)
    return gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), crs=partes[0].crs)


def comparar(base: gpd.GeoDataFrame, atual: gpd.GeoDataFrame, codigos: set[str], quando: str) -> tuple:
    """Sem confirmação, só a fazenda afetada sai do lote. Divergência nunca conserva crédito antigo."""
    base = base.to_crs(4674).copy().set_index("cod_imovel", drop=False)
    atual = atual.to_crs(4674).copy()
    if not {"status_imovel", "tipo_imovel"} <= set(atual) and len(atual):
        raise ConferenciaPendente("WFS atual sem situação cadastral")
    duplicados = set(atual.loc[atual.cod_imovel.duplicated(keep=False), "cod_imovel"])
    atual = atual.drop_duplicates("cod_imovel").set_index("cod_imovel", drop=False)
    mudou, marcas = False, {}
    for cod in sorted(codigos):
        marca = {
            "car_conferido_em": None,
            "car_conferencia": "CAR a conferir",
            "car_situacao": "a_conferir",
            "car_geometria_alterada": False,
        }
        marcas[cod] = marca
        if cod not in base.index or cod not in atual.index or cod in duplicados:
            continue
        li, geom = atual.loc[cod], atual.loc[cod].geometry
        if (
            geom is None
            or geom.is_empty
            or not geom.is_valid
            or geom.geom_type not in ("Polygon", "MultiPolygon")
            or not np.isfinite(geom.bounds).all()
            or geom.area <= 0
        ):
            continue
        marca.update(
            car_conferido_em=quando, car_conferencia=f"CAR conferido em {quando[:10]}", car_situacao="conferido"
        )
        if li.status_imovel not in ("AT", "PE", "SU") or li.tipo_imovel != "IRU":
            marca["car_situacao"] = "fora_do_lote"
            continue
        anterior = base.loc[cod].geometry
        geometria_mudou = anterior is None or not anterior.equals(geom)
        # Módulos fiscais e situação também afetam o funil, mesmo com contorno igual.
        mf_antes, mf_agora = base.loc[cod].get("m_fiscal"), li.get("m_fiscal")
        mesmo_mf = (pd.isna(mf_antes) and pd.isna(mf_agora)) or mf_antes == mf_agora
        atributos_mudaram = not mesmo_mf or any(
            str(base.loc[cod].get(k)) != str(li.get(k)) for k in ("status_imovel", "tipo_imovel")
        )
        mudou |= geometria_mudou or atributos_mudaram
        marca["car_geometria_alterada"] = geometria_mudou
        for k in COLUNAS:
            if k in atual and k != "cod_imovel":
                base.loc[cod, k] = li[k]
    return base.reset_index(drop=True), marcas, mudou


def _csv(t: pd.DataFrame, arquivo: Path) -> None:
    tmp = arquivo.with_suffix(f".{os.getpid()}.tmp")
    t.to_csv(tmp, index=False)
    os.replace(tmp, arquivo)


def recalcular(pasta: Path, uf: str, cod: int, entrada: Path, trabalho: Path) -> None:
    """Processo separado: o chdir e os módulos globais do motor não vazam para a API."""
    from raiz import RAIZ_REPO
    from raiz.funil.rodar import dir_trabalho

    trabalho.mkdir(parents=True, exist_ok=True)
    cache = trabalho / "cache"
    if not cache.exists():
        origem = dir_trabalho().resolve() / "cache"
        origem.mkdir(parents=True, exist_ok=True)
        cache.symlink_to(origem, target_is_directory=True)
    env = {**os.environ, "RAIZ_MOTOR_DIR_TRABALHO": str(trabalho), "RAIZ_SEM_BANCO": "1"}
    # O diagnóstico privado fica junto ao checkpoint; nunca despejar resposta WFS nos logs do lote.
    with (trabalho / "recalculo.log").open("ab") as log:
        r = subprocess.run(
            [sys.executable, "-m", "raiz.coleta.car_conferencia", uf, str(cod), str(entrada)],
            cwd=RAIZ_REPO,
            env=env,
            stdout=log,
            stderr=log,
            check=False,
        )
    if r.returncode:
        raise ConferenciaPendente("CAR atualizado preservado; recálculo pendente antes da entrada no lote")
    resultado = trabalho / "saida" / uf
    for arquivo in resultado.glob(f"*_{cod}.*"):
        temporario = pasta / (arquivo.name + ".car-atual.tmp")
        shutil.copyfile(arquivo, temporario)
        os.replace(temporario, pasta / arquivo.name)


def conferir_pasta(pasta: Path, uf: str, cod: int, codigos: set[str], *, quando: str | None = None) -> dict:
    """Confere selecionadas; preserva checkpoint de desenho novo até terminar o recálculo."""
    pasta = Path(pasta).resolve()
    quando = quando or dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    checkpoint = pasta / ".car_atual" / str(cod)
    checkpoint.mkdir(parents=True, exist_ok=True)
    pendente = checkpoint / "pendente.json"
    with trava(checkpoint / "conferencia"):
        if pendente.exists():
            salvo = json.loads(pendente.read_text())
            recalcular(pasta, uf, cod, checkpoint / "car.parquet", checkpoint / "trabalho")
            _marcar(pasta, cod, salvo)
            pendente.unlink()
        tabela = pd.read_csv(pasta / f"imoveis_{cod}.csv", dtype={"cod_imovel": str}, low_memory=False)
        geo = gpd.read_parquet(pasta / f"geo_{cod}.parquet").to_crs(4674)
        base = gpd.GeoDataFrame(
            tabela.merge(geo[["cod_imovel", "geometry"]], on="cod_imovel", validate="one_to_one"), crs=4674
        )
        atual = consultar(uf, codigos)
        nova, marcas, mudou = comparar(base, atual, codigos, quando)
        if mudou:
            entrada = nova[[c for c in (*COLUNAS, *MARCAS, "car_base", "car_fonte") if c in nova]]
            tmp = checkpoint / "car.tmp"
            entrada.to_parquet(tmp)
            os.replace(tmp, checkpoint / "car.parquet")
            provisoria = pendente.with_suffix(".tmp")
            provisoria.write_text(json.dumps(marcas))
            os.replace(provisoria, pendente)
            recalcular(pasta, uf, cod, checkpoint / "car.parquet", checkpoint / "trabalho")
        _marcar(pasta, cod, marcas)
        pendente.unlink(missing_ok=True)
        return marcas


def _marcar(pasta: Path, cod: int, marcas: dict) -> None:
    arquivo = pasta / f"imoveis_{cod}.csv"
    t = pd.read_csv(arquivo, dtype={"cod_imovel": str}, low_memory=False)
    for campo in MARCAS:
        if campo not in t:
            t[campo] = None
        for imovel, marca in marcas.items():
            t.loc[t.cod_imovel.eq(imovel), campo] = marca[campo]
    _csv(t, arquivo)


def conferir_banco(engine, selecionadas: pd.DataFrame) -> None:
    """Usa os mesmos arquivos privados da carga; atualiza oferta e desenho juntos."""
    from raiz.carga import carregar_municipio, depois_da_carga
    from raiz.executor.armazem import do_config
    from raiz.executor.sincronizar import espelho_local, sincronizar
    from raiz.funil.rodar import dir_trabalho

    for (uf, cod), g in selecionadas.groupby(["uf", "cod_ibge"]):
        cod = int(cod)
        destinos = [espelho_local(), dir_trabalho()]
        pasta = next(
            (
                d / "saida" / uf
                for d in destinos
                if (d / "saida" / uf / f"geo_{cod}.parquet").exists()
                and (d / "saida" / uf / f"imoveis_{cod}.csv").exists()
            ),
            None,
        )
        if pasta is None:
            destino = espelho_local()
            sincronizar(do_config(), destino, [uf], re.compile(rf"_{cod}\.(?:csv|parquet)$"))
            pasta = destino / "saida" / uf
        conferir_pasta(pasta, uf, cod, set(g.cod_imovel))
        with engine.begin() as con:
            carregar_municipio(con, pasta, cod, motor_confirmado=True)
        depois_da_carga(engine, cod, estrito=True)


def _rodar_recalculo(uf: str, cod: int, entrada: Path) -> None:
    from raiz.funil import rodar as RD
    from raiz.funil.ponte import arquivo, espelho_padrao

    esp = entrada.parent / "espelho"
    destino = arquivo(esp, "car", uf, cod)
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(entrada, destino)
    sigef = esp / "sigef"
    original = espelho_padrao() / "sigef"
    if original.exists() and not sigef.exists():
        sigef.symlink_to(original.resolve(), target_is_directory=True)
    op = RD.Opcoes(
        uf, tarefas=tuple(t for t in RD.TAREFAS if t != "carga"), refazer=True, espelho=str(esp), banco=False
    )
    RD.preparar_motor()
    RD.preparar_estado(op)
    resultado = RD.rodar_municipio(cod, op)
    if set(resultado) != set(op.tarefas) or any(s != "sucesso" for s in resultado.values()):
        raise ConferenciaPendente("Recálculo incompleto")


if __name__ == "__main__":  # apenas o trabalhador isolado, chamado com caminhos controlados
    _rodar_recalculo(sys.argv[1], int(sys.argv[2]), Path(sys.argv[3]))
