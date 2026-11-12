"""Recálculo do Pará em fatias no Actions, com entradas congeladas e publicação verificável.

Não roda o motor no computador do agente. O workflow chama preparar, recalcular e consolidar;
cada cálculo usa o mesmo commit, pacotes de entrada e premissas. A publicação tem nomes por rodada e não
sobrescreve os pacotes do executor nacional que podem estar sendo atualizados em paralelo.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FATIAS = 12
PRODUTOS = ("terra", "rebanho", "desenvolvedor")


def sha256(arquivo: Path) -> str:
    with arquivo.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def gravar_json(arquivo: Path, dados: dict) -> None:
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def municipios_pa() -> list[int]:
    with (REPO / "raiz/executor/municipios.csv").open(encoding="utf-8") as f:
        cods = sorted(int(r["codigo_ibge"]) for r in csv.DictReader(f) if r["codigo_uf"] == "15")
    if len(cods) != 144:
        raise ValueError("A lista do IBGE precisa conter exatamente os 144 municípios do Pará")
    return cods


def conferir_municipios(pasta: Path, prefixo: str, esperados: list[int]) -> None:
    presentes = {int(f.stem.rsplit("_", 1)[1]) for f in pasta.glob(f"{prefixo}_*.csv")}
    if presentes != set(esperados):
        raise ValueError(f"{prefixo}: cobertura incompleta ou inesperada; faltam {sorted(set(esperados) - presentes)}")


def extrair(pacote: Path, destino: Path) -> None:
    """Só arquivos regulares diretamente em PA; nenhum link ou caminho fora da pasta."""
    with tarfile.open(pacote) as tar:
        for item in tar.getmembers():
            partes = Path(item.name).parts
            if item.isdir() and partes == ("PA",):
                continue
            if not item.isfile() or len(partes) != 2 or partes[0] != "PA" or partes[1] in (".", ".."):
                raise ValueError("Pacote de entrada tem caminho ou tipo de arquivo não permitido")
        tar.extractall(destino, filter="data")


def exigir_actions() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true" or not os.environ.get("GITHUB_SHA"):
        raise SystemExit("Este recálculo só pode rodar no GitHub Actions; use Recalcular lote do Pará")


def conferir_premissas() -> None:
    from raiz import restauracao as R

    r = R.regra()
    if float(r["nao_permanencia"]["piso"]) < 0.20:
        raise ValueError("Recálculo bloqueado: piso de não permanência menor que 20%")


def baixar_asset(repo: str, asset: dict, destino: Path) -> dict:
    with destino.open("wb") as f:
        subprocess.run(
            ["gh", "api", f"repos/{repo}/releases/assets/{asset['id']}", "-H", "Accept: application/octet-stream"],
            stdout=f,
            check=True,
        )
    sha = sha256(destino)
    if asset.get("digest") and asset["digest"] != f"sha256:{sha}":
        raise ValueError("O hash do pacote baixado não confere com o Release")
    return {"arquivo": asset["name"], "asset_id": asset["id"], "sha256": sha, "bytes": destino.stat().st_size}


def preparar(pasta: Path) -> None:
    conferir_premissas()
    repo = os.environ["GITHUB_REPOSITORY"]
    rel = json.loads(subprocess.check_output(["gh", "api", f"repos/{repo}/releases/tags/dados"]))
    paginas = json.loads(
        subprocess.check_output(
            ["gh", "api", f"repos/{repo}/releases/{rel['id']}/assets?per_page=100", "--paginate", "--slurp"]
        )
    )
    assets = {a["name"]: a for pagina in paginas for a in pagina}
    entradas = pasta / "entradas"
    entradas.mkdir(parents=True, exist_ok=True)
    fontes = []
    for nome in ("raiz_PA.tar.gz", "raiz_geo_PA.tar.gz"):
        pacote = pasta / nome
        fontes.append(baixar_asset(repo, assets[nome], pacote))
        extrair(pacote, entradas / "saida")
        pacote.unlink()
    cods = municipios_pa()
    for tipo in ("imoveis", "filtros", "mapbiomas", "direto"):
        conferir_municipios(entradas / "saida/PA", tipo, cods)
    geos = {int(f.stem.rsplit("_", 1)[1]) for f in (entradas / "saida/PA").glob("geo_*.parquet")}
    if geos != set(cods):
        raise ValueError("GeoParquet incompleto: não calcular com localização aproximada")
    # Usa as rotinas oficiais já mantidas pelo motor apenas para baixar as fontes.
    # Não recalcula funil, MapBiomas ou filtros, que já estão no pacote publicado.
    sys.path.insert(0, str(REPO / "motor"))
    anterior = Path.cwd()
    try:
        os.chdir(REPO / "motor")
        import raiz_filtros as F
        import raiz_mapbiomas as M

        cobertura = Path(M.exporta_uf("PA", espera=3600, temas=["cobertura"])["cobertura"]).resolve()
        cache = entradas / "cache"
        (cache / "mapbiomas/PA").mkdir(parents=True, exist_ok=True)
        shutil.copy2(cobertura, cache / "mapbiomas/PA" / cobertura.name)
        for tema in F.ARQ:
            arq = Path(F.baixar(tema)).resolve()
            shutil.copy2(arq, cache / arq.name)
    finally:
        os.chdir(anterior)
    for f in sorted((entradas / "cache").rglob("*")):
        if f.is_file():
            fontes.append({"arquivo": str(f.relative_to(entradas)), "sha256": sha256(f), "bytes": f.stat().st_size})
    from raiz import restauracao as R

    gravar_json(
        entradas / "fontes.json",
        {"commit": os.environ["GITHUB_SHA"], "fontes": fontes, "municipios": cods, "versao_restauracao": R.versao()},
    )
    print(f"Entradas congeladas: {len(cods)} municípios, commit {os.environ['GITHUB_SHA']}", flush=True)


def recalcular(pasta: Path, fatia: int) -> None:
    if not 0 <= fatia < FATIAS:
        raise ValueError("Fatia inválida")
    conferir_premissas()
    from raiz import rebanho, restauracao, terra

    entradas = pasta / "entradas"
    fontes = json.loads((entradas / "fontes.json").read_text())
    if fontes["commit"] != os.environ["GITHUB_SHA"] or fontes["versao_restauracao"] != restauracao.versao():
        raise ValueError("O código ou as premissas mudaram depois de congelar as entradas")
    saida, cache = entradas / "saida/PA", entradas / "cache"
    feitos = []
    destino = pasta / "fragmentos"
    (destino / "PA").mkdir(parents=True, exist_ok=True)
    (destino / "entradas_geograficas").mkdir(exist_ok=True)
    for cod in fontes["municipios"][fatia::FATIAS]:
        inicio = time.monotonic()
        terra.escrever_municipio(saida, cod, cache)
        rebanho.escrever_municipio(saida, cod)
        restauracao.escrever_municipio(saida, cod, cache, pasta / "cache_restauracao")
        for tipo in PRODUTOS:
            f = saida / f"{tipo}_{cod}.csv"
            shutil.copy2(f, destino / "PA" / f.name)
        # Essas medições leem rasters remotos durante o cálculo. Preserva as entradas
        # efetivamente usadas, inclusive campos ausentes, em vez de prometer snapshot bruto.
        entradas_geo = list((pasta / "cache_restauracao/entradas").glob(f"{cod}_*.json"))
        if len(entradas_geo) != 1:
            raise ValueError(f"{cod}: entradas geográficas de auditoria ausentes ou ambíguas")
        shutil.copy2(entradas_geo[0], destino / "entradas_geograficas" / f"{cod}.json")
        feitos.append(cod)
        print(f"PA/{cod}: pronto em {time.monotonic() - inicio:.0f} s ({len(feitos)}/12 da fatia)", flush=True)
    gravar_json(destino / f"fatia_{fatia}.json", {"municipios": feitos, "commit": fontes["commit"]})


def validar_resultados(saida: Path, esperados: list[int], versao: str) -> dict:
    """Recusa município ausente, mistura de versões, perda de fazendas e reserva abaixo do piso."""
    import pandas as pd

    from raiz.privacidade import colunas_pessoais

    faltas, fazendas = {}, 0
    for tipo in PRODUTOS:
        conferir_municipios(saida, tipo, esperados)
    for cod in esperados:
        base = pd.read_csv(saida / f"imoveis_{cod}.csv", usecols=["cod_imovel"], dtype=str)
        for tipo in PRODUTOS:
            df = pd.read_csv(saida / f"{tipo}_{cod}.csv", low_memory=False)
            if colunas_pessoais(df.columns):
                raise ValueError(f"{tipo}/{cod}: coluna pessoal na saída; publicação bloqueada")
            if df.cod_imovel.duplicated().any() or set(df.cod_imovel) != set(base.cod_imovel):
                raise ValueError(f"{tipo}/{cod}: perdeu ou duplicou fazendas")
            if tipo != "desenvolvedor":
                continue
            if set(df.restauracao_versao) != {versao}:
                raise ValueError(f"{cod}: mistura de versões da restauração")
            elegiveis = df[df.restauracao_area_ha > 0]
            if elegiveis.reserva_risco_pct.isna().any() or (elegiveis.reserva_risco_pct < 20 - 1e-6).any():
                raise ValueError(f"{cod}: reserva de não permanência abaixo de 20%")
            fazendas += len(df)
            faltas[str(cod)] = df.restauracao_faltou.fillna("").value_counts().to_dict()
    return {"fazendas": fazendas, "faltas_de_fontes_por_municipio": faltas}


def consolidar(pasta: Path) -> None:
    conferir_premissas()
    from raiz import lote as L
    from raiz import lote_relatorio as LR
    from raiz import restauracao as R
    from raiz.privacidade import colunas_pessoais

    entradas = pasta / "entradas"
    fontes = json.loads((entradas / "fontes.json").read_text())
    cods = municipios_pa()
    marcados = []
    for i in range(FATIAS):
        fatia = json.loads((pasta / "fragmentos" / f"fatia_{i}.json").read_text())
        if fatia["commit"] != os.environ["GITHUB_SHA"]:
            raise ValueError("Fatia calculada em outro commit")
        marcados.extend(fatia["municipios"])
    if sorted(marcados) != cods:
        raise ValueError("As fatias não cobrem exatamente os 144 municípios")
    saida = entradas / "saida/PA"
    for f in (pasta / "fragmentos/PA").glob("*.csv"):
        shutil.copy2(f, saida / f.name)
    verificado = validar_resultados(saida, cods, R.versao())
    dados = L.ler_pasta(saida, "PA")
    lote = L.montar(dados, 1_000_000)
    if lote["resumo"]["municipios"]["lidos"] != 144 or colunas_pessoais(lote["tabela"].columns):
        raise ValueError("Lote incompleto ou com coluna pessoal")
    destino = pasta / "publicacao"
    destino.mkdir(parents=True, exist_ok=True)
    LR.gravar_lote(lote, pasta / "lote", folhas=False)
    rodada = f"{os.environ['GITHUB_RUN_ID']}_{os.environ['GITHUB_RUN_ATTEMPT']}"
    pacote = destino / f"raiz_restauracao_PA_{rodada}.tar.gz"
    entradas_geo = pasta / "fragmentos/entradas_geograficas"
    if {int(f.stem) for f in entradas_geo.glob("*.json")} != set(cods):
        raise ValueError("As entradas geográficas de auditoria não cobrem os 144 municípios")
    with tarfile.open(pacote, "w:gz") as tar:
        for f in sorted((pasta / "fragmentos/PA").glob("*.csv")):
            tar.add(f, arcname=f"PA/{f.name}")
        for f in sorted((pasta / "lote").glob("*")):
            tar.add(f, arcname=f"PA/lote/{f.name}")
        for f in sorted(entradas_geo.glob("*.json")):
            tar.add(f, arcname=f"PA/entradas_geograficas/{f.name}")
    for f in (pasta / "lote").glob("*"):
        shutil.copy2(f, destino / f"{f.stem}_{rodada}{f.suffix}")
    manifesto = {
        **fontes,
        **verificado,
        "rodada": f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}",
        "piso_nao_permanencia": R.regra()["nao_permanencia"]["piso"],
        "municipios_calculados": len(cods),
        "produtos": list(PRODUTOS),
        "entradas_geograficas": {
            f.stem: {"arquivo_no_pacote": f"PA/entradas_geograficas/{f.name}", "sha256": sha256(f)}
            for f in sorted(entradas_geo.glob("*.json"))
        },
        "limites": [
            "Lote indicativo: não substitui consulta, contrato, certidão nem aprovação humana.",
            "SIGEF e CNFP adicionais não foram baixados; "
            "classificação usa as evidências do pacote e camadas nacionais.",
            "Acesso a estrada/cidade depende da ficha publicada; ausência permanece indicada no cálculo.",
            "Declividade, chuva, solo e linha de base usam rasters remotos durante o cálculo; "
            "as medições por município ficam no pacote, sem afirmar snapshot dos rasters brutos.",
            "Fontes geográficas que falharam são explicitadas por município; não há confirmação de completude delas.",
        ],
        "arquivos": {f.name: {"sha256": sha256(f), "bytes": f.stat().st_size} for f in sorted(destino.iterdir())},
    }
    gravar_json(destino / f"manifesto_lote_PA_{rodada}.json", manifesto)
    resumo = lote["resumo"]
    texto = (
        f"## Lote do Pará — 144 municípios\n\nCommit: `{fontes['commit']}`. "
        f"Premissas: `{R.versao()}`. Reserva mínima: 20%.\n\n"
        f"{resumo['titulares']} titulares e {resumo['reservas']} reservas; {resumo['ha_lote']:,.1f} ha; "
        f"{resumo['creditos_lote']:,.0f} créditos. Fecha com reserva: {resumo['fecha_com_reserva']}.\n\n"
        "Resultados e hashes no Release `dados`, identificados pelo número desta rodada.\n"
    )
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as f:
            f.write(texto)
    print(texto)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("acao", choices=["preparar", "recalcular", "consolidar"])
    p.add_argument("--pasta", type=Path, default=REPO / "dados/armazem_local/recalculo-pa")
    p.add_argument("--fatia", type=int)
    args = p.parse_args()
    exigir_actions()
    pasta = args.pasta.resolve()
    if args.acao == "recalcular":
        if args.fatia is None:
            p.error("recalcular exige --fatia")
        recalcular(pasta, args.fatia)
    elif args.acao == "preparar":
        preparar(pasta)
    else:
        consolidar(pasta)


if __name__ == "__main__":
    main()
