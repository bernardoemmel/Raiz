"""Confere o mapeamento dos municípios e diz o que ainda precisa rodar.

Sem rede, compara a lista do motor (`raiz/executor/municipios.csv`) com os códigos do front
(`front/compartilhado/ibge-municipios.ts`). Com `--baixar`, baixa a Divisão Territorial
Brasileira mais recente do IBGE e aponta código ou nome que divergir.

A troca da malha desenhada no mapa não cabe aqui: `front/scripts/geo.py` aplica a Malha
Municipal do IBGE a cada UF publicada quando o site é montado (`--dados`). A primeira vez
baixa o ZIP de cada UF e leva cerca de 15 a 40 minutos dentro do workflow Publicar o site,
que já tem 180 minutos. Não reprocessa o funil e não chama API paga.

Uso:
  python3 scripts/conferir_municipios.py
  python3 scripts/conferir_municipios.py --baixar
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

RAIZ = Path(__file__).resolve().parents[1]
CSV = RAIZ / "raiz/executor/municipios.csv"
FRONT = RAIZ / "front/compartilhado/ibge-municipios.ts"
DTB = "https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/divisao_territorial/"


def codigos_do_front() -> set[str]:
    texto = FRONT.read_text(encoding="utf-8")
    prefixo = dict(re.findall(r'^  ([A-Z]{2}): "(\d{2})",$', texto, re.M))
    codigos = set()
    for uf, corpo in re.findall(r'^  ([A-Z]{2}): "([0-9 ]+)",$', texto, re.M):
        partes = corpo.split()
        # A segunda tabela do arquivo é o código da UF (dois dígitos), não a lista de municípios.
        if uf not in prefixo or not partes or all(len(parte) == 2 for parte in partes):
            continue
        codigos.update(prefixo[uf] + parte for parte in partes)
    return codigos


def linhas_csv() -> list[dict[str, str]]:
    with CSV.open(encoding="utf-8", newline="") as arquivo:
        return list(csv.DictReader(arquivo))


def nomes_da_dtb(conteudo: bytes) -> dict[str, str]:
    pacote = zipfile.ZipFile(io.BytesIO(conteudo))
    planilha = next(nome for nome in pacote.namelist() if re.search(r"MUNICIPIOS\.ods$", nome))
    ods = zipfile.ZipFile(io.BytesIO(pacote.read(planilha)))
    tabela = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
    nomes: dict[str, str] = {}
    for linha in ET.fromstring(ods.read("content.xml")).iter(tabela + "table-row"):
        celulas: list[str] = []
        for celula in linha.findall(tabela + "table-cell"):
            repetida = min(int(celula.get(tabela + "number-columns-repeated", "1")), 20)
            celulas += ["".join(celula.itertext())] * repetida
        codigo = next((c for c in celulas if re.fullmatch(r"\d{7}", c or "")), None)
        if not codigo:
            continue
        indice = celulas.index(codigo)
        nomes[codigo] = celulas[indice + 1].strip() if indice + 1 < len(celulas) else ""
    return nomes


def baixar_dtb() -> tuple[str, bytes]:
    import urllib.request

    indice = urllib.request.urlopen(DTB, timeout=60).read().decode("latin-1", "replace")
    anos = sorted(set(re.findall(r'href="(\d{4})/"', indice)))
    for ano in reversed(anos):
        pagina = urllib.request.urlopen(DTB + ano + "/", timeout=60).read().decode("latin-1", "replace")
        nome = next(iter(re.findall(r'href="(DTB_\d{4}\.zip)"', pagina)), None)
        if nome:
            return nome, urllib.request.urlopen(DTB + ano + "/" + nome, timeout=120).read()
    raise RuntimeError("nenhuma DTB na pasta do IBGE")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baixar", action="store_true", help="baixa a DTB oficial e compara código e nome")
    args = parser.parse_args()
    linhas = linhas_csv()
    do_csv = {r["codigo_ibge"] for r in linhas}
    do_front = codigos_do_front()
    print(f"lista do motor: {len(do_csv)} códigos")
    print(f"lista do front: {len(do_front)} códigos")
    so_csv, so_front = sorted(do_csv - do_front), sorted(do_front - do_csv)
    if so_csv or so_front:
        print(f"só no motor: {so_csv[:20]}")
        print(f"só no front: {so_front[:20]}")
        return 1
    print("motor e front têm os mesmos códigos")
    if not args.baixar:
        print(
            "Geometria: o próximo build do site (front/scripts/geo.py --dados <pasta do Release>) "
            "troca a malha de cada UF publicada pela Malha Municipal do IBGE. "
            "Primeira vez: cerca de 15 a 40 minutos, dentro do workflow Publicar o site. "
            "Não reprocessa o funil. Para conferir os nomes oficiais: python3 scripts/conferir_municipios.py --baixar"
        )
        return 0
    nome, conteudo = baixar_dtb()
    oficial = nomes_da_dtb(conteudo)
    print(f"{nome}: {len(oficial)} municípios")
    faltam, sobram = sorted(set(oficial) - do_csv), sorted(do_csv - set(oficial))
    if faltam or sobram:
        print(f"códigos só na DTB: {faltam}")
        print(f"códigos só na lista local: {sobram}")
        print("Atualize raiz/executor/municipios.csv e regenere a lista do front antes de reprocessar.")
        return 1
    divergentes = [
        (r["codigo_ibge"], r["nome"], oficial[r["codigo_ibge"]])
        for r in linhas
        if oficial.get(r["codigo_ibge"]) != r["nome"]
    ]
    if divergentes:
        print(f"{len(divergentes)} nomes divergem da DTB. Os primeiros:")
        for codigo, local, certo in divergentes[:15]:
            print(f"  {codigo}: {local!r} -> {certo!r}")
        return 1
    print("códigos e nomes batem com a DTB oficial")
    print(
        "Os resumos já publicados no Release dados só trocam o nome quando o estado for reprocessado "
        "(workflow Processar estados, várias horas nos estados grandes). Não é necessário para a demo."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
