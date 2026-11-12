"""Aprendizado dos documentos (E8): cada leitura fica gravada com a versão do modelo; quando a certidão real (conferida
por gente, pelo ONR ou no cartório) confirma ou desmente, isso vira gabarito e o placar mostra o acerto por modelo e
versão do prompt.

Duas previsões aprendem com a mesma certidão:
  leitor_certidao  a leitura do modelo (situação da matrícula e campos: área, CNS, número, ônus ativos, cadeia).
                   Gabarito: a marcação de gente sobre a certidão real.
  motor_sigef      o motor previu que a matrícula do SIGEF vale para o imóvel (certidoes_<mun>.csv). Gabarito: a
                   situação conferida, só de leitura confirmada por gente ou feita por gente (modelo "humano").

exportar() grava as duas no formato das tabelas aprendizado.previsao e aprendizado.gabarito do back-end (E8);
enviar_ao_banco() registra direto quando o pacote do back-end (raiz.aprendizado) está instalado.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

from raiz.documentos.armazem import Armazem
from raiz.documentos.certidao.conferencia import SITUACOES
from raiz.documentos.certidao.regras import normalizar_cns, normalizar_matricula

# campos que gente pode conferir na certidão real, e como achar o valor lido
CAMPOS = {
    "area_ha": lambda lt: (lt.derivados or {}).get("area_ha"),
    "cns": lambda lt: normalizar_cns((lt.dados.get("cartorio") or {}).get("cns")),
    "matricula": lambda lt: normalizar_matricula((lt.dados.get("matricula") or {}).get("numero")),
    "onus_ativos": lambda lt: len((lt.derivados or {}).get("onus_ativos") or []),
    "onus_graves": lambda lt: bool((lt.derivados or {}).get("onus_graves")),
    "n_transmissoes": lambda lt: (lt.derivados or {}).get("n_transmissoes"),
    "quebra_cadeia": lambda lt: bool((lt.derivados or {}).get("quebras_cadeia")),
    "situacao_documento": lambda lt: lt.situacao_documento,
}
NORMALIZA = {"cns": normalizar_cns, "matricula": normalizar_matricula}
ALVO_LEITOR = "titulo_matricula_situacao"
ALVO_MOTOR = "motor_matricula_valida"


def _igual(campo: str, lido, real: str) -> bool:
    if campo in NORMALIZA:
        return NORMALIZA[campo](real) == lido
    if isinstance(lido, bool):
        return str(real).strip().lower() in (("true", "1", "sim") if lido else ("false", "0", "nao", "não"))
    if isinstance(lido, int | float):
        try:
            r = float(str(real).replace(",", "."))
        except ValueError:
            return False
        return abs(r - float(lido)) <= max(0.01 * abs(r), 0.5)
    return str(lido) == str(real)


def situacao_prevista(armazem: Armazem, leitura_id: int) -> str | None:
    """A situação que a leitura deu (a pior entre os imóveis da última conferência)."""
    sits = [c["situacao"] for c in armazem.conferencias_por_leitura(leitura_id)]
    return next((s for s in ("revisar", "cancelada", "divergente", "conferida") if s in sits), None)


def marcar(
    leitura_id: int,
    *,
    fonte: str,
    confirma: bool | None = None,
    situacao_real: str | None = None,
    campos: dict[str, str] | None = None,
    observado_em: str | None = None,
    nota: str | None = None,
    armazem: Armazem | None = None,
) -> dict:
    """Marca a leitura como confirmada ou desmentida pela certidão real. Devolve o que foi gravado.

    confirma=True: a situação lida é a real. situacao_real: a situação certa (confirma se for igual à lida).
    campos: valores reais conferidos, ex. {"area_ha": "290", "onus_ativos": "0"}."""
    armazem = armazem or Armazem()
    lt = armazem.leitura(leitura_id)
    if lt is None:
        raise ValueError(f"leitura {leitura_id} não existe")
    if situacao_real is not None and situacao_real not in SITUACOES:
        raise ValueError(f"situação deve ser uma de {', '.join(SITUACOES)}")
    if confirma is None and situacao_real is None and not campos:
        raise ValueError("diga se confirma, a situação real ou os campos conferidos")
    gravado = {}
    prevista = situacao_prevista(armazem, leitura_id)
    if confirma is not None or situacao_real is not None:
        real = situacao_real or (prevista if confirma else None)
        if real is None:
            raise ValueError("desmentir pede a situação real (--real)")
        ok = (real == prevista) if prevista else None
        armazem.gravar_gabarito(
            lt.chave,
            "situacao",
            fonte,
            valor_real=real,
            confirma=ok,
            leitura_id=leitura_id,
            observado_em=observado_em,
            nota=nota,
        )
        gravado["situacao"] = dict(lida=prevista, real=real, confirma=ok)
    for campo, real in (campos or {}).items():
        if campo not in CAMPOS:
            raise ValueError(f"campo desconhecido: {campo} (use {', '.join(CAMPOS)})")
        lido = CAMPOS[campo](lt)
        ok = _igual(campo, lido, real)
        armazem.gravar_gabarito(
            lt.chave,
            f"campo:{campo}",
            fonte,
            valor_real=str(real),
            confirma=ok,
            leitura_id=leitura_id,
            observado_em=observado_em,
            nota=nota,
        )
        gravado[campo] = dict(lido=lido, real=real, confirma=ok)
    return gravado


def fila_revisao(armazem: Armazem | None = None, limite: int = 50) -> list[dict]:
    """Leituras de certidão sem gabarito, as mais importantes primeiro: situação ruim, pedido de confirmação,
    confiança baixa, mais antigas."""
    armazem = armazem or Armazem()
    com_gab = {g["leitura_id"] for g in armazem.gabaritos()}
    confs = defaultdict(list)
    for c in armazem.conferencias_por_leitura():
        confs[c["leitura_id"]].append(c)
    peso = {"revisar": 0, "cancelada": 1, "divergente": 2, "conferida": 4}
    fila = []
    for lt in armazem.leituras(tipo="certidao"):
        if lt.id in com_gab or lt.erro or lt.modelo == "humano":
            continue
        cs = confs.get(lt.id, [])
        sit = next(
            (s for s in ("revisar", "cancelada", "divergente", "conferida") if s in {c["situacao"] for c in cs}), None
        )
        confirmar = any(c["precisa_confirmar"] for c in cs)
        prioridade = peso.get(sit, 3) - (1 if confirmar else 0) - (1 if lt.confianca == "baixa" else 0)
        fila.append(
            dict(
                leitura_id=lt.id,
                chave=lt.chave,
                situacao=sit,
                precisa_confirmar=confirmar,
                confianca=lt.confianca,
                imoveis=sorted({c["cod_imovel"] for c in cs if c["cod_imovel"]}),
                lido_em=lt.lido_em,
                modelo=lt.modelo,
                _p=prioridade,
            )
        )
    fila.sort(key=lambda x: (x["_p"], x["lido_em"]))
    return [{k: v for k, v in f.items() if k != "_p"} for f in fila[:limite]]


def placar(armazem: Armazem | None = None) -> list[dict]:
    """Acerto por modelo e versão do prompt: situação e cada campo conferido, com custo médio por leitura."""
    armazem = armazem or Armazem()
    gabs = defaultdict(dict)
    for g in armazem.gabaritos():
        if g["leitura_id"] is not None:
            gabs[g["leitura_id"]][g["alvo"]] = g
    grupos = defaultdict(list)
    for lt in armazem.leituras(tipo="certidao"):
        grupos[(lt.modelo or lt.modelo_pedido, lt.prompt_versao)].append(lt)
    out = []
    for (modelo, versao), lts in sorted(grupos.items()):
        acertos = defaultdict(lambda: [0, 0])
        for lt in lts:
            for alvo, g in gabs.get(lt.id, {}).items():
                if g["confirma"] is not None:
                    acertos[alvo][0] += int(g["confirma"])
                    acertos[alvo][1] += 1
        custos = [lt.custo_usd for lt in lts if lt.custo_usd is not None]
        out.append(
            dict(
                modelo=modelo,
                prompt_versao=versao,
                leituras=len(lts),
                com_erro=sum(1 for lt in lts if lt.erro),
                com_gabarito=sum(1 for lt in lts if lt.id in gabs),
                acerto=(
                    {alvo: dict(certos=c, total=t, taxa=round(c / t, 3)) for alvo, (c, t) in sorted(acertos.items())}
                ),
                custo_medio_usd=round(sum(custos) / len(custos), 4) if custos else None,
            )
        )
    return out


# --- exportação para a E8 -------------------------------------------------------------------------------------------

COLS_PREVISAO = [
    "tipo",
    "cod_imovel",
    "alvo",
    "valor_num",
    "valor_texto",
    "p10",
    "p50",
    "p90",
    "data_corte",
    "horizonte_dias",
    "modelo",
    "modelo_versao",
    "entradas_versao",
    "regras_versao",
    "receita_hash",
    "referencia",
]
COLS_GABARITO = [
    "cod_imovel",
    "alvo",
    "valor_num",
    "valor_texto",
    "observado_em",
    "fonte",
    "referencia",
    "desenho_amostral",
]


def previsoes_e_gabaritos(armazem: Armazem | None = None) -> tuple[list[dict], list[dict]]:
    armazem = armazem or Armazem()
    gab_sit = {g["leitura_id"]: g for g in armazem.gabaritos() if g["alvo"] == "situacao"}
    prevs, gabs = [], []
    for c in armazem.conferencias_por_leitura():
        if not c["cod_imovel"]:
            continue
        lt = armazem.leitura(c["leitura_id"])
        corte = (lt.lido_em or "")[:10]
        ref = f"leitura:{lt.id}"
        prevs.append(
            dict(
                tipo="ao_vivo",
                cod_imovel=c["cod_imovel"],
                alvo=ALVO_LEITOR,
                valor_texto=c["situacao"],
                data_corte=corte,
                horizonte_dias=0,
                modelo="leitor_certidao",
                modelo_versao=f"{lt.modelo}|{lt.prompt_versao}",
                entradas_versao=lt.arquivo_sha256[:16],
                regras_versao=c["regras_versao"],
                referencia=ref,
            )
        )
        motor = Path(c["motor_arquivo"]).name if c["motor_arquivo"] else "motor"
        prevs.append(
            dict(
                tipo="ao_vivo",
                cod_imovel=c["cod_imovel"],
                alvo=ALVO_MOTOR,
                valor_texto="sim",
                data_corte=corte,
                horizonte_dias=0,
                modelo="motor_sigef",
                modelo_versao=motor,
                entradas_versao=f"{c['registro_cns']}|{c['registro_matricula']}",
                referencia=ref,
            )
        )
        g = gab_sit.get(lt.id)
        if g is not None:
            gabs.append(
                dict(
                    cod_imovel=c["cod_imovel"],
                    alvo=ALVO_LEITOR,
                    valor_texto=g["valor_real"],
                    observado_em=g["observado_em"],
                    fonte=g["fonte"],
                    referencia=ref,
                    desenho_amostral="oportunidade",
                )
            )
        real = g["valor_real"] if g is not None else (c["situacao"] if lt.modelo == "humano" else None)
        if real is not None:
            gabs.append(
                dict(
                    cod_imovel=c["cod_imovel"],
                    alvo=ALVO_MOTOR,
                    valor_texto="sim" if real == "conferida" else "nao",
                    observado_em=(g or {}).get("observado_em") or corte,
                    fonte=(g or {}).get("fonte") or "leitura_humana",
                    referencia=ref,
                    desenho_amostral="oportunidade",
                )
            )
    return prevs, gabs


def exportar(pasta: Path, armazem: Armazem | None = None) -> tuple[Path, Path]:
    prevs, gabs = previsoes_e_gabaritos(armazem)
    pasta.mkdir(parents=True, exist_ok=True)
    a, b = pasta / "previsoes_documentos.csv", pasta / "gabaritos_documentos.csv"
    for caminho, linhas, cols in ((a, prevs, COLS_PREVISAO), (b, gabs, COLS_GABARITO)):
        with caminho.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(linhas)
    return a, b


def enviar_ao_banco(armazem: Armazem | None = None) -> str:
    """Registra no banco do back-end (aprendizado.previsao e aprendizado.gabarito), quando o pacote existe."""
    try:
        from raiz.aprendizado.registro import Previsao, Versoes, registrar_gabarito, registrar_lote  # type: ignore
        from raiz.banco import engine  # type: ignore
    except ImportError as ex:
        raise RuntimeError("o back-end (raiz.aprendizado) não está instalado: use exportar() e carregue os CSV") from ex
    prevs, gabs = previsoes_e_gabaritos(armazem)
    lotes = defaultdict(list)
    for p in prevs:
        lotes[(p["modelo"], p["modelo_versao"], p.get("regras_versao"), p["data_corte"])].append(p)
    n = 0
    with engine().begin() as con:
        for (modelo, versao, regras, corte), ps in lotes.items():
            v = Versoes(modelo, versao, ps[0]["entradas_versao"], dt.date.fromisoformat(corte), regras)
            registrar_lote(
                con,
                [Previsao(p["cod_imovel"], p["alvo"], 0, valor_texto=p["valor_texto"]) for p in ps],
                v,
                descricao="raiz.documentos",
            )
            n += len(ps)
        for g in gabs:
            registrar_gabarito(
                con,
                g["cod_imovel"],
                g["alvo"],
                dt.date.fromisoformat(g["observado_em"][:10]),
                g["fonte"],
                valor_texto=g["valor_texto"],
                referencia=g["referencia"],
            )
    return json.dumps({"previsoes": n, "gabaritos": len(gabs)})
