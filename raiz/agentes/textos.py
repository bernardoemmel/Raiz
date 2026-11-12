"""Textos das mensagens ao dono: curtos, em português simples, na ordem fonte, fato, fazenda, prazo, o que fazer.
Número no formato brasileiro. Nada promete o que a Raíz ainda não sabe (estimativa é chamada de estimativa).
A E9 troca estes modelos pelos do formato GOV.UK Notify, com medidor de legibilidade antes de cada envio."""

from __future__ import annotations


def num(x: float | None, casas: int = 0) -> str:
    if x is None:
        return "?"
    s = f"{x:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def cod_curto(cod_imovel: str) -> str:
    partes = cod_imovel.split("-")
    return f"{partes[0]}-{partes[1]}-{partes[2][:4]}" if len(partes) >= 3 else cod_imovel


def convite(ficha: dict) -> str:
    area = ficha.get("carbono_ha") or ficha.get("alem_rl_ha")
    return (
        f"Olá! Aqui é a Raíz. Olhamos os dados públicos do Cadastro Ambiental Rural (CAR) do imóvel "
        f"{cod_curto(ficha['cod_imovel'])}, em {ficha.get('municipio', '')} ({ficha.get('uf', '')}).\n\n"
        f"Pela nossa estimativa, cerca de {num(area)} hectares podem voltar a ser mata e gerar pagamento "
        f"por carbono. Quem paga é um investidor. O senhor ou a senhora não paga nada.\n\n"
        f"Quer saber mais? Responda SIM ou NÃO. Se tiver dúvida, pode perguntar."
    )


def proposta(p: dict) -> str:
    return (
        "Esta é a proposta:\n"
        f"- Área: {num(p['area_ha'], 1)} hectares, que ficam para a mata voltar.\n"
        f"- Prazo: {p['prazo_anos']} anos.\n"
        f"- Pagamento: {p['pagamento']}.\n"
        f"- Quem paga: {p.get('quem_paga', 'o investidor')}.\n\n"
        "Para ter certeza de que ficou claro, explique com suas palavras: qual a área, por quanto tempo e "
        "como é o pagamento."
    )


def reexplicar(p: dict, faltou: list[str]) -> str:
    partes = {
        "area": f"a área é de {num(p['area_ha'], 1)} hectares",
        "prazo": f"o prazo é de {p['prazo_anos']} anos",
        "pagamento": f"o pagamento é {p['pagamento']}",
    }
    itens = "; ".join(partes[f] for f in faltou if f in partes)
    return f"Só para reforçar: {itens}. Pode explicar de novo com suas palavras?"


def pedir_codigo(codigo: str) -> str:
    return (
        f"Obrigado. Se o senhor ou a senhora concorda com a proposta, responda com este código: {codigo}\n"
        "Se não concordar, é só responder NÃO."
    )


def codigo_errado() -> str:
    return "O código não confere. Pode conferir e mandar de novo?"


def aceito() -> str:
    return "Pronto, seu aceite foi registrado. A Raíz vai entrar em contato com os próximos passos."


def pedido_sede() -> str:
    """Pede a localização da sede (E5 passo 6). Vai com o botão "Enviar localização" do WhatsApp."""
    return (
        "Mais um pedido. Quando estiver na sede da fazenda, toque no botão abaixo e mande a sua localização. "
        "Assim a Raíz confere se a terra é a mesma do mapa. Guardamos só se o ponto cai dentro da fazenda. "
        "O ponto em si não fica guardado."
    )


def recusado() -> str:
    return "Tudo bem, obrigado pela resposta. Se mudar de ideia, é só escrever para este número."


def duvida_recebida() -> str:
    return "Recebemos sua pergunta. Alguém da Raíz vai responder em breve."


def em_analise() -> str:
    return "Obrigado. Vamos olhar com cuidado e voltamos a falar em breve."


def exemplos() -> dict[str, str]:
    """Cada modelo preenchido com um imóvel e uma proposta de exemplo (sem pessoa real), para medir a legibilidade
    (`raiz legibilidade modelos`)."""
    ficha = {"cod_imovel": "PA-1500107-0000EXEMPLO", "municipio": "Abaetetuba", "uf": "PA", "carbono_ha": 12.4}
    p = {"area_ha": 12.5, "prazo_anos": 30, "pagamento": "R$ 300 por hectare por ano, todo mês de março"}
    return {
        "convite": convite(ficha),
        "proposta": proposta(p),
        "reexplicacao": reexplicar(p, ["area", "pagamento"]),
        "codigo": pedir_codigo("4821"),
        "codigo_errado": codigo_errado(),
        "aceito": aceito(),
        "pedido_sede": pedido_sede(),
        "recusa": recusado(),
        "duvida": duvida_recebida(),
        "em_analise": em_analise(),
    }
