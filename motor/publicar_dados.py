"""Prepara as saídas do motor para o Release `dados` do GitHub, de onde o front baixa sozinho.

Os dados grandes nunca ficam no git: este script monta os pacotes em uma pasta de entrada, o workflow
.github/workflows/publicar-dados.yml sobe os pacotes como arquivos do Release `dados` e a pasta de entrada
sai do branch logo depois (os pacotes ficam só no Release).

Para cada estado monta:
  raiz_<UF>.tar.gz      todos os CSV do estado (imoveis_, direto_, filtros_, extras_, extras_direto_,
                        mapbiomas_, certidoes_ e resumo_<UF>.csv), dentro da pasta <UF>/
  raiz_geo_<UF>.tar.gz  os polígonos dos imóveis (geo_<cod>.parquet, GeoParquet), dentro da pasta <UF>/
e um estados.json com o que existe (municípios feitos, total do IBGE, se está completo, tamanho e versão).
Só monta de novo o estado que mudou (a versão é o sha256 do conteúdo, comparada com o estados.json publicado).
O GitHub não aceita arquivo acima de 100 MB no branch, então pacotes grandes vão em partes (.part00, .part01...)
que o workflow junta antes de subir.

Uso:
  python motor/publicar_dados.py <pasta_da_saida_do_motor> <pasta_de_entrada> [UF ...]

Antes de montar, confere que nenhum CSV tem coluna de nome, CPF, CNPJ ou contato.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import urllib.request
from pathlib import Path

REPO = os.environ.get("RAIZ_REPO", "bernardoemmel/raiz")
TAG = os.environ.get("RAIZ_TAG_DADOS", "dados")
BASE = f"https://github.com/{REPO}/releases/download/{TAG}"
PARTE = 90 * 1024 * 1024

# municípios por UF (IBGE 2022)
TOTAL_IBGE = {
    "AC": 22, "AL": 102, "AP": 16, "AM": 62, "BA": 417, "CE": 184, "DF": 1, "ES": 78, "GO": 246,
    "MA": 217, "MT": 142, "MS": 79, "MG": 853, "PA": 144, "PB": 223, "PR": 399, "PE": 185, "PI": 224,
    "RJ": 92, "RN": 167, "RS": 497, "RO": 52, "RR": 15, "SC": 295, "SP": 645, "SE": 75, "TO": 139,
}
TABELAS = ["imoveis", "direto", "filtros", "extras", "extras_direto", "mapbiomas", "certidoes"]
PROIBIDAS = re.compile(r"(^|_)(cpf|cnpj|nome|proprietario|titular|email|telefone)($|_)", re.I)


def manifesto_publicado() -> dict:
    try:
        with urllib.request.urlopen(f"{BASE}/estados.json", timeout=60) as r:
            return json.load(r)
    except Exception:
        return {}


def empacotar(uf: str, arquivos: list[Path]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tar:
        for f in sorted(arquivos):
            info = tar.gettarinfo(str(f), arcname=f"{uf}/{f.name}")
            info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "", ""
            with open(f, "rb") as fh:
                tar.addfile(info, fh)
    return buf.getvalue()


def gravar(destino: Path, nome: str, conteudo: bytes) -> None:
    if len(conteudo) <= PARTE:
        (destino / nome).write_bytes(conteudo)
        return
    for i in range(0, len(conteudo), PARTE):
        (destino / f"{nome}.part{i // PARTE:02d}").write_bytes(conteudo[i:i + PARTE])


def versao(arquivos: list[Path]) -> str:
    h = hashlib.sha256()
    for f in sorted(arquivos):
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def conferir_privacidade(csvs: list[Path]) -> None:
    for f in csvs:
        with open(f, encoding="utf-8", errors="replace") as fh:
            cab = fh.readline().strip().split(",")
        ruins = [c for c in cab if PROIBIDAS.search(c)]
        if ruins:
            raise SystemExit(f"{f.name} tem coluna proibida {ruins}: não publico.")


def estado_info(pasta: Path, uf: str) -> dict:
    def cods(t: str) -> set[str]:
        return {m.group(1) for f in pasta.glob(f"{t}_*.csv") if (m := re.fullmatch(rf"{t}_(\d{{7}})\.csv", f.name))}
    feitos = cods("imoveis")
    total = TOTAL_IBGE.get(uf)
    return {
        "municipios": len(feitos),
        "total_ibge": total,
        "completo": total is not None and len(feitos) >= total,
        "tabelas": {t: len(cods(t)) for t in TABELAS},
    }


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    saida, destino = Path(sys.argv[1]), Path(sys.argv[2])
    destino.mkdir(parents=True, exist_ok=True)
    ufs = sys.argv[3:] or sorted(p.name for p in saida.iterdir() if p.is_dir() and p.name in TOTAL_IBGE)
    estados = manifesto_publicado().get("estados", {})
    agora = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    mudou = False

    for uf in ufs:
        pasta = saida / uf
        csvs = [f for f in pasta.glob("*.csv") if f.stat().st_size > 0]
        if not csvs:
            continue
        conferir_privacidade(csvs)
        antigo = estados.get(uf, {})
        info = estado_info(pasta, uf)
        v = versao(csvs)
        if antigo.get("versao") != v:
            pacote = empacotar(uf, csvs)
            gravar(destino, f"raiz_{uf}.tar.gz", pacote)
            info.update(tamanho=len(pacote), atualizado_em=agora)
            mudou = True
            print(f"{uf}: raiz_{uf}.tar.gz {len(pacote) / 1e6:.1f} MB ({info['municipios']}/{info['total_ibge']} municípios)")
        else:
            info.update(tamanho=antigo.get("tamanho"), atualizado_em=antigo.get("atualizado_em"))
            print(f"{uf}: sem mudança")
        info.update(versao=v, url=f"{BASE}/raiz_{uf}.tar.gz")
        geos = list(pasta.glob("geo_*.parquet"))
        if geos:
            vg = versao(geos)
            if antigo.get("geo", {}).get("versao") != vg:
                pg = empacotar(uf, geos)
                gravar(destino, f"raiz_geo_{uf}.tar.gz", pg)
                info["geo"] = {"versao": vg, "tamanho": len(pg), "url": f"{BASE}/raiz_geo_{uf}.tar.gz",
                               "municipios": len(geos)}
                mudou = True
                print(f"{uf}: raiz_geo_{uf}.tar.gz {len(pg) / 1e6:.1f} MB")
            else:
                info["geo"] = antigo["geo"]
        estados[uf] = info

    if mudou:
        manifesto = {"gerado_em": agora, "repo": REPO, "tag": TAG, "estados": dict(sorted(estados.items()))}
        (destino / "estados.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=1), encoding="utf-8")
        print("estados.json pronto")
    else:
        print("nada mudou")


if __name__ == "__main__":
    main()
