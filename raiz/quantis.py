"""Exportação pública de cenários por imóvel no formato longo do hubverse.

Só lê desenvolvedor_<mun>.csv e flag_<mun>.csv. ``reference_date`` é o dia UTC
da execução registrado nos metadados do arquivo, nunca uma data histórica das
fontes. Os quantis do desenvolvedor são preservados; cruzamentos são recusados.
FLAG recebe um prior triangular explícito (mínimo, moda central, máximo), sem
alterar suas colunas originais e sem alegar calibração ou medição em campo.

``quantis_uf`` devolve bytes para publicação e diagnósticos sem valores das
linhas. O Parquet público agrega modelos e traz suas versões. Dentro do hub
nativo, modelo/versão ficam no diretório e nos metadados, e os Parquet contêm
apenas as seis colunas do model output. Nada é gravado no espelho de entrada.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import math
import re
import tarfile
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

EXPORTADOR_VERSAO = "quantis-1"
TRIANGULAR_VERSAO = "triangular-1"
QUANTIS = (0.1, 0.5, 0.9)
ESQUEMA_TASKS = "https://raw.githubusercontent.com/hubverse-org/schemas/main/v6.0.0/tasks-schema.json"
REFERENCIA_METADATA = "https://hubverse.io/en/latest/user-guide/model-metadata.html"
REPO = "https://github.com/bernardoemmel/Raiz"
BASE_DATA = "dia_utc_da_execucao_do_arquivo_nao_corte_historico_das_fontes"
METODO_FLAG = "prior_triangular_nao_calibrado"
METODO_DESENVOLVEDOR = "quantis_publicados_p50_cenario_central"

# Nome do alvo, unidade, descrição e colunas P10/P50/P90. O anual líquido tem P50 sem sufixo.
ALVOS = {
    "custo_restauracao_ha": ("R$/ha", "Custo de restauração por hectare", "custo_restauracao_ha"),
    "captura_tco2_ha_ano": ("tCO2e/ha/ano", "Captura bruta anual média no horizonte do cenário", "captura_tco2_ha_ano"),
    "credito_liquido_tco2_ha_ano": (
        "tCO2e/ha/ano",
        "Crédito líquido anual médio no horizonte do cenário",
        "credito_liquido_tco2_ha_ano",
    ),
    "credito_liquido_ha_contrato": (
        "tCO2e/ha",
        "Crédito líquido até o fim do contrato do cenário",
        "credito_liquido_tco2_ha_contrato",
    ),
    "vpl_rs_ha": ("R$/ha", "Valor presente líquido por hectare", "vpl_rs_ha"),
    "tir_projeto_pct": ("%/ano", "Taxa interna de retorno do projeto", "tir_projeto_pct"),
    "tir_alavancada_pct": ("%/ano", "Taxa interna de retorno com financiamento", "tir_alavancada_pct"),
    "pico_capital_proprio_rs_ha": ("R$/ha", "Pico de capital próprio por hectare", "pico_capital_proprio_rs_ha"),
    "flag_tco2_ano": ("tCO2e/ano", "Remoção FLAG: cenário triangular provisório, sem calibração", "flag_tco2_ano"),
}
COLUNAS = ["reference_date", "location", "target", "output_type", "output_type_id", "value"]
EXTRAS = ["model_id", "model_version", "source_model_version", "task_version", "quantile_method", "source_file"]
ESQUEMA_SAIDA = pa.schema(
    [
        ("reference_date", pa.date32()),
        ("location", pa.string()),
        ("target", pa.string()),
        ("output_type", pa.string()),
        ("output_type_id", pa.float64()),
        ("value", pa.float64()),
    ]
)
ESQUEMA_PUBLICO = pa.schema([*ESQUEMA_SAIDA, *[(c, pa.string()) for c in EXTRAS]])
_ARQUIVO = re.compile(r"(desenvolvedor|flag)_(\d{7})\.csv$")
_CAR = re.compile(r"[A-Z]{2}-\d{7}-[A-Za-z0-9]+$")


def triangular(minimo: float, moda: float, maximo: float, q: float) -> float:
    """Inversa da CDF triangular. O P50 não é necessariamente a moda central."""
    if not all(math.isfinite(v) for v in (minimo, moda, maximo, q)) or not minimo <= moda <= maximo:
        raise ValueError("parâmetros triangulares inválidos")
    if not 0 <= q <= 1:
        raise ValueError("quantil fora de [0, 1]")
    if minimo == maximo:
        return minimo
    largura = maximo - minimo
    if not math.isfinite(largura):
        raise ValueError("largura triangular não finita")
    if q <= (moda - minimo) / largura:
        return minimo + largura * math.sqrt(q * ((moda - minimo) / largura))
    return maximo - largura * math.sqrt((1 - q) * ((maximo - moda) / largura))


def model_id(tarefa: str, versao: str) -> str:
    if tarefa not in {"desenvolvedor", "flag"} or not versao.strip():
        raise ValueError("modelo público desconhecido ou sem versão")
    return f"raiz-{tarefa}_{hashlib.sha256(versao.encode()).hexdigest()[:16]}"


def esquema_modelos() -> dict:
    """Schema do hub Raíz: customização permitida pelo hubverse, sem inventar licença dos dados."""
    campos = {
        "team_name": {"type": "string"},
        "team_abbr": {"const": "raiz"},
        "model_name": {"type": "string"},
        "model_abbr": {"type": "string", "pattern": "^[A-Za-z0-9_+]+$"},
        "model_version": {"type": "string", "minLength": 1},
        "source_model_version": {"type": "string", "minLength": 1},
        "task_version": {"type": "string", "minLength": 1},
        "exporter_version": {"const": EXPORTADOR_VERSAO},
        "quantile_method": {"enum": [METODO_FLAG, METODO_DESENVOLVEDOR]},
        "reference_date_basis": {"const": BASE_DATA},
        "license_status": {"const": "licenca_dos_dados_derivados_nao_definida"},
        "model_details": {"type": "object", "required": ["data_inputs", "methods", "methods_long"]},
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Metadados dos modelos públicos da Raíz",
        "description": f"Schema próprio conforme {REFERENCIA_METADATA}",
        "type": "object",
        "properties": campos,
        "required": list(campos),
        "additionalProperties": True,
    }


def tasks(datas=(), locais=()) -> dict:
    """Configuração hubverse v6: allowlist fixa de alvos e valores observados de data/local."""
    metas = []
    for alvo, (unidade, nome, coluna) in ALVOS.items():
        metas.append(
            {
                "target_id": alvo,
                "target_name": nome,
                "target_units": unidade,
                "target_keys": {"target": alvo},
                "target_type": "continuous",
                "is_step_ahead": False,
                "description": "Cenário por imóvel, com horizonte original e sem data de vencimento inferida.",
                "additional_metadata": {"source_column": coluna, "reference_date_basis": BASE_DATA},
            }
        )
    return {
        "schema_version": ESQUEMA_TASKS,
        "output_type_id_datatype": "double",
        "rounds": [
            {
                "round_id_from_variable": True,
                "round_id": "reference_date",
                "model_tasks": [
                    {
                        "task_ids": {
                            "reference_date": {"required": None, "optional": sorted({str(x) for x in datas})},
                            "location": {"required": None, "optional": sorted(set(locais))},
                            "target": {"required": None, "optional": list(ALVOS)},
                        },
                        "output_type": {
                            "quantile": {
                                "output_type_id": {"required": list(QUANTIS)},
                                "value": {"type": "double"},
                                "is_required": True,
                            }
                        },
                        "target_metadata": metas,
                    }
                ],
                "submissions_due": {"relative_to": "reference_date", "start": 0, "end": 3650},
                "additional_metadata": {"reference_date_basis": BASE_DATA},
            }
        ],
    }


def combinar_tasks(configuracoes) -> dict:
    """Une configurações estaduais já publicadas; não precisa dos CSV dos outros estados."""
    datas, locais = set(), set()
    for configuracao in configuracoes:
        if configuracao.get("schema_version") != ESQUEMA_TASKS:
            raise ValueError("configuração de hub incompatível")
        for rodada in configuracao["rounds"]:
            for tarefa in rodada["model_tasks"]:
                ids = tarefa["task_ids"]
                for nome, destino in (("reference_date", datas), ("location", locais)):
                    destino.update(ids[nome].get("required") or [])
                    destino.update(ids[nome].get("optional") or [])
    return tasks(datas, locais)


def admin() -> dict:
    return {
        "schema_version": ESQUEMA_TASKS.replace("tasks-schema", "admin-schema"),
        "name": "Raíz: cenários públicos de restauração e FLAG",
        "maintainer": "Raíz",
        "contact": {"name": "Raíz"},
        "repository": {"host": "github", "owner": "bernardoemmel", "name": "Raiz"},
        "file_format": ["parquet"],
        "timezone": "America/Sao_Paulo",
        "additional_metadata": {"reference_date_basis": BASE_DATA},
    }


def _json(valor) -> bytes:
    return (json.dumps(valor, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _sha(arquivo: Path) -> str:
    h = hashlib.sha256()
    with arquivo.open("rb") as entrada:
        for bloco in iter(lambda: entrada.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _data(valor: str) -> dt.date:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor):
        return dt.date.fromisoformat(valor)
    data = dt.datetime.fromisoformat(valor.replace("Z", "+00:00"))
    if data.tzinfo is None:
        raise ValueError("execução sem fuso")
    return data.astimezone(dt.UTC).date()


def _numero(valor) -> float:
    if valor is None or not str(valor).strip():
        raise ValueError("valor_ausente")
    try:
        n = float(valor)
    except (TypeError, ValueError) as ex:
        raise ValueError("valor_invalido") from ex
    if not math.isfinite(n):
        raise ValueError("valor_nao_finito")
    return n


def _versao(valor) -> str:
    texto = str(valor or "").strip()
    return "" if texto.lower() in {"nan", "null", "none", "<na>", "publicado"} else texto


def _modelo(tarefa: str, original: str, versao_tarefa: str, cenario: str) -> tuple[str, dict]:
    metodo = METODO_FLAG if tarefa == "flag" else METODO_DESENVOLVEDOR
    partes = [original, f"tarefa={versao_tarefa}", f"exportador={EXPORTADOR_VERSAO}"]
    if tarefa == "flag":
        partes.append(TRIANGULAR_VERSAO)
    elif cenario:
        partes.append(f"cenario={cenario}")
    versao = "|".join(partes)
    mid = model_id(tarefa, versao)
    metodos = (
        "Prior triangular sobre mínimo, moda central e máximo anuais publicados; sem calibração."
        if tarefa == "flag"
        else "P10/P90 publicados; P50 do cenário central determinístico, sem reordenar valores."
    )
    detalhes = (
        "CDF inversa triangular aplicada à faixa anual total do imóvel; P50 não necessariamente igual à moda. "
        "Não se trata de intervalo medido ou calibrado; não muda a conta FLAG original nem soma crédito Verra."
        if tarefa == "flag"
        else "Valores copiados das colunas declaradas, sem impor distribuição adicional. "
        "P10/P90 econômicos vêm de Monte Carlo; P50 é o caminho central das premissas, não a mediana amostral."
    )
    return mid, {
        "team_name": "Raíz",
        "team_abbr": "raiz",
        "model_name": f"Raíz: {tarefa}",
        "model_abbr": mid.split("-", 1)[1],
        "model_version": versao,
        "source_model_version": original,
        "task_version": versao_tarefa,
        "exporter_version": EXPORTADOR_VERSAO,
        "quantile_method": metodo,
        "reference_date_basis": BASE_DATA,
        "license_status": "licenca_dos_dados_derivados_nao_definida",
        "repo_url": REPO,
        "model_details": {
            "data_inputs": f"{tarefa}_<codigo_municipio>.csv público e metadados da execução do arquivo.",
            "methods": metodos,
            "methods_long": detalhes,
        },
    }


def _colunas(tarefa: str, alvo: str) -> tuple[str, str, str]:
    if tarefa == "flag":
        return "flag_tco2_ano_min", "flag_tco2_ano", "flag_tco2_ano_max"
    base = ALVOS[alvo][2]
    return f"{base}_p10", base if base == "credito_liquido_tco2_ha_ano" else f"{base}_p50", f"{base}_p90"


def _tar(arquivos: dict[str, bytes]) -> bytes:
    destino = io.BytesIO()
    with (
        gzip.GzipFile(fileobj=destino, mode="wb", mtime=0, filename="") as gz,
        tarfile.open(fileobj=gz, mode="w") as tar,
    ):
        for nome, dados in sorted(arquivos.items()):
            info = tarfile.TarInfo(nome)
            info.size, info.mtime = len(dados), 0
            tar.addfile(info, io.BytesIO(dados))
    return destino.getvalue()


def quantis_uf(pasta: str | Path, uf: str, versoes: dict | None = None) -> dict:
    """Gera artefatos a partir do espelho de UMA UF, sem banco, rede ou escrita no espelho.

    ``versoes`` é arquivo -> metadados (tarefa, versao, data, sha256). Tem precedência
    sobre .meta.json e _versoes.json. Data/versão ausentes são diagnosticadas; não se
    usa a data de publicação nem a versão atualmente instalada como substituto.
    """
    pasta = Path(pasta)
    uf = uf.upper()
    if not re.fullmatch(r"[A-Z]{2}", uf):
        raise ValueError("UF inválida")
    diagnosticos, modelos, fontes = [], {}, []
    datas, locais = set(), set()
    total = 0

    def diagnostico(arquivo, linha, alvo, codigo):
        diagnosticos.append({"arquivo": arquivo, "linha": linha, "target": alvo, "codigo": codigo})

    manifesto = pasta / "_versoes.json"
    publicadas = json.loads(manifesto.read_text()) if manifesto.exists() else {}
    with tempfile.TemporaryDirectory(prefix="raiz-quantis-") as temporario:
        saida = Path(temporario)
        publico = pq.ParquetWriter(saida / "quantis.parquet", ESQUEMA_PUBLICO, compression="zstd")
        escritores, buffers, emitidos = {}, {}, {}

        def despejar(chave):
            linhas = buffers[chave]
            if not linhas:
                return
            publico.write_table(pa.Table.from_pylist(linhas, schema=ESQUEMA_PUBLICO))
            escritores[chave].write_table(pa.Table.from_pylist(linhas, schema=ESQUEMA_SAIDA))
            linhas.clear()

        try:
            for arquivo in sorted(pasta.glob("*.csv")):
                achado = _ARQUIVO.fullmatch(arquivo.name)
                if not achado:
                    continue
                tarefa, _municipio = achado.groups()
                meta = dict(publicadas.get(arquivo.name) or {})
                lateral = arquivo.with_name(arquivo.name + ".meta.json")
                if lateral.exists():
                    meta.update(json.loads(lateral.read_text()))
                meta.update((versoes or {}).get(arquivo.name) or {})
                versao_tarefa = _versao(meta.get("versao"))
                if not versao_tarefa:
                    diagnostico(arquivo.name, None, None, "versao_da_tarefa_ausente")
                    continue
                try:
                    data = _data(str(meta.get("data") or ""))
                except ValueError:
                    diagnostico(arquivo.name, None, None, "data_da_execucao_ausente_ou_invalida")
                    continue
                sha = _sha(arquivo)
                if meta.get("sha256") and meta["sha256"] != sha:
                    diagnostico(arquivo.name, None, None, "sha256_da_fonte_divergente")
                    continue
                fontes.append(
                    {
                        "arquivo": arquivo.name,
                        "sha256": sha,
                        "task_version": versao_tarefa,
                        "reference_date": data.isoformat(),
                        "source_execution_time": str(meta["data"]),
                    }
                )
                with arquivo.open(newline="", encoding="utf-8-sig") as entrada:
                    leitor = csv.DictReader(entrada)
                    cabecalho = set(leitor.fieldnames or [])
                    campo_versao = "flag_regra_versao" if tarefa == "flag" else "restauracao_versao"
                    if not {"cod_imovel", campo_versao} <= cabecalho:
                        diagnostico(arquivo.name, None, None, "identificador_ou_versao_do_modelo_ausente")
                        continue
                    alvos = ["flag_tco2_ano"] if tarefa == "flag" else [a for a in ALVOS if a != "flag_tco2_ano"]
                    completos = []
                    for alvo in alvos:
                        if not set(_colunas(tarefa, alvo)) <= cabecalho:
                            diagnostico(arquivo.name, None, alvo, "coluna_de_quantil_ausente")
                        else:
                            completos.append(alvo)
                    vistos = set()
                    for numero, linha in enumerate(leitor, 2):
                        car = str(linha.get("cod_imovel") or "").strip()
                        if not _CAR.fullmatch(car) or not car.startswith(f"{uf}-"):
                            diagnostico(arquivo.name, numero, None, "codigo_car_ausente_ou_incompativel")
                            continue
                        if car in vistos:
                            diagnostico(arquivo.name, numero, None, "codigo_car_duplicado")
                            continue
                        vistos.add(car)
                        original = _versao(linha.get(campo_versao))
                        if not original:
                            diagnostico(arquivo.name, numero, None, "versao_do_modelo_ausente")
                            continue
                        mid, modelo = _modelo(
                            tarefa, original, versao_tarefa, str(linha.get("restauracao_cenario") or "")
                        )
                        chave = (mid, data.isoformat())
                        if car in emitidos.get(chave, set()):
                            diagnostico(arquivo.name, numero, None, "codigo_car_duplicado_na_rodada_do_modelo")
                            continue
                        for alvo in completos:
                            try:
                                valores = tuple(_numero(linha.get(c)) for c in _colunas(tarefa, alvo))
                            except ValueError as ex:
                                diagnostico(arquivo.name, numero, alvo, str(ex))
                                continue
                            if not valores[0] <= valores[1] <= valores[2]:
                                diagnostico(
                                    arquivo.name,
                                    numero,
                                    alvo,
                                    "quantis_cruzados" if tarefa != "flag" else "faixa_triangular_invalida",
                                )
                                continue
                            if tarefa == "flag":
                                if valores[0] < 0:
                                    diagnostico(arquivo.name, numero, alvo, "faixa_flag_negativa")
                                    continue
                                valores = tuple(triangular(*valores, q) for q in QUANTIS)
                            if chave not in escritores:
                                destino = saida / "model-output" / mid / f"{data}-{mid}.parquet"
                                destino.parent.mkdir(parents=True, exist_ok=True)
                                escritores[chave] = pq.ParquetWriter(destino, ESQUEMA_SAIDA, compression="zstd")
                                buffers[chave] = []
                                emitidos[chave] = set()
                            emitidos[chave].add(car)
                            modelos[mid] = modelo
                            datas.add(data.isoformat())
                            locais.add(car)
                            for q, valor in zip(QUANTIS, valores, strict=True):
                                buffers[chave].append(
                                    {
                                        "reference_date": data,
                                        "location": car,
                                        "target": alvo,
                                        "output_type": "quantile",
                                        "output_type_id": q,
                                        "value": valor,
                                        "model_id": mid,
                                        "model_version": modelo["model_version"],
                                        "source_model_version": original,
                                        "task_version": versao_tarefa,
                                        "quantile_method": modelo["quantile_method"],
                                        "source_file": arquivo.name,
                                    }
                                )
                                total += 1
                            if len(buffers[chave]) >= 10000:
                                despejar(chave)
            for chave in buffers:
                despejar(chave)
        finally:
            publico.close()
            for escritor in escritores.values():
                escritor.close()
        configuracao = tasks(datas, locais)
        nativos = {
            p.relative_to(saida).as_posix(): p.read_bytes() for p in sorted((saida / "model-output").rglob("*.parquet"))
        }
        nativos["hub-config/tasks.json"] = _json(configuracao)
        nativos["hub-config/admin.json"] = _json(admin())
        nativos["hub-config/model-metadata-schema.json"] = _json(esquema_modelos())
        for mid, modelo in modelos.items():
            nativos[f"model-metadata/{mid}.yml"] = yaml.safe_dump(modelo, allow_unicode=True, sort_keys=True).encode()
        metadados = {
            "exporter_version": EXPORTADOR_VERSAO,
            "reference_date_basis": BASE_DATA,
            "modelos": modelos,
            "fontes": fontes,
        }
        arquivos = {
            f"quantis_{uf}.parquet": (saida / "quantis.parquet").read_bytes(),
            f"tasks_{uf}.json": _json(configuracao),
            f"modelos_{uf}.json": _json(metadados),
            f"diagnosticos_quantis_{uf}.json": _json(diagnosticos),
            f"hub_{uf}.tar.gz": _tar(nativos),
        }
    return {
        "arquivos": arquivos,
        "modelos": modelos,
        "diagnosticos": diagnosticos,
        "linhas": total,
        "tasks": configuracao,
    }
