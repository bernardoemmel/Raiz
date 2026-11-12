"""Aviso inicial à Verra, separado do relatório de perda. Preparar nunca envia nem quita o prazo."""

from __future__ import annotations

import datetime as dt
from email import policy
from email.message import EmailMessage

from raiz.vigilancia.privacidade import mascarar
from raiz.vigilancia.projetos import Projeto
from raiz.vigilancia.regras import Regras
from raiz.vigilancia.relatorio import FONTES, TIPOS


def preparar(
    projeto: Projeto,
    perda_id: str,
    regras: Regras,
    hoje: dt.date,
    perda: dict | None = None,
    prazo_informado: dt.date | None = None,
) -> dict:
    """Sem o estado privado, aceita só o prazo explicitamente informado pelo operador.

    Nesse caso não deduz descoberta nem inventa a caracterização da perda. As pendências
    acompanham o rascunho; a mensagem só é registrada como enviada por evento separado.
    """
    if perda is None and prazo_informado is None:
        raise ValueError("evento indisponível: restaure o estado privado ou informe o prazo conhecido")
    if not perda_id.startswith(f"{projeto.id}_LE") or not perda_id.removeprefix(f"{projeto.id}_LE").isdigit():
        raise ValueError("evento de perda não é deste projeto")
    if perda and perda["perda_id"] != perda_id:
        raise ValueError("identificador do evento divergente")
    prazo = perda["prazo"]["aviso_verra_ate"] if perda else prazo_informado
    if perda and prazo_informado and prazo != prazo_informado:
        raise ValueError("prazo informado diverge do estado do evento; confira a descoberta antes de preparar")
    pendencias = ["Conferir os fatos e preencher a assinatura e o contato do proponente no cliente de e-mail."]
    registro = projeto.get("verra_id")
    if not registro:
        pendencias.append("Preencher o ID do projeto no registro da Verra.")
    linhas = [
        "Dear Verra Registry Team,",
        "",
        f"This is an initial notification of a potential loss event concerning project {projeto.nome}.",
        f"Verra project ID: {registro or '[to be completed]'}.",
        f"Internal event reference: {perda_id}.",
        "",
    ]
    if perda:
        linhas += [
            f"Discovery date recorded by monitoring: {perda['descoberta_em'].isoformat()}.",
            "Detected signals: " + ", ".join(TIPOS.get(t, (t, t))[1] for t in perda["tipos"]) + ".",
            f"Preliminary affected area within the project carbon area: {perda['area_ha']:.4f} ha.",
            "Monitoring sources: " + "; ".join(FONTES.get(f, (f, f))[1] for f in perda["fontes"]) + ".",
            "Field confirmation, the cause and carbon stock impact remain subject to assessment.",
        ]
        if perda["estado"] in ("descartada", "relatada") or perda["prazo"].get("aviso_verra_feito_em"):
            pendencias.append("Evento encerrado ou aviso já registrado: conferir antes de repetir o envio.")
    else:
        pendencias.append("Restaurar o estado privado do projeto e conferir descoberta, área, fontes e caracterização.")
        linhas += [
            "Discovery date: [to be completed from the event record].",
            "Nature, location and preliminary affected area: [to be completed from the event record].",
            "The detailed monitoring record is being reviewed; this draft does not assert a confirmed reversal.",
        ]
    linhas += [
        "",
        f"The notification deadline recorded for this event is {prazo.isoformat()}.",
        "Please acknowledge receipt and advise on any further information required for the initial notification.",
        "The loss event report, where applicable, will be handled separately under the applicable VCS requirements.",
        "",
        "Kind regards,",
        "[project proponent / authorized representative — complete before sending]",
        "[contact details — complete in the email client]",
    ]
    return {
        "projeto_id": projeto.id,
        "perda_id": perda_id,
        "destinatario": regras.verra["email"],
        "assunto": mascarar(f"Initial notification of potential loss event — {projeto.nome} — {perda_id}"),
        "corpo": mascarar("\n".join(linhas) + "\n"),
        "prazo": prazo.isoformat(),
        "dias_restantes": (prazo - hoje).days,
        "origem_prazo": "estado_do_evento" if perda else "informado_pelo_operador",
        "regra_versao": regras.versao,
        "estado": "rascunho_aguardando_conferencia",
        "enviado": False,
        "pendencias": pendencias,
    }


def eml(aviso: dict) -> str:
    """Arquivo abrível no cliente de e-mail; sem remetente inventado nem envio SMTP."""
    mensagem = EmailMessage(policy=policy.SMTP)
    mensagem["To"] = aviso["destinatario"]
    mensagem["Subject"] = aviso["assunto"]
    mensagem["X-Unsent"] = "1"
    mensagem.set_content(aviso["corpo"])
    return mensagem.as_string()
