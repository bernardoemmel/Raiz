"""Regras determinísticas sobre a leitura da certidão: o modelo lê, o código decide.

- normalizar CNS e número de matrícula para comparar com o motor;
- área em hectares a partir da unidade escrita na certidão;
- ônus ativos (os que nenhum ato posterior cancelou) e ônus graves;
- cadeia de donos (mascarada: só rótulos, tipo e documento mascarado), com as quebras de continuidade;
- situação do documento: ativa, cancelada (encerrada, cancelada ou transportada) ou ilegível.

A versão das regras é o hash deste arquivo e de conferencia.py: mudou a regra, muda a versão gravada.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import asdict, dataclass, field

from raiz.documentos.certidao.esquema import ONUS, TRANSMISSAO

# hectares por unidade. Alqueire varia por região: paulista 2,42; mineiro e goiano 4,84; baiano 9,68; do norte 2,72.
# Tarefa e braça quadrada variam demais de um lugar para outro: a conversão fica para gente confirmar.
HA_POR_UNIDADE = {
    "ha": 1.0,
    "m2": 1e-4,
    "alqueire_paulista": 2.42,
    "alqueire_mineiro": 4.84,
    "alqueire_goiano": 4.84,
    "alqueire_baiano": 9.68,
    "alqueire_do_norte": 2.72,
}

ONUS_GRAVES = {"penhora", "arresto", "sequestro", "indisponibilidade", "acao_judicial", "bloqueio_matricula"}
FECHAM = {"encerramento_matricula", "cancelamento_matricula"}


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower().strip()


def normalizar_cns(cns) -> str | None:
    """'06.842-9' -> '068429'. CNS tem 6 dígitos (5 + verificador); aceita como vier, só com os dígitos."""
    if cns is None or (isinstance(cns, float) and cns != cns):
        return None
    d = re.sub(r"\D", "", str(cns))
    if not d:
        return None
    return d.zfill(6) if len(d) < 6 else d


def normalizar_matricula(num) -> str | None:
    """'Matrícula nº 5.178' -> '5178'; '005178' -> '5178'; '1234-A' -> '1234A'. Número com casa decimal vindo do
    pandas (5178.0, ou o texto '5178.0') também vira '5178'; '5.000' é ponto de milhar e vira '5000'."""
    if num is None or (isinstance(num, float) and num != num):
        return None
    if isinstance(num, float) and num.is_integer():
        num = int(num)
    s = str(num).strip().upper()
    if re.fullmatch(r"\d+\.0", s):  # número que passou por float no pandas ('5178.0'); '5.000' é milhar e fica
        s = s[:-2]
    s = re.sub(r"MATR[IÍ]CULA|N[º°O]\.?|N\.", " ", s)
    s = re.sub(r"[^0-9A-Z]", "", s)
    if not s:
        return None
    m = re.match(r"^0*(\d+)([A-Z]*)$", s)
    return (m.group(1) + m.group(2)) if m else s


def normalizar_ato(numero: str | None) -> str:
    """'R.3', 'R3', 'R-03/5178' -> 'R-3'; 'Av-12' -> 'AV-12'; abertura -> 'ABERTURA'."""
    if not numero:
        return ""
    s = str(numero).strip().upper()
    if "ABERT" in s:
        return "ABERTURA"
    m = re.match(r"^(AV|R)\s*[-.:º°]?\s*0*(\d+)", s)
    return f"{m.group(1)}-{m.group(2)}" if m else s


def area_ha(valor, unidade) -> float | None:
    if valor is None or unidade is None:
        return None
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return None
    f = HA_POR_UNIDADE.get(unidade)
    return round(v * f, 4) if f is not None else None


def _data(s) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


@dataclass
class Derivados:
    area_ha: float | None = None
    area_fonte: str | None = None  # imovel | ultimo_ato | original | nenhuma
    area_precisa_confirmar: bool = False
    situacao_documento: str = "ativa"  # ativa | cancelada | bloqueada | ilegivel | nao_e_certidao
    situacao_motivo: str | None = None
    matricula_destino: str | None = None
    onus_ativos: list[dict] = field(default_factory=list)
    onus_cancelados: int = 0
    onus_graves: bool = False
    cancelamentos_sem_alvo: list[str] = field(default_factory=list)
    cadeia: list[dict] = field(default_factory=list)
    quebras_cadeia: list[dict] = field(default_factory=list)
    proprietarios_atuais: list[dict] = field(default_factory=list)
    proprietarios_conferem: bool | None = None
    n_transmissoes: int = 0
    georreferenciado: bool | None = None
    contrato_averbado: bool = False
    idade_certidao_dias: int | None = None

    def para_dict(self) -> dict:
        return asdict(self)


def derivar(dados: dict, hoje: dt.date | None = None) -> Derivados:
    hoje = hoje or dt.date.today()
    d = Derivados()
    doc = dados.get("documento") or {}
    mat = dados.get("matricula") or {}
    imv = dados.get("imovel") or {}
    atos = list(dados.get("atos") or [])
    partes = {p.get("rotulo"): p for p in (dados.get("partes") or []) if p.get("rotulo")}

    # --- área atual -------------------------------------------------------------------------------------------------
    a = area_ha(imv.get("area_valor"), imv.get("area_unidade"))
    if a is not None:
        d.area_ha, d.area_fonte = a, "imovel"
    else:
        for ato in reversed(atos):
            a = area_ha(ato.get("area_valor"), ato.get("area_unidade"))
            if a is not None:
                d.area_ha, d.area_fonte = a, "ultimo_ato"
                break
        else:
            a = area_ha(imv.get("area_original_valor"), imv.get("area_original_unidade"))
            d.area_ha, d.area_fonte = a, ("original" if a is not None else "nenhuma")
    unidades = {imv.get("area_unidade"), imv.get("area_original_unidade")} | {x.get("area_unidade") for x in atos}
    d.area_precisa_confirmar = d.area_ha is None or bool(unidades & {"tarefa", "braca_quadrada", "outro"})

    # --- ônus -----------------------------------------------------------------------------------------------------
    canceladores: dict[str, str] = {}
    for ato in atos:
        for alvo in ato.get("cancela") or []:
            canceladores[normalizar_ato(alvo)] = normalizar_ato(ato.get("numero"))
        if ato.get("natureza") == "cancelamento" and not (ato.get("cancela") or []):
            d.cancelamentos_sem_alvo.append(normalizar_ato(ato.get("numero")))
    bloqueada = False
    for ato in atos:
        nat, num = ato.get("natureza"), normalizar_ato(ato.get("numero"))
        if nat == "bloqueio_matricula":
            bloqueada = num not in canceladores
            continue
        if nat == "desbloqueio_matricula":
            bloqueada = False
            continue
        if nat not in ONUS:
            continue
        if num in canceladores:
            d.onus_cancelados += 1
            continue
        credores = [partes.get(r, {}).get("tipo", "desconhecido") for r in ato.get("adquirentes") or []]
        d.onus_ativos.append(
            dict(
                numero=num,
                natureza=nat,
                data=ato.get("data"),
                credor_tipo=credores[0] if credores else None,
                credor_instituicao=next(
                    (
                        partes[r].get("nome_instituicao")
                        for r in ato.get("adquirentes") or []
                        if r in partes and partes[r].get("nome_instituicao")
                    ),
                    None,
                ),
                pagina=ato.get("pagina"),
                resumo=ato.get("resumo"),
            )
        )
        if nat == "arrendamento_ou_contrato":
            d.contrato_averbado = True
    d.onus_graves = bloqueada or any(o["natureza"] in ONUS_GRAVES for o in d.onus_ativos)

    # --- cadeia de donos ------------------------------------------------------------------------------------------
    donos: set[str] | None = None
    for ato in atos:
        nat = ato.get("natureza")
        if nat == "abertura":
            if ato.get("adquirentes"):
                donos = set(ato["adquirentes"])
            continue
        if nat not in TRANSMISSAO:
            continue
        de, para = list(ato.get("transmitentes") or []), list(ato.get("adquirentes") or [])
        num = normalizar_ato(ato.get("numero"))
        elo = dict(
            numero=num,
            natureza=nat,
            data=ato.get("data"),
            de=[_parte_mascarada(partes, r) for r in de],
            para=[_parte_mascarada(partes, r) for r in para],
            fracao_pct=ato.get("fracao_pct"),
            pagina=ato.get("pagina"),
        )
        originaria = nat in {"usucapiao", "desapropriacao", "titulacao_publica", "legitimacao_fundiaria"}
        if donos is not None and de and not originaria and not set(de) <= donos:
            fora = sorted(set(de) - donos)
            d.quebras_cadeia.append(
                dict(
                    numero=num,
                    motivo=f"{', '.join(fora)} transmite sem aparecer antes como dono",
                    pagina=ato.get("pagina"),
                )
            )
        if donos is None or originaria:
            donos = set(para)
        else:
            parcial = ato.get("fracao_pct") is not None and float(ato.get("fracao_pct") or 0) < 99.5
            donos = (donos | set(para)) if parcial else ((donos - set(de)) | set(para))
        d.cadeia.append(elo)
    d.n_transmissoes = len(d.cadeia)
    if donos is not None:
        d.proprietarios_atuais = [_parte_mascarada(partes, r) for r in sorted(donos)]
        declarados = {p.get("rotulo") for p in dados.get("proprietarios_atuais") or []}
        d.proprietarios_conferem = (declarados == donos) if declarados else None
    else:
        d.proprietarios_atuais = [
            _parte_mascarada(partes, p.get("rotulo")) for p in dados.get("proprietarios_atuais") or []
        ]

    # --- georreferenciamento e contrato -------------------------------------------------------------------------
    geo_ato = any(a.get("natureza") == "georreferenciamento" for a in atos)
    d.georreferenciado = True if (geo_ato or imv.get("georreferenciado")) else imv.get("georreferenciado")

    # --- situação do documento ----------------------------------------------------------------------------------
    sit = mat.get("situacao_declarada")
    fecha = next((a for a in atos if a.get("natureza") in FECHAM), None)
    d.matricula_destino = mat.get("matricula_destino") or (fecha or {}).get("matricula_destino")
    if doc.get("tipo_documento") == "nao_e_certidao":
        d.situacao_documento, d.situacao_motivo = "nao_e_certidao", "o arquivo não é certidão de registro de imóveis"
    elif doc.get("legivel") is False and not atos:
        d.situacao_documento, d.situacao_motivo = "ilegivel", "a certidão não deu para ler"
    elif fecha is not None or sit in {"encerrada", "cancelada", "transportada"}:
        d.situacao_documento = "cancelada"
        quando = f" em {fecha.get('data')}" if fecha and fecha.get("data") else ""
        destino = f"; o imóvel passou para a matrícula {d.matricula_destino}" if d.matricula_destino else ""
        ato = f" ({normalizar_ato(fecha.get('numero'))})" if fecha else ""
        d.situacao_motivo = (
            f"matrícula {sit if sit in {'encerrada', 'cancelada', 'transportada'} else 'encerrada'}"
            f"{ato}{quando}{destino}"
        )
    elif bloqueada or sit == "bloqueada":
        d.situacao_documento, d.situacao_motivo = "bloqueada", "matrícula bloqueada"
        d.onus_graves = True

    em = _data(doc.get("data_emissao"))
    d.idade_certidao_dias = (hoje - em).days if em else None
    return d


def _parte_mascarada(partes: dict, rotulo: str | None) -> dict:
    p = partes.get(rotulo) or {}
    return dict(
        rotulo=rotulo,
        tipo=p.get("tipo", "desconhecido"),
        documento=p.get("documento"),
        instituicao=p.get("nome_instituicao"),
    )


def mesmo_municipio(a: str | None, b: str | None) -> bool | None:
    if not a or not b:
        return None
    return _sem_acento(a) == _sem_acento(b)
