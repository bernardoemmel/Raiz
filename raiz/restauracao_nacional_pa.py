"""Importa a rodada PA vigente sem recalcular nem reetiquetar o histórico R11."""

import hashlib
import json
import re
import shutil
from pathlib import Path

import pandas as pd

from raiz import restauracao as R
from raiz import restauracao_nacional_fontes as F
from raiz import restauracao_rodada as P
from raiz.executor.transferencia_privada import empacotar, extrair


def referencia(arm, ativos: dict) -> dict | None:
    nome = f"lote_PA_{R.cenario()['cenario']}.json"
    if nome not in ativos:
        return None
    arm._exigir_privado()
    bruto = arm._baixar_asset(nome, fresco=True)
    if bruto is None:
        raise ValueError("ponteiro PA desapareceu durante captura")
    dado = json.loads(bruto)
    if dado.get("modelo_versao") != R.versao() or dado.get("cenario") != R.cenario()["cenario"]:
        return None  # fonte anterior permanece anterior; não recebe etiqueta nova
    if dado.get("uf") != "PA" or dado.get("municipios") != 144 or dado.get("imoveis_calculados") != 345870:
        raise ValueError("rodada PA não contém a cobertura histórica completa")
    padrao = rf"lote_PA_{re.escape(R.cenario()['cenario'])}_\d+_\d+_previsoes\.tar\.gz"
    pacotes = [n for n in dado["arquivos"] if re.fullmatch(padrao, n)]
    if len(pacotes) != 1:
        raise ValueError("rodada PA sem pacote único de previsões")
    return {"manifesto": dado, "manifesto_sha256": hashlib.sha256(bruto).hexdigest(), "pacote": pacotes[0]}


def importar(arm, referencia: dict, destino: Path) -> tuple[Path, dict]:
    destino.mkdir(mode=0o700, parents=True, exist_ok=True)
    origem = {
        "nome": "retomada_PA_43285608189_entradas_42a37d06c245092d.tar.gz",
        "sha256": "42a37d06c245092dbab4f464ab9915a2553af485037a8ba82cce42e67ce4fbe0",
        "bytes": 190550833,
    }
    F.baixar(arm, origem, destino / "entradas.tar.gz")
    extrair(destino / "entradas.tar.gz", destino / "entradas")
    manifesto = referencia["manifesto"]
    for nome in P.PACOTES:
        arquivo = destino / "entradas" / nome
        if F.C.sha256(arquivo) != manifesto["fontes"][nome]["sha256"]:
            raise ValueError("rodada PA e entrada histórica usam fontes diferentes")
        P.extrair(arquivo, destino / "fonte")
    nome = referencia["pacote"]
    F.baixar(arm, {"nome": nome, **manifesto["arquivos"][nome]}, destino / "previsoes.tar.gz")
    extrair(destino / "previsoes.tar.gz", destino / "produto")
    fonte = destino / "fonte/PA"
    devs = list((destino / "produto/previsoes").glob("desenvolvedor_*.csv"))
    if len(devs) != 144:
        raise ValueError("rodada PA sem previsões dos 144 municípios")
    total = 0
    for arquivo in devs:
        t = pd.read_csv(arquivo, usecols=["cod_imovel", "restauracao_versao", "restauracao_cenario"])
        if (
            not t.cod_imovel.is_unique
            or not t.restauracao_versao.eq(R.versao()).all()
            or not t.restauracao_cenario.eq(manifesto["cenario"]).all()
        ):
            raise ValueError("previsões PA divergentes da rodada")
        total += len(t)
        shutil.copy2(arquivo, fonte / arquivo.name)
    if total != manifesto["imoveis_calculados"]:
        raise ValueError("rodada PA perdeu imóveis")
    for arquivo in (destino / "produto/previsoes").glob("terra_*.csv"):
        shutil.copy2(arquivo, fonte / arquivo.name)
    P.conferir_cobertura(fonte)
    pacote = destino / "fonte_completa.tar.gz"
    empacotar(fonte, pacote, prefixo="PA")
    ref = F.publicar(arm, pacote, "lote_fonte_PA_rodada", ".tar.gz")
    return fonte, {
        "tipo": "rodada_PA144_mesmas_entradas_historicas",
        "fontes": {"completa": {"copia_imutavel": ref}},
        "manifesto_origem_sha256": referencia["manifesto_sha256"],
        "modelo_versao": R.versao(),
    }
