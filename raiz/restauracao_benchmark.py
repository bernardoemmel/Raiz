"""Mede seleção sobre oferta sintética; não representa cobertura real do Brasil."""

import argparse
import json
import pathlib
import resource
import time

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from raiz import restauracao as R
from raiz import restauracao_catalogo as C
from raiz import restauracao_nacional as N
from raiz.pedidos.campos import CamposPedido


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--linhas", type=int, default=7000000)
    p.add_argument("--destino", type=pathlib.Path, required=True)
    p.add_argument("--misto", action="store_true")
    a = p.parse_args()
    if not 1 <= a.linhas <= 10000000:
        raise ValueError("Escolha de 1 a 10 milhões de imóveis sintéticos")
    base = a.destino
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    f = base / "oferta.parquet"
    inicio = time.monotonic()
    n = a.linhas
    cenario = R.cenario()
    if f.exists():
        raise ValueError("Use destino novo para medir uma execução sem cache de resultado")
    if not f.exists():
        with pq.ParquetWriter(f, C.SCHEMA, compression="zstd") as w:
            for ini in range(0, n, 100000):
                k = min(n, ini + 100000)
                i = np.arange(ini, k)
                tam = len(i)
                pequena = (i % 5 != 0) if a.misto else np.full(tam, True)
                area = np.where(pequena, (i % 199 + 1) / 10, 100 + (i % 499))
                credito = area * 160
                valores = {
                    "cod_imovel": [f"SINTETICO-{v:09}" for v in i],
                    "uf": "PA",
                    "municipio": "sintético",
                    "cod_ibge": 1500107,
                    "bioma": "Amazônia",
                    "modo": "regeneracao_assistida",
                    "caminho": "matricula_a_conferir",
                    "caminho_terra": "privada_matricula",
                    "risco_terra": "baixo",
                    "restauracao_versao": R.versao(),
                    "restauracao_cenario": cenario["cenario"],
                    "entradas_versao": "sintetico",
                    "situacao_previsao": "compativel",
                    "pendencias": "jurisdicional_a_conferir",
                    "nivel_interesse": "sem_contato",
                    "consulta_livre_previa_informada": "nao_sinalizada",
                    "ha": area * 2,
                    "area_ha": area,
                    "m_fiscal": area / 75,
                    "pequena": pequena,
                    "local_aproximado": False,
                    "elegivel": True,
                    "problema": False,
                    "bloqueio": False,
                    "salvaguardas_planejamento": True,
                    "salvaguardas_comercializavel": False,
                    "lon": -73 + (i % 7000) * 0.005,
                    "lat": -30 + ((i // 7000) % 1000) * 0.03,
                    "credito_p10": credito * 0.6,
                    "credito_p50": credito,
                    "credito_p90": credito * 1.3,
                    "credito_ano": credito / 25,
                    "custo_credito_usd": 20 + (i % 80) * 0.5,
                    "preco_equilibrio_usd": 35 + (i % 80) * 0.5,
                    "tir_p10": 3.0,
                    "tir_p50": 12.0,
                    "tir_p90": 20.0,
                    "tir_projeto": 10.0,
                    "reserva_risco_pct": 20.0,
                    "regeneracao_ha": area,
                    "semeadura_ha": 0.0,
                    "plantio_ha": 0.0,
                    "metodos": ["regeneracao_assistida"],
                }
                arrays = []
                for campo in C.SCHEMA:
                    v = valores.get(campo.name, False if pa.types.is_boolean(campo.type) else None)
                    arrays.append(
                        pa.array(v, type=campo.type)
                        if isinstance(v, np.ndarray) or campo.name == "cod_imovel"
                        else pa.repeat(pa.scalar(v, type=campo.type), tam)
                    )
                w.write_table(pa.Table.from_arrays(arrays, schema=C.SCHEMA))
    part = {
        "uf": "PA",
        "municipio": 1500107,
        "acesso": "privado",
        "esquema": C.ESQUEMA,
        "id": "sintetico",
        "fontes": {},
        "arquivos": {"oferta": {"caminho": "oferta.parquet", "sha256": C.sha256(f), "bytes": f.stat().st_size}},
    }
    catalogo = C.consolidar_catalogo(
        [part],
        base,
        municipios_esperados={"PA": [1500107]},
        proveniencia={
            "sintetico": True,
            "observacoes": "Teste de escala computacional; nenhuma cobertura real do Brasil ou fazenda.",
        },
    )
    preparo = time.monotonic() - inicio
    r = N.montar_tres_opcoes(
        catalogo,
        CamposPedido(
            dinheiro={"preco_venda_usd": cenario["preco_usd_t"], "fracao_financiada": cenario["fracao_financiada"]}
        ),
        N.normalizar_recorte(brasil=True),
        modelo=R.versao(),
        cenario=cenario["cenario"],
        destino=base / "consultas",
    )
    saida = {
        "sintetico": True,
        "misto": a.misto,
        "linhas": n,
        "preparo_s": preparo,
        "consulta_tempos": r["tempos"],
        "pico_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "cpu_max": pathlib.Path("/sys/fs/cgroup/cpu.max").read_text().strip(),
        "modelo": R.versao(),
        "indice_versao": C.versao_indice(),
        "modelo_lote": r["versao"],
        "catalogo_sha256": C.sha256(catalogo),
        "opcoes": {
            op: {
                k: v
                for k, v in x.items()
                if k in ("estado", "fazendas", "pequenas", "fecha_meta", "fecha_reserva", "diagnosticos")
            }
            for op, x in r["opcoes"].items()
        },
        "ressalva": "Somente consulta/seleção sobre índice sintético; sem simulação municipal "
        "nem recomposição dos fluxos das selecionadas.",
    }
    C.gravar_json(base / "benchmark.json", saida)
    print(json.dumps(saida, ensure_ascii=False))


if __name__ == "__main__":
    main()
