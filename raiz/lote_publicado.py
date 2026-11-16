"""Contratos dos lotes finais imutáveis e CADT dos cinco marcos já publicados.

Não seleciona fazendas, não executa o modelo e não interpola previsões anuais.
O valor inteiro de cada período é a diferença entre acumulados arredondados;
os números originais, inclusive o total fracionário, permanecem nos metadados.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from raiz import cadt, metadados

OPCOES = ("barata", "segura", "compacta")
MARCOS = (7, 12, 17, 22, 25)
VERSAO = "lote-publicado-1"
VERSAO_CADT = "lote-cadt-marcos-publicados-1"
MANIFESTO = re.compile(r"lote_PA_central_r11_retomada_([0-9]+)_([0-9]+)_([a-f0-9]{16})\.json")
SHA = re.compile(r"[a-f0-9]{64}")
COMMIT = re.compile(r"[a-f0-9]{40}")
VERSOES = ("versao_premissas", "versao_otimizador", "versao_modelo_lote", "versao_edital")


class LoteInvalido(ValueError):
    """Só códigos fixos, sem conteúdos ou nomes privados nas mensagens."""


def exigir(condicao, codigo):
    if not condicao:
        raise LoteInvalido(codigo)


def sha256(caminho: Path) -> str:
    with Path(caminho).open("rb") as arquivo:
        return hashlib.file_digest(arquivo, "sha256").hexdigest()


def json_bytes(dado) -> bytes:
    return (json.dumps(dado, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def namespace(digest: str) -> str:
    exigir(isinstance(digest, str) and SHA.fullmatch(digest), "sha_manifesto_invalido")
    return f"lote_PA_central_r11_{digest[:16]}"


def eh_manifesto(nome: str) -> bool:
    return isinstance(nome, str) and MANIFESTO.fullmatch(nome) is not None


def eh_pacote(nome: str) -> bool:
    return (
        isinstance(nome, str)
        and re.fullmatch(
            r"lote_PA_central_r11_retomada_[0-9]+_[0-9]+_(barata|segura|compacta|previsoes)_[a-f0-9]{16}\.tar\.gz", nome
        )
        is not None
    )


def data_declarada(manifesto: dict) -> dt.date:
    datas = {manifesto["resumos"][opcao].get("data") for opcao in OPCOES}
    exigir(len(datas) == 1, "datas_resumos_divergentes")
    valor = next(iter(datas))
    exigir(isinstance(valor, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor), "data_resumo_ausente")
    try:
        return dt.date.fromisoformat(valor)
    except ValueError:
        raise LoteInvalido("data_resumo_invalida") from None


def _numero(valor) -> float:
    exigir(type(valor) in (int, float) and math.isfinite(valor), "numero_do_resumo_invalido")
    return valor


def proveniencia(manifesto: dict) -> dict:
    """Distingue a origem e a retomada, sem atribuir a cada CSV uma execução não registrada."""
    retomada = manifesto["retomada"]
    origem, orquestrador = retomada.get("sha_origem"), retomada.get("sha_orquestrador")
    exigir(
        isinstance(origem, str)
        and COMMIT.fullmatch(origem)
        and isinstance(orquestrador, str)
        and COMMIT.fullmatch(orquestrador)
        and manifesto.get("commit") == origem,
        "commits_da_proveniencia_invalidos",
    )
    for campo in ("execucao_origem", "execucao_atual"):
        exigir(re.fullmatch(r"[0-9]+", str(retomada.get(campo, ""))), "execucao_da_proveniencia_invalida")
    exigir(str(manifesto.get("execucao")) == str(retomada["execucao_atual"]), "execucao_final_divergente")
    fatias = {}
    for campo in ("fatias_reusadas", "fatias_calculadas"):
        valores = retomada.get(campo)
        exigir(
            isinstance(valores, list)
            and len(valores) == len(set(valores))
            and all(isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", v) for v in valores),
            "fatias_da_proveniencia_invalidas",
        )
        fatias[campo] = sorted(valores)
    exigir(not set(fatias["fatias_reusadas"]) & set(fatias["fatias_calculadas"]), "fatias_de_origens_sobrepostas")
    return {
        "origem": {"execucao": str(retomada["execucao_origem"]), "commit": origem},
        "retomada": {"execucao": str(retomada["execucao_atual"]), "commit_orquestrador": orquestrador, **fatias},
        "execucao_individual_das_previsoes": "nao_registrada",
        "versao_tarefa_individual": None,
    }


def ler_manifesto(caminho: Path, nome: str, *, base_url: str) -> tuple[dict, str]:
    exigir(eh_manifesto(nome), "nome_manifesto_nao_reconhecido")
    exigir(Path(caminho).stat().st_size <= 8 * 1024**2, "manifesto_acima_do_limite")
    bruto = Path(caminho).read_bytes()
    digest = hashlib.sha256(bruto).hexdigest()
    match = MANIFESTO.fullmatch(nome)
    exigir(digest.startswith(match[3]), "nome_manifesto_diverge_dos_bytes")
    metadados._url_acesso(base_url + nome, escopo="privado")
    try:
        manifesto = json.loads(bruto)
        exigir(
            manifesto.get("uf") == "PA"
            and manifesto.get("cenario") == "central_r11"
            and set(manifesto.get("opcoes", [])) == set(OPCOES)
            and set(manifesto["resumos"]) == set(OPCOES)
            and set(manifesto["arquivos"]) == {*OPCOES, "previsoes"},
            "estrutura_manifesto_incompativel",
        )
        prov = proveniencia(manifesto)
        exigir(prov["retomada"]["execucao"] == match[1], "execucao_diverge_do_nome")
        data_declarada(manifesto)
        for opcao in OPCOES:
            resumo = manifesto["resumos"][opcao]
            exigir(
                resumo.get("uf") == "PA" and resumo.get("cenario") == "central_r11" and resumo.get("opcao") == opcao,
                "opcao_diverge_do_resumo",
            )
            exigir(all(isinstance(resumo.get(c), str) and resumo[c].strip() for c in VERSOES), "versao_resumo_ausente")
            exigir(resumo["versao_premissas"] == manifesto.get("modelo_versao"), "modelo_resumo_divergente")
            faixa = resumo["creditos_lote_faixa"]
            exigir(set(faixa) == {"p10", "p50", "p90"}, "faixa_resumo_incompleta")
            numeros = [_numero(faixa[q]) for q in ("p10", "p50", "p90")]
            exigir(0 <= numeros[0] <= numeros[1] <= numeros[2], "faixa_resumo_invalida")
        for tipo, ref in manifesto["arquivos"].items():
            exigir(
                type(ref.get("asset_id")) is int
                and ref["asset_id"] > 0
                and type(ref.get("bytes")) is int
                and 0 < ref["bytes"] <= 8 * 1024**3
                and isinstance(ref.get("sha256"), str)
                and SHA.fullmatch(ref["sha256"]),
                "referencia_pacote_invalida",
            )
            esperado = f"lote_PA_central_r11_retomada_{match[1]}_{match[2]}_{tipo}_{ref['sha256'][:16]}.tar.gz"
            exigir(ref.get("nome") == esperado, "nome_pacote_diverge_da_referencia")
            metadados._url_acesso(base_url + esperado, escopo="privado")
    except (KeyError, TypeError, json.JSONDecodeError):
        raise LoteInvalido("estrutura_manifesto_invalida") from None
    return manifesto, digest


def conferir_pacotes(manifesto: dict, pacotes: dict[str, Path]) -> None:
    exigir(set(pacotes) == {*OPCOES, "previsoes"}, "pacotes_do_lote_incompletos")
    for tipo, caminho in pacotes.items():
        ref = manifesto["arquivos"][tipo]
        exigir(Path(caminho).is_file() and not Path(caminho).is_symlink(), "pacote_local_invalido")
        exigir(Path(caminho).stat().st_size == ref["bytes"], "tamanho_pacote_divergente")
        exigir(sha256(caminho) == ref["sha256"], "sha_pacote_divergente")


def _inteiro(valor) -> int:
    return int(Decimal(str(_numero(valor))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def projetos_cadt(manifesto: dict, digest: str, *, data_inicio: str, base_url: str) -> dict:
    """Cinco períodos publicados cobrem 25 anos; não presume a distribuição dentro de cada período."""
    try:
        inicio = dt.date.fromisoformat(data_inicio)
    except (TypeError, ValueError):
        raise LoteInvalido("inicio_de_cenario_nao_informado_ou_invalido") from None
    exigir(inicio.year <= 9974, "inicio_cenario_fora_do_calendario")
    ns, projetos = namespace(digest), []
    url = base_url + ns + "_cadt.json"
    metadados._url_acesso(url, escopo="privado")
    for opcao in OPCOES:
        resumo = manifesto["resumos"][opcao]
        cronograma = resumo["cronograma_lote"]
        marcos = cronograma.get("marcos", [])
        exigir([m.get("ano") for m in marcos] == list(MARCOS), "anos_marcos_do_lote_divergentes")
        acumulados = [_numero(m["acumulado_p50"]) for m in marcos]
        total = _numero(cronograma["credito_contrato_p50"])
        exigir(total > 0 and acumulados[-1] == total, "total_cronograma_diverge_ultimo_marco")
        exigir(all(a <= b for a, b in zip([0, *acumulados], acumulados, strict=False)), "marcos_decrescentes")
        estimativas, anteriores = [], (0, 0)
        for marco in marcos:
            ano, inteiro = marco["ano"], _inteiro(marco["acumulado_p50"])
            anterior, unidades = anteriores
            estimativas.append(
                {
                    "creditingPeriodStart": cadt._aniversario(inicio, anterior).isoformat(),
                    "creditingPeriodEnd": (cadt._aniversario(inicio, ano) - dt.timedelta(days=1)).isoformat(),
                    "unitCount": inteiro - unidades,
                }
            )
            anteriores = (ano, inteiro)
        identidade = {
            "uf": "PA",
            "cenario": "central_r11",
            "opcao": opcao,
            "inicio": inicio.isoformat(),
            "source_manifest_sha256": digest,
            "source_option_archive_sha256": manifesto["arquivos"][opcao]["sha256"],
            "versoes": {c: resumo[c] for c in VERSOES},
            "exportador": VERSAO_CADT,
        }
        identificador = "raiz-lote-PA-" + opcao + "-" + hashlib.sha256(json_bytes(identidade)).hexdigest()[:32]
        projetos.append(
            {
                "opcao": opcao,
                "projeto": {
                    "projectId": identificador,
                    "originProjectId": identificador,
                    "projectName": f"Cenário de lote Raíz — PA — {opcao}",
                    "projectDeveloper": "Raíz — modelagem de cenário",
                    "registryOfOrigin": "Raíz — catálogo de cenários",
                    "projectLink": url + "#" + identificador,
                    "sector": "Agriculture; forestry and fishing",
                    "projectType": "Reforestation and Revegetation",
                    "coveredByNDC": "Unknown",
                    "projectStatus": "Listed",
                    "unitMetric": "tCO2e",
                    "methodology": "VCS - VM0047",
                    "projectStatusDate": resumo["data"],
                    "description": cadt.AVISO,
                    "estimations": estimativas,
                },
                "metadados": {
                    "escopo": "privado",
                    "identidade": identidade,
                    "versao_exportador": VERSAO_CADT,
                    "data_inicio_cenario": inicio.isoformat(),
                    "data_inicio_contratada": False,
                    "data_montagem_declarada": resumo["data"],
                    "data_execucao_individual": None,
                    "resolucao": "cinco_periodos_dos_marcos_publicados",
                    "prazo_anos": 25,
                    "credito_contrato_p50": total,
                    "total_inteiro_tco2e": _inteiro(total),
                    "marcos": [
                        {
                            "ano": m["ano"],
                            "acumulado_p50": m["acumulado_p50"],
                            "acumulado_inteiro": _inteiro(m["acumulado_p50"]),
                        }
                        for m in marcos
                    ],
                    "arredondamento": (
                        "acumulados publicados à unidade mais próxima (meia para cima), depois diferenças entre marcos"
                    ),
                    "previsoes_recalculadas": False,
                    "carteira_reotimizada": False,
                    "estimativas_anuais_inferidas": False,
                    "comercializacao": {"situacao": "pendente"},
                    "proveniencia_execucoes": proveniencia(manifesto),
                    "source_summary": f"#/resumos/{opcao}/cronograma_lote",
                    "source_option_archive_url": base_url + manifesto["arquivos"][opcao]["nome"],
                },
            }
        )
    return {"perfil": VERSAO_CADT, "source_manifest_sha256": digest, "projetos": projetos}


def gerar(
    manifesto_path: Path, nome: str, pacotes: dict[str, Path], destino: Path, *, base_url: str, data_inicio: str
) -> dict:
    """Gera somente arquivos novos locais a partir dos produtos completos já publicados."""
    from raiz.quantis_lote import exportar

    manifesto, digest = ler_manifesto(manifesto_path, nome, base_url=base_url)
    conferir_pacotes(manifesto, pacotes)
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True, mode=0o700)
    resultado = exportar(manifesto, digest, pacotes, destino, base_url=base_url)
    arquivos = resultado["arquivos"]
    ns = namespace(digest)
    arquivo_cadt = destino / f"{ns}_cadt.json"
    arquivo_cadt.write_bytes(json_bytes(projetos_cadt(manifesto, digest, data_inicio=data_inicio, base_url=base_url)))
    arquivos[arquivo_cadt.name] = arquivo_cadt
    cartao = destino / f"{ns}_cartao_modelo.md"
    cartao.write_text(
        "# Cartão dos produtos finais do lote PA\n\n"
        f"Manifesto de origem (SHA256): {digest}. Modelo original: {manifesto['modelo_versao']}.\n\n"
        "Valores e opções publicados são preservados. Não há recálculo, nova seleção nem reordenação dos quantis. "
        "P50 pode ser cenário central determinístico; os intervalos não demonstram calibração.\n\n"
        "reference_date é a data declarada de montagem/consolidação do lote. Não é a data de execução das previsões "
        "individuais. A versão da tarefa individual ausente permanece nula, com diagnóstico. Origem e retomada "
        "mantêm commits e execuções separados; não se atribui execução individual não registrada.\n\n"
        "O cronograma CAD Trust descreve cinco períodos plurianuais até o ano25, obtidos dos cinco marcos P50 "
        "publicados. Não há previsão anual interpolada. Acumulados fracionários originais são preservados; "
        "unitCount usa diferenças de acumulados arredondados (meia unidade para cima).\n\n"
        "Campos ausentes, valores não finitos, cruzamentos e duplicações são diagnosticados; as fontes permanecem "
        "intactas. Nenhum imóvel é excluído por tamanho. Produtos completos e localização por CAR são privados. "
        "Titularidade, consentimento, salvaguardas e certificação continuam pendentes. Não há créditos emitidos.\n",
        encoding="utf-8",
    )
    arquivos[cartao.name] = cartao
    catalogo = {
        "perfil": VERSAO,
        "namespace": ns,
        "escopo": "privado",
        "manifesto": {
            "nome": nome,
            "url": base_url + nome,
            "sha256": digest,
            "bytes": Path(manifesto_path).stat().st_size,
        },
        "pacotes": {
            tipo: {k: ref[k] for k in ("nome", "sha256", "bytes", "asset_id")}
            for tipo, ref in manifesto["arquivos"].items()
        },
        "proveniencia_execucoes": proveniencia(manifesto),
        "data_montagem_declarada": data_declarada(manifesto).isoformat(),
        "data_inicio_cenario": data_inicio,
        "contagens": resultado["contagens"],
        "arquivos": {
            n: {"url": base_url + n, "sha256": sha256(p), "bytes": p.stat().st_size}
            for n, p in sorted(arquivos.items())
        },
    }
    indice = destino / f"{ns}_catalogo.json"
    indice.write_bytes(json_bytes(catalogo))
    arquivos[indice.name] = indice
    return {"arquivos": arquivos, "manifesto": manifesto, "sha256": digest, "catalogo": catalogo}
