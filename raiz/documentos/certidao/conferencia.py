"""Confere a leitura da certidão com o que o motor achou (certidoes_<mun>.csv: cartório CNS, número da matrícula e
área da parcela SIGEF dentro do CAR, por imóvel).

Resultado por (imóvel, matrícula):
  conferida   a certidão existe, a matrícula está ativa e bate com o SIGEF/motor (cartório, número e área);
  divergente  não bate: outro cartório, outro número, área menor que a parcela SIGEF dentro do CAR, matrícula que o
              motor não conhece para o imóvel, ou matrícula bloqueada;
  cancelada   a matrícula foi encerrada, cancelada ou transportada para outra (a certidão diz);
  revisar     o arquivo não deixa conferir (ilegível ou não é certidão): pedir outra cópia.
Cada motivo tem gravidade: reprova (decide divergente), confirmar (gente precisa olhar, sem mudar a situação) ou info.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from raiz.documentos.certidao import regras
from raiz.documentos.certidao.regras import Derivados, normalizar_cns, normalizar_matricula
from raiz.documentos.formato import fmt_num

VERSAO_BASE = "conferencia-2026a"
TOLERANCIA_AREA = 0.10  # a matrícula pode ter até 10% (e 1 ha) a menos que a parcela SIGEF dentro do CAR
VALIDADE_CERTIDAO_DIAS = 30  # para contrato, a certidão vale 30 dias
TETO_TITULO_PUBLICO_HA = (
    2500  # Constituição, art. 188, § 1º: acima disso a alienação de terra pública exige o Congresso
)
SITUACOES = ("conferida", "divergente", "cancelada", "revisar")


def versao_regras() -> str:
    aqui = Path(__file__).parent
    h = hashlib.sha256()
    for nome in ("regras.py", "conferencia.py"):
        h.update((aqui / nome).read_bytes())
    return f"{VERSAO_BASE}+{h.hexdigest()[:10]}"


@dataclass
class Motivo:
    codigo: str
    gravidade: str  # reprova | confirmar | info
    texto: str


@dataclass
class Conferencia:
    situacao: str
    motivos: list[Motivo] = field(default_factory=list)
    cod_imovel: str | None = None
    registro_cns: str | None = None
    registro_matricula: str | None = None
    motor_arquivo: str | None = None
    motor_ha_sobre_car: float | None = None
    area_matricula_ha: float | None = None

    @property
    def precisa_confirmar(self) -> bool:
        return any(m.gravidade == "confirmar" for m in self.motivos)

    def motivos_dict(self) -> list[dict]:
        return [asdict(m) for m in self.motivos]

    def resumo(self) -> str:
        ordem = {"reprova": 0, "confirmar": 1, "info": 2}
        return "; ".join(m.texto for m in sorted(self.motivos, key=lambda m: ordem[m.gravidade]))


def _f(v) -> float | None:
    try:
        x = float(v)
        return None if x != x else x
    except (TypeError, ValueError):
        return None


def motivos_do_documento(dados: dict, der: Derivados, hoje: dt.date | None = None) -> list[Motivo]:
    hoje = hoje or dt.date.today()
    doc, mat, imv = dados.get("documento") or {}, dados.get("matricula") or {}, dados.get("imovel") or {}
    m: list[Motivo] = []
    if der.situacao_documento in ("nao_e_certidao", "ilegivel"):
        m.append(Motivo(der.situacao_documento, "reprova", der.situacao_motivo or "documento não conferível"))
    if der.situacao_documento == "cancelada":
        m.append(Motivo("matricula_cancelada", "reprova", der.situacao_motivo or "matrícula encerrada"))
    if der.situacao_documento == "bloqueada":
        m.append(Motivo("matricula_bloqueada", "reprova", "matrícula bloqueada no cartório: não pode ser negociada"))
    if doc.get("legivel") is False and der.situacao_documento not in ("ilegivel", "nao_e_certidao"):
        pags = ", ".join(str(p) for p in doc.get("paginas_ilegiveis") or []) or "algumas"
        m.append(Motivo("paginas_ilegiveis", "confirmar", f"páginas que não deram para ler: {pags}"))
    if dados.get("confianca") == "baixa":
        m.append(Motivo("confianca_baixa", "confirmar", "o leitor tem pouca confiança nesta leitura"))
    for q in der.quebras_cadeia:
        m.append(Motivo("quebra_cadeia", "confirmar", f"quebra na cadeia de donos no {q['numero']}: {q['motivo']}"))
    if der.proprietarios_conferem is False:
        m.append(Motivo("donos_atuais", "confirmar", "os donos atuais declarados não batem com a cadeia de atos"))
    for c in der.cancelamentos_sem_alvo:
        m.append(Motivo("cancelamento_sem_alvo", "confirmar", f"{c} cancela algo que o leitor não ligou a um ato"))
    if der.area_precisa_confirmar:
        m.append(
            Motivo(
                "area_unidade",
                "confirmar",
                "área sem unidade conversível com segurança (tarefa, braça ou sem área): conferir",
            )
        )
    graves = [o for o in der.onus_ativos if o["natureza"] in regras.ONUS_GRAVES]
    if graves:
        lista = ", ".join(f"{o['natureza']} ({o['numero']})" for o in graves)
        m.append(Motivo("onus_grave", "confirmar", f"ônus grave ativo: {lista}"))
    elif der.onus_ativos:
        lista = ", ".join(f"{o['natureza']} ({o['numero']})" for o in der.onus_ativos[:5])
        m.append(Motivo("onus_ativo", "info", f"ônus ativo: {lista}"))
    if der.contrato_averbado:
        m.append(
            Motivo(
                "contrato_averbado",
                "confirmar",
                "há contrato averbado na matrícula (arrendamento, carbono ou outro): conferir se ainda vale",
            )
        )
    uf = (imv.get("uf") or (dados.get("cartorio") or {}).get("uf") or "").upper()
    if mat.get("origem") == "desconhecida" and uf == "PA":
        m.append(
            Motivo(
                "origem_para",
                "confirmar",
                "no Pará, matrícula sem origem clara pode ter sido alcançada "
                "pelos Provimentos 13/2006 e 02/2010 da CGJ-PA: conferir a origem",
            )
        )
    if mat.get("origem") == "titulo_publico" and (der.area_ha or 0) > TETO_TITULO_PUBLICO_HA:
        m.append(
            Motivo(
                "titulo_publico_grande",
                "confirmar",
                f"título público de {fmt_num(der.area_ha)} ha (acima de "
                "2.500 ha exige aprovação do Congresso, art. 188 da Constituição): conferir",
            )
        )
    tipo = doc.get("tipo_documento")
    if tipo and tipo not in ("certidao_inteiro_teor", "nao_e_certidao"):
        m.append(Motivo("nao_inteiro_teor", "info", "não é certidão de inteiro teor: a cadeia pode estar incompleta"))
    if der.idade_certidao_dias is not None and der.idade_certidao_dias > VALIDADE_CERTIDAO_DIAS:
        m.append(
            Motivo(
                "certidao_antiga",
                "info",
                f"certidão emitida há {der.idade_certidao_dias} dias: pedir uma nova antes do contrato",
            )
        )
    return m


def _situacao(motivos: list[Motivo]) -> str:
    cod = {x.codigo for x in motivos if x.gravidade == "reprova"}
    if cod & {"nao_e_certidao", "ilegivel"}:
        return "revisar"
    if "matricula_cancelada" in cod:
        return "cancelada"
    if cod:
        return "divergente"
    return "conferida"


def conferir(
    dados: dict,
    der: Derivados,
    motor: pd.DataFrame | None,
    cod_imovel: str | None = None,
    imoveis: pd.DataFrame | None = None,
    motor_arquivo: str | None = None,
    hoje: dt.date | None = None,
) -> list[Conferencia]:
    """Uma Conferencia por imóvel do CAR em que a matrícula aparece no certidoes_<mun>.csv (ou uma só, sem imóvel,
    quando o motor não conhece a matrícula)."""
    base = motivos_do_documento(dados, der, hoje)
    cns = normalizar_cns((dados.get("cartorio") or {}).get("cns"))
    mat = normalizar_matricula((dados.get("matricula") or {}).get("numero"))

    m = (
        motor.copy()
        if motor is not None
        else pd.DataFrame(columns=["cod_imovel", "registro_cns", "registro_matricula", "ha_sobre_car"])
    )
    for col in ("cod_imovel", "registro_cns", "registro_matricula", "ha_sobre_car"):
        if col not in m.columns:
            m[col] = None
    m["_cns"] = m.registro_cns.map(normalizar_cns)
    m["_mat"] = m.registro_matricula.map(normalizar_matricula)
    if cod_imovel:
        m = m[m.cod_imovel == cod_imovel]

    mesma_mat = m[m._mat == mat] if mat else m.iloc[0:0]
    exatas = mesma_mat[mesma_mat._cns == cns] if cns else mesma_mat
    saida: list[Conferencia] = []

    if len(exatas):
        extra = (
            []
            if cns
            else [
                Motivo(
                    "sem_cns", "confirmar", "a certidão não traz o CNS do cartório: conferido pelo número da matrícula"
                )
            ]
        )
        soma_sigef = sum(_f(x) or 0 for x in exatas.ha_sobre_car)
        for _, r in exatas.iterrows():
            mot = base + extra + _motivos_area(der, soma_sigef, r) + _motivos_imovel(dados, der, r, imoveis)
            saida.append(_conf(mot, r, der, motor_arquivo))
        return saida

    if len(mesma_mat):  # mesmo número, outro cartório
        for _, r in mesma_mat.iterrows():
            lido = (dados.get("cartorio") or {}).get("cns") or cns
            texto = f"cartório diferente: a certidão é do CNS {lido}, o SIGEF aponta {r.registro_cns}"
            saida.append(_conf(base + [Motivo("cns_diferente", "reprova", texto)], r, der, motor_arquivo))
        return saida

    if cod_imovel:
        esperadas = sorted({str(x) for x in m.registro_matricula.dropna()})
        txt = (
            f"a matrícula {mat} não é a que o SIGEF aponta para este imóvel ({', '.join(esperadas)})"
            if esperadas
            else "o motor não tem matrícula SIGEF para este imóvel"
        )
        c = Conferencia(
            _situacao(base + [Motivo("matricula_diferente", "reprova", txt)]),
            base + [Motivo("matricula_diferente", "reprova", txt)],
            cod_imovel=cod_imovel,
            registro_cns=(dados.get("cartorio") or {}).get("cns"),
            registro_matricula=mat,
            motor_arquivo=motor_arquivo,
            area_matricula_ha=der.area_ha,
        )
        return [c]

    txt = "matrícula não aparece no certidoes_<mun>.csv do motor (SIGEF não liga esta matrícula a imóvel do CAR)"
    mot = base + [Motivo("fora_do_motor", "reprova", txt)]
    return [
        Conferencia(
            _situacao(mot),
            mot,
            registro_cns=(dados.get("cartorio") or {}).get("cns"),
            registro_matricula=mat,
            motor_arquivo=motor_arquivo,
            area_matricula_ha=der.area_ha,
        )
    ]


def _motivos_area(der: Derivados, soma_sigef: float, r) -> list[Motivo]:
    sigef = _f(r.ha_sobre_car)
    if der.area_ha is None or not soma_sigef:
        return []
    if der.area_ha < soma_sigef * (1 - TOLERANCIA_AREA) - 1:
        return [
            Motivo(
                "area_menor",
                "reprova",
                f"a matrícula tem {fmt_num(der.area_ha, 1)} ha, menos que os {fmt_num(soma_sigef, 1)} ha "
                "da parcela SIGEF dentro do CAR",
            )
        ]
    if sigef and der.area_ha > 3 * soma_sigef:
        return [
            Motivo(
                "area_maior",
                "info",
                f"a matrícula ({fmt_num(der.area_ha, 1)} ha) é bem maior que a parte "
                f"dentro deste CAR ({fmt_num(soma_sigef, 1)} ha): o imóvel da matrícula pode ter outros CAR",
            )
        ]
    return []


def _motivos_imovel(dados: dict, der: Derivados, r, imoveis: pd.DataFrame | None) -> list[Motivo]:
    out: list[Motivo] = []
    if der.georreferenciado is not True:
        out.append(
            Motivo(
                "sem_georreferenciamento",
                "confirmar",
                "a parcela está certificada no SIGEF, mas a averbação do georreferenciamento não aparece na certidão",
            )
        )
    if imoveis is None or "cod_imovel" not in imoveis.columns:
        return out
    linha = imoveis[imoveis.cod_imovel == r.cod_imovel]
    if linha.empty:
        return out
    li = linha.iloc[0]
    mun_cert = (dados.get("imovel") or {}).get("municipio")
    if "municipio" in li and regras.mesmo_municipio(mun_cert, li.get("municipio")) is False:
        out.append(
            Motivo(
                "municipio_diferente",
                "confirmar",
                f"a certidão situa o imóvel em {mun_cert}; o CAR, em "
                f"{li.get('municipio')} (pode ser município antigo, antes de desmembrar)",
            )
        )
    car = (dados.get("imovel") or {}).get("car")
    if car and str(car).replace(".", "").upper() != str(r.cod_imovel).replace(".", "").upper():
        out.append(Motivo("car_diferente", "confirmar", "a certidão cita outro código do CAR"))
    return out


def _conf(motivos: list[Motivo], r, der: Derivados, motor_arquivo: str | None) -> Conferencia:
    return Conferencia(
        situacao=_situacao(motivos),
        motivos=motivos,
        cod_imovel=r.cod_imovel,
        registro_cns=r.registro_cns,
        registro_matricula=None if pd.isna(r.registro_matricula) else str(r.registro_matricula),
        motor_arquivo=motor_arquivo,
        motor_ha_sobre_car=_f(r.ha_sobre_car),
        area_matricula_ha=der.area_ha,
    )
