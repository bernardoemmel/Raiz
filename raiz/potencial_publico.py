"""Potencial conhecido em células H3, sem atribuir hectares pagos a um CAR público.

A localização é uma alocação estatística pelo ponto interior do CAR, não o desenho
medido da restauração. Só soma áreas positivas conhecidas de imóveis sem nenhuma
sobreposição detectada; exige cinco contribuintes por célula. O cadastro conserva
todos os imóveis. Dados privados nunca são gravados no diretório do site.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import re
import tarfile
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import h3
import numpy as np
import shapely

RESOLUCAO = 5
DOMINIO_HA = [0, 100, 1000, 10000, 50000]
FONTE = "Motor da Raíz: carbono_ha, pasto perto de floresta além da reserva legal."
AVISO = (
    "Potencial conhecido, cobertura parcial. Soma somente imóveis com área positiva publicada, "
    "sem sobreposição detectada entre CARs e com pelo menos cinco contribuintes na célula. "
    "Áreas ausentes ou sobrepostas não entram na soma; célula desconhecida não significa zero. "
    "Cada imóvel é alocado uma vez pelo ponto interior do CAR. O hexágono não é o desenho da restauração "
    "e pode atravessar divisas estaduais. Não é área disponível para venda nem prova de elegibilidade."
)
_CAR = re.compile(r"^[A-Z]{2}-[0-9]{7}-[0-9A-F]{32}$")


def numero(v) -> float | None:
    try:
        n = float(v)
    except (ValueError, TypeError):
        return None
    return n if math.isfinite(n) and n >= 0 else None


class Entradas:
    """Somente identidade técnica, geometria e a medida necessária; nunca nomes/contatos."""

    def __init__(self):
        self.areas: dict[str, float | None] = {}
        self.geometrias: dict[str, object] = {}
        self.ufs_por_car: dict[str, set[str]] = defaultdict(set)
        self.geometrias_esperadas: dict[str, str] = {}
        self.geometrias_lidas: dict[str, str] = {}
        self.ufs: set[str] = set()
        self.datas: list[str] = []

    def csv(self, dados: bytes, uf: str) -> None:
        leitor = csv.DictReader(io.StringIO(dados.decode("utf-8-sig")))
        if "cod_imovel" not in (leitor.fieldnames or []):
            raise ValueError("Fonte do potencial sem a identidade técnica necessária.")
        self.ufs.add(uf)
        for linha in leitor:
            car = linha["cod_imovel"].strip().upper()
            if not _CAR.fullmatch(car):
                raise ValueError("Identidade técnica inválida no potencial privado.")
            # Há registros reais cujo prefixo do CAR difere da UF do pacote municipal.
            # Não inventar outra identidade nem duplicar sua contribuição ao indexar a fronteira.
            self.ufs_por_car[car].add(uf)
            # Novas coletas podem ainda não ter a medida: conservamos o cadastro como desconhecido.
            valor = numero(linha.get("carbono_ha"))
            if car in self.areas and self.areas[car] != valor:
                valor = None  # duplicidade contraditória não vira soma nem escolha arbitrária
            self.areas[car] = valor

    def parquet(self, arquivo) -> None:
        import geopandas as gpd

        geo = gpd.read_parquet(arquivo, columns=["cod_imovel", "geometry"])
        if geo.crs is None:
            raise ValueError("Geometria do potencial sem sistema de referência.")
        geo = geo.to_crs(4326)
        for car, bruto in zip(geo.cod_imovel, geo.geometry, strict=True):
            if not isinstance(car, str) or not _CAR.fullmatch(car):
                raise ValueError("Identidade técnica inválida na geometria privada.")
            if bruto is None or bruto.is_empty:
                continue
            geom = shapely.make_valid(bruto)
            if geom.geom_type not in ("Polygon", "MultiPolygon") or geom.is_empty:
                continue
            anterior = self.geometrias.get(car)
            if anterior is not None and not anterior.equals(geom):
                self.areas[car] = None
                geom = shapely.union_all([anterior, geom])
            self.geometrias[car] = geom

    def pacote(self, dados: bytes, uf: str, *, geometria: bool) -> None:
        with tarfile.open(fileobj=io.BytesIO(dados), mode="r:gz") as tar:
            for membro in tar:
                p = Path(membro.name)
                if p.is_absolute() or ".." in p.parts or not (membro.isdir() or membro.isfile()):
                    raise ValueError("Caminho inválido no pacote privado do potencial.")
                if not membro.isfile():
                    continue
                if geometria and re.fullmatch(r"geo_[0-9]{7}\.parquet", p.name):
                    with tar.extractfile(membro) as f:
                        bruto = f.read()
                        self.geometrias_lidas[p.name] = hashlib.sha256(bruto).hexdigest()
                        self.parquet(io.BytesIO(bruto))
                elif not geometria and re.fullmatch(r"imoveis_[0-9]{7}\.csv", p.name):
                    with tar.extractfile(membro) as f:
                        self.csv(f.read(), uf)
                elif not geometria and p.name == "_versoes.json":
                    with tar.extractfile(membro) as f:
                        versoes = json.load(f)
                    self.geometrias_esperadas = {
                        nome: valor.get("sha256")
                        for nome, valor in versoes.items()
                        if re.fullmatch(r"geo_[0-9]{7}\.parquet", nome)
                    }

    def conferir_par(self) -> None:
        # O publicador sobe CSV e GeoParquet em sequência; IDs estáveis sozinhos não garantem o mesmo retrato.
        if not self.geometrias_esperadas or self.geometrias_esperadas != self.geometrias_lidas:
            raise RuntimeError("A geometria não corresponde à proveniência do pacote de medidas; aguardar publicação.")


def ler_local(pasta: Path) -> Entradas:
    e = Entradas()
    for uf in sorted(p for p in pasta.iterdir() if p.is_dir() and re.fullmatch(r"[A-Z]{2}", p.name)):
        for f in sorted(uf.glob("imoveis_???????.csv")):
            e.csv(f.read_bytes(), uf.name)
        for f in sorted(uf.glob("geo_???????.parquet")):
            e.parquet(f)
    manifesto = pasta / "estados.json"
    if manifesto.exists():
        data = json.loads(manifesto.read_text()).get("gerado_em")
        if data:
            e.datas.append(data)
    return e


def _incorporar(destino: Entradas, origem: Entradas) -> None:
    destino.ufs.update(origem.ufs)
    destino.datas.extend(origem.datas)
    for car, ufs in origem.ufs_por_car.items():
        destino.ufs_por_car[car].update(ufs)
    for car, area in origem.areas.items():
        destino.areas[car] = None if car in destino.areas and destino.areas[car] != area else area
    for car, geom in origem.geometrias.items():
        anterior = destino.geometrias.get(car)
        if anterior is not None and not anterior.equals(geom):
            destino.areas[car] = None
            geom = shapely.union_all([anterior, geom])
        destino.geometrias[car] = geom


def ler_privado(arm) -> Entradas:
    """Congela o par de assets por UF; troca concorrente refaz somente aquela UF.

    Nunca incorpora metade do par nem reutiliza os bytes de uma tentativa falha.
    A listagem final precisa conservar os mesmos IDs/digests lidos na inicial.
    """

    def listar():
        return {a["name"]: a for a in arm._assets(arm._exigir_privado())}

    ufs = sorted(m[1] for nome in listar() if (m := re.fullmatch(r"raiz_([A-Z]{2})\.tar\.gz", nome)))
    e = Entradas()
    for uf in ufs:
        nomes = [f"raiz_{uf}.tar.gz", f"raiz_geo_{uf}.tar.gz"]
        for tentativa in range(5):
            try:
                por_nome = listar()
                if any(n not in por_nome for n in nomes):
                    break  # UF sem desenho: cobertura indisponível, sem ponto municipal inventado.
                parte = Entradas()
                for i, nome in enumerate(nomes):
                    a = por_nome[nome]
                    digest = a.get("digest")
                    if not digest:
                        raise RuntimeError("O pacote privado ainda não recebeu o digest após o upload.")
                    dados = arm._baixar_ativo(a)
                    if len(dados) != a.get("size"):
                        raise ValueError("Tamanho divergente no pacote privado do potencial.")
                    if digest != "sha256:" + hashlib.sha256(dados).hexdigest():
                        raise ValueError("SHA-256 divergente no pacote privado do potencial.")
                    parte.pacote(dados, uf, geometria=i == 1)
                    if a.get("updated_at"):
                        parte.datas.append(a["updated_at"])
                parte.conferir_par()
                depois = listar()
                if any(
                    (por_nome[n]["id"], por_nome[n].get("digest"))
                    != (depois.get(n, {}).get("id"), depois.get(n, {}).get("digest"))
                    for n in nomes
                ):
                    raise RuntimeError("Publicação concorrente da UF durante a leitura do potencial.")
                _incorporar(e, parte)
                print(f"Potencial: fonte privada de {uf} lida; nenhum dado individual será publicado.", flush=True)
                break
            except RuntimeError:
                if tentativa == 4:
                    raise RuntimeError(f"Não foi possível obter um par estável de pacotes privados de {uf}.") from None
                print(
                    f"Potencial: repetindo leitura de {uf} após atualização concorrente ou falha transitória.",
                    flush=True,
                )
                time.sleep(min(2**tentativa, 8))
    return e


def detectar_sobreposicoes(geometrias: list) -> np.ndarray:
    """Interseção das áreas internas, sem confundir divisa encostada ou bbox com sobreposição."""
    gs = np.asarray(geometrias, dtype=object)
    resultado = np.zeros(len(gs), dtype=bool)
    arvore = shapely.STRtree(gs)
    for inicio in range(0, len(gs), 3000):
        a, b = arvore.query(gs[inicio : inicio + 3000], predicate="intersects")
        a = a + inicio
        unico = a < b
        a, b = a[unico], b[unico]
        if len(a):
            interior = shapely.relate_pattern(gs[a], gs[b], "2********")
            resultado[a[interior]], resultado[b[interior]] = True, True
    return resultado


def agregar(entrada: Entradas) -> tuple[dict, dict[str, dict], set[str], dict]:
    """Uma contribuição por CAR/célula; auditoria de massa permanece somente no processo privado."""
    codigos = sorted(entrada.geometrias)
    gs = [entrada.geometrias[c] for c in codigos]
    sobrepostos = detectar_sobreposicoes(gs)
    grupos = defaultdict(list)
    for i, g in enumerate(gs):
        p = g.representative_point()
        if not -90 <= p.y <= 90 or not -180 <= p.x <= 180:
            raise ValueError("Coordenadas inválidas para a célula estatística.")
        grupos[h3.latlng_to_cell(p.y, p.x, RESOLUCAO)].append(i)
    contagens = {
        "fazendas_com_geometria": len(gs),
        "incluidas": 0,
        "sem_medida": 0,
        "com_sobreposicao": int(sobrepostos.sum()),
        "sem_geometria": len(set(entrada.areas) - set(codigos)),
    }
    # Contagens podem se sobrepor; ausência não é zero, nem motivo para apagar a fazenda do cadastro.
    contagens["sem_medida"] = sum(entrada.areas.get(c) is None for c in codigos)
    colecoes = {uf: {"type": "FeatureCollection", "features": []} for uf in sorted(entrada.ufs)}
    ha_publicado = ha_suprimido = 0.0
    n_celulas = 0
    for celula, indices in sorted(grupos.items()):
        contribuintes = [i for i in indices if not sobrepostos[i] and (entrada.areas.get(codigos[i]) or 0) > 0]
        soma = math.fsum(entrada.areas[codigos[i]] for i in contribuintes)
        if len(indices) < 5:
            ha_suprimido += soma
            continue
        liberar = len(contribuintes) >= 5
        if liberar:
            contagens["incluidas"] += len(contribuintes)
            ha_publicado += soma
        else:
            ha_suprimido += soma
        anel = [[lon, lat] for lat, lon in h3.cell_to_boundary(celula)]
        anel.append(anel[0])
        feicao = {
            "type": "Feature",
            "properties": {"h3": celula, "fazendas": len(indices), "potencial_ha": soma if liberar else None},
            "geometry": {"type": "Polygon", "coordinates": [anel]},
        }
        n_celulas += 1
        # Células de fronteira são idênticas nos arquivos; o consumidor deduplica por H3, nunca soma cópias.
        ufs = set().union(*(entrada.ufs_por_car.get(codigos[i], {codigos[i][:2]}) for i in indices))
        for uf in sorted(ufs & entrada.ufs):
            colecoes[uf]["features"].append(feicao)
    datas = sorted(entrada.datas)
    meta = {
        "contrato": "potencial_h3",
        "versao": 1,
        "resolucao": RESOLUCAO,
        "dominio_ha": DOMINIO_HA,
        "atualizado_em": datas[-1] if datas else None,
        "fonte_mais_antiga_em": datas[0] if datas else None,
        "fonte": FONTE,
        "metodo": "ponto_interior_estatistico",
        "cobertura": "parcial",
        "aviso": AVISO,
        "minimo_contribuintes": 5,
        "zoom_maximo": 11,
        "contagens": contagens,
        "celulas_publicadas": n_celulas,
        "gerado_em": datetime.now(UTC).isoformat(),
    }
    for colecao in colecoes.values():
        colecao["metadados"] = meta
    ids_sobrepostos = {codigos[i] for i in np.flatnonzero(sobrepostos)}
    # Auditoria privada: não serializar totais suprimidos, que permitiriam reconstrução por diferença.
    auditoria = {
        "ha_publicado": ha_publicado,
        "ha_suprimido": ha_suprimido,
        "ha_sem_sobreposicao": math.fsum(
            entrada.areas.get(c) or 0 for i, c in enumerate(codigos) if not sobrepostos[i]
        ),
    }
    return meta, colecoes, ids_sobrepostos, auditoria


def gravar(destino: Path, meta: dict, colecoes: dict[str, dict], sobrepostos: set[str], conhecidos: set[str]) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    arquivos = {}
    for uf, colecao in colecoes.items():
        nome = f"potencial_{uf}.geojson.gz"
        dados = gzip.compress(
            json.dumps(colecao, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(), mtime=0
        )
        temporario = destino / (nome + ".tmp")
        temporario.write_bytes(dados)
        temporario.replace(destino / nome)
        arquivos[uf] = {"arquivo": nome, "bytes": len(dados)}
    # Nunca anunciar um agregado de execução anterior como parte da atual.
    for f in destino.glob("potencial_??.geojson.gz"):
        if f.name not in {a["arquivo"] for a in arquivos.values()}:
            f.unlink()
    indice = destino / "potencial_indice.json"
    indice.write_text(
        json.dumps({"potencial": arquivos, "potencial_metadados": meta}, ensure_ascii=False), encoding="utf-8"
    )
    # Sinal espacial básico, inferível dos mesmos contornos públicos. Nunca anexar hectares ao CAR.
    for f in destino.glob("imoveis_???????.geojson.gz"):
        dado = json.loads(gzip.decompress(f.read_bytes()))
        for feicao in dado.get("features", []):
            car = feicao.get("properties", {}).get("cod_imovel")
            feicao["properties"] = {"cod_imovel": car}
            if car in conhecidos:
                feicao["properties"]["sobreposto"] = car in sobrepostos
        f.write_bytes(gzip.compress(json.dumps(dado, separators=(",", ":")).encode(), mtime=0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dados-privados", type=Path, help="Espelho privado local; sem esta opção, lê o Release autenticado."
    )
    parser.add_argument("--destino", type=Path, default=Path("front/geo"))
    a = parser.parse_args()
    if a.dados_privados:
        entrada = ler_local(a.dados_privados)
    else:
        from raiz.executor.transferencia_privada import arquivo_privado

        entrada = ler_privado(arquivo_privado())
    meta, colecoes, sobrepostos, _auditoria = agregar(entrada)
    gravar(a.destino, meta, colecoes, sobrepostos, set(entrada.geometrias))
    print(
        json.dumps(
            {
                "potencial_h3": "publicado",
                "estados": len(colecoes),
                "contagens": meta["contagens"],
                "celulas": meta["celulas_publicadas"],
            }
        )
    )


if __name__ == "__main__":
    main()
