"""CNIB e SAEC no fluxo de certidões, só com autorização do dono (LGPD).

- **CNIB** (Central Nacional de Indisponibilidade de Bens, Provimento CNJ 39/2014, hoje no Código Nacional de Normas
  do Foro Extrajudicial): diz se há ordem de indisponibilidade contra o documento do proprietário. A consulta é por
  CPF ou CNPJ, então só acontece com autorização escrita do dono para o escopo "cnib".
- **SAEC** (Serviço de Atendimento Eletrônico Compartilhado do ONR): pede a certidão de inteiro teor da matrícula
  (até 30 dias, a que o fluxo de títulos lê) pelo cartório (CNS) e pelo número da matrícula. Não precisa de documento
  pessoal, mas custa e expõe a matrícula: também só com autorização para o escopo "saec".

O acesso automático às duas depende do convênio com o ONR (pedido em docs/pedidos/onr-convenio.md). Até a
documentação técnica chegar, o transporte padrão é o manual: devolve a instrução do que pedir e onde, e o checklist
do lote marca "pendente". O transporte do convênio entra implementando `Transporte` (sem mudar o resto).

O documento do dono só existe em memória durante a chamada: não vai para log, resultado, banco ou arquivo. O que fica
é a situação (sem_ordem, com_ordem, pendente...), quantas ordens, a data e o hash do protocolo.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
from dataclasses import dataclass
from typing import Protocol

from raiz.privacidade import cnpj_valido, cpf_valido

ESCOPOS = frozenset({"cnib", "saec"})
MEIOS = frozenset({"assinatura_eletronica", "termo_assinado", "aceite_whatsapp", "aceite_plataforma"})
VALIDADE_DIAS = 90
URL_CNIB_MANUAL = "https://indisponibilidade.onr.org.br"
URL_SAEC_MANUAL = "https://registradores.onr.org.br"
log = logging.getLogger(__name__)


class SemAutorizacao(PermissionError):
    """Sem autorização vigente do dono para este imóvel e escopo: nada é consultado nem pedido."""


@dataclass(frozen=True)
class Autorizacao:
    """Autorização do dono para consultar a CNIB e/ou pedir certidão pelo SAEC de um imóvel.

    `evidencia_sha256` é o hash do termo ou do aceite (o original fica no armazenamento pessoal cifrado), nunca o
    documento. Vale `validade_dias` a partir de `concedida_em` e pode ser revogada."""

    cod_imovel: str
    escopos: frozenset[str]
    concedida_em: dt.date
    meio: str
    evidencia_sha256: str
    validade_dias: int = VALIDADE_DIAS
    revogada_em: dt.date | None = None

    def __post_init__(self):
        if not self.escopos or not set(self.escopos) <= ESCOPOS:
            raise ValueError(f"escopos aceitos: {sorted(ESCOPOS)}")
        if self.meio not in MEIOS:
            raise ValueError(f"meio aceito: {sorted(MEIOS)}")
        if len(self.evidencia_sha256 or "") != 64:
            raise ValueError("evidência da autorização precisa do sha256 do termo ou aceite")

    def vale(self, escopo: str, cod_imovel: str, hoje: dt.date | None = None) -> bool:
        hoje = hoje or dt.date.today()
        if self.revogada_em and self.revogada_em <= hoje:
            return False
        return (
            escopo in self.escopos
            and cod_imovel == self.cod_imovel
            and self.concedida_em <= hoje <= self.concedida_em + dt.timedelta(days=self.validade_dias)
        )


def exigir(aut: Autorizacao | None, escopo: str, cod_imovel: str, hoje: dt.date | None = None) -> None:
    if aut is None or not aut.vale(escopo, cod_imovel, hoje):
        raise SemAutorizacao(f"{escopo}: sem autorização vigente do dono para o imóvel")


def _documento(doc: str) -> str:
    d = "".join(c for c in str(doc).upper() if c.isalnum())
    if not (len(d) == 11 and cpf_valido(d)) and not (len(d) == 14 and cnpj_valido(d)):
        raise ValueError("documento inválido para a CNIB")
    return d


def _hash(protocolo: str | None) -> str | None:
    return hashlib.sha256(protocolo.encode()).hexdigest()[:16] if protocolo else None


@dataclass(frozen=True)
class ResultadoCNIB:
    cod_imovel: str
    situacao: str  # sem_ordem | com_ordem | pendente | sem_autorizacao
    ordens_n: int | None = None
    consultado_em: str | None = None
    protocolo_sha: str | None = None
    instrucao: str | None = None
    fonte: str = "cnib"


@dataclass(frozen=True)
class PedidoSAEC:
    cod_imovel: str
    situacao: str  # pedido | pendente | sem_autorizacao
    cns: str | None = None
    matricula: str | None = None
    pedido_em: str | None = None
    protocolo_sha: str | None = None
    instrucao: str | None = None
    tipo: str = "inteiro_teor"
    fonte: str = "saec"


class Transporte(Protocol):
    """Implementação do convênio ONR. Recebe o documento só em memória; devolve só contagem e protocolo."""

    automatico: bool

    def indisponibilidades(self, documento: str) -> dict:  # {"ordens_n": int, "protocolo": str}
        ...

    def pedir_certidao(self, cns: str, matricula: str, tipo: str) -> dict:  # {"protocolo": str}
        ...


@dataclass
class TransporteManual:
    """Sem convênio: não chama nada. A instrução vai para o checklist de validação humana."""

    automatico: bool = False

    def indisponibilidades(self, documento: str) -> dict:
        raise NotImplementedError

    def pedir_certidao(self, cns: str, matricula: str, tipo: str) -> dict:
        raise NotImplementedError


def transporte_padrao() -> Transporte:
    """O do convênio quando existir (RAIZ_ONR_*); até lá, o manual."""
    return TransporteManual()


def consultar_cnib(
    cod_imovel: str,
    documento: str,
    aut: Autorizacao | None,
    transporte: Transporte | None = None,
    hoje: dt.date | None = None,
) -> ResultadoCNIB:
    """Consulta de indisponibilidade do dono do imóvel. Sem autorização, não consulta (nem valida o documento)."""
    hoje = hoje or dt.date.today()
    try:
        exigir(aut, "cnib", cod_imovel, hoje)
    except SemAutorizacao:
        return ResultadoCNIB(
            cod_imovel, "sem_autorizacao", instrucao="pedir ao dono a autorização para consultar a CNIB (escopo cnib)"
        )
    doc = _documento(documento)
    transporte = transporte or transporte_padrao()
    if not transporte.automatico:
        return ResultadoCNIB(
            cod_imovel,
            "pendente",
            instrucao=(
                f"consultar a CNIB do proprietário em {URL_CNIB_MANUAL} (ou no cartório) com a autorização "
                "registrada; anexar o protocolo"
            ),
        )
    r = transporte.indisponibilidades(doc)
    del doc
    n = int(r.get("ordens_n") or 0)
    log.info("CNIB consultada para %s: %s ordem(ns)", cod_imovel, n)
    return ResultadoCNIB(
        cod_imovel,
        "com_ordem" if n else "sem_ordem",
        ordens_n=n,
        consultado_em=hoje.isoformat(),
        protocolo_sha=_hash(r.get("protocolo")),
    )


def pedir_inteiro_teor(
    cod_imovel: str,
    cns: str | None,
    matricula: str | None,
    aut: Autorizacao | None,
    transporte: Transporte | None = None,
    hoje: dt.date | None = None,
) -> PedidoSAEC:
    """Pedido da certidão de inteiro teor pelo SAEC (cartório + matrícula, vindos do SIGEF ou do dono)."""
    hoje = hoje or dt.date.today()
    try:
        exigir(aut, "saec", cod_imovel, hoje)
    except SemAutorizacao:
        return PedidoSAEC(
            cod_imovel,
            "sem_autorizacao",
            cns,
            matricula,
            instrucao="pedir ao dono a autorização para pedir a certidão (escopo saec)",
        )
    if not cns or not matricula:
        return PedidoSAEC(
            cod_imovel,
            "pendente",
            cns,
            matricula,
            instrucao=("falta cartório (CNS) ou número da matrícula: pedir ao dono ou ler do SIGEF"),
        )
    transporte = transporte or transporte_padrao()
    if not transporte.automatico:
        return PedidoSAEC(
            cod_imovel,
            "pendente",
            cns,
            matricula,
            instrucao=(
                f"pedir certidão de inteiro teor (até 30 dias) da matrícula {matricula} no cartório CNS {cns} em "
                f"{URL_SAEC_MANUAL}; depois enviar o PDF em /documentos/certidoes"
            ),
        )
    r = transporte.pedir_certidao(cns, matricula, "inteiro_teor")
    return PedidoSAEC(
        cod_imovel, "pedido", cns, matricula, pedido_em=hoje.isoformat(), protocolo_sha=_hash(r.get("protocolo"))
    )


def itens_checklist(cnib: ResultadoCNIB | None, saec: PedidoSAEC | None) -> list[dict]:
    """O que entra no checklist de validação humana do imóvel (situação ok, falha ou pendente, como o do lote)."""
    itens = []
    if cnib is None or cnib.situacao in ("sem_autorizacao", "pendente"):
        itens.append(
            {
                "item": "cnib",
                "situacao": "pendente",
                "detalhe": (cnib.instrucao if cnib else "CNIB: pedir autorização do dono e consultar"),
            }
        )
    elif cnib.situacao == "com_ordem":
        itens.append(
            {
                "item": "cnib",
                "situacao": "falha",
                "detalhe": f"{cnib.ordens_n} ordem(ns) de indisponibilidade na CNIB: não contratar até baixar",
            }
        )
    else:
        itens.append({"item": "cnib", "situacao": "ok", "detalhe": f"CNIB sem ordem em {cnib.consultado_em}"})
    if saec is None or saec.situacao in ("sem_autorizacao", "pendente"):
        itens.append(
            {
                "item": "certidao_inteiro_teor",
                "situacao": "pendente",
                "detalhe": (saec.instrucao if saec else "certidão de inteiro teor: pedir autorização e pedir"),
            }
        )
    else:
        itens.append(
            {
                "item": "certidao_inteiro_teor",
                "situacao": "pendente",
                "detalhe": f"certidão pedida pelo SAEC em {saec.pedido_em}; ler quando chegar",
            }
        )
    return itens
