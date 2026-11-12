"""Folha de 3 páginas para o dono do imóvel, em português simples.

Página 1: o que a Raíz viu (áreas) e o que pode render (faixa P10 a P90, com a regra escrita).
Página 2: situação da terra (selo da matrícula), pontos de atenção e documentos que vão ser pedidos.
Página 3: próximos passos, direito de dizer não, dados pessoais, contato e glossário.

Sem nome nem CPF: a folha usa só o código do CAR e dados públicos. As listas têm teto para caber sempre em 3 páginas.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from raiz.documentos import __version__, config
from raiz.documentos.gerados import faixas as FX
from raiz.documentos.gerados.conversao import pasta_gerados, renderizar
from raiz.documentos.gerados.dados import data_dos_dados, fmt_data, fmt_moeda, fmt_num, linha_imovel, num, porte
from raiz.documentos.gerados.dados import verdadeiro as V

MAX_ATENCOES = 5
MAX_DOCUMENTOS = 7

FONTES = (
    "Cadastro Ambiental Rural (SICAR/SFB), desmatamento do PRODES (INPE), MapBiomas, cadastro de imóveis do "
    "INCRA (SIGEF), embargos do Ibama, terras indígenas (FUNAI) e unidades de conservação (CNUC)"
)

GLOSSARIO = [
    dict(termo="CAR", texto="Cadastro Ambiental Rural, o cadastro do imóvel no governo, feito pelo próprio dono."),
    dict(termo="Reserva legal", texto="parte do imóvel que a lei manda manter com mata (na Amazônia, em geral 80%)."),
    dict(termo="APP", texto="beira de rio, nascente e encosta, que a lei manda proteger."),
    dict(termo="Crédito de carbono", texto="pagamento pela mata que cresce e tira gás carbônico do ar."),
    dict(termo="Faixa", texto="de cada 10 resultados possíveis, 8 ficam entre o menor e o maior número mostrado."),
]


def _numeros(li: dict) -> list[dict]:
    linhas = [
        ("Área do imóvel", num(li, "ha", "area"), "tamanho do desenho do imóvel no CAR"),
        (
            "Mata em pé",
            num(li, "comp_mata_em_pe_ha", "floresta_rem_ha", "mb_floresta_2025_ha"),
            "floresta que continua de pé",
        ),
        ("Pasto", num(li, "comp_pasto_ha", "pasto_ha", "mb_pasto_2025_ha"), "área de pasto vista pelo MapBiomas"),
        (
            "Pode voltar a ser mata",
            num(li, "comp_para_restaurar_ha", "carbono_ha"),
            "pasto perto da mata, fora da reserva legal, onde a mata volta com ajuda",
        ),
    ]
    rl = num(li, "deficit_RL_alem_ha", "deficit_RL_ha")
    if rl and rl > 1:
        linhas.append(("Reserva legal que falta", rl, "parte que a lei pede com mata e hoje está aberta"))
    app = num(li, "app_recompor_ha")
    if app and app > 0.5:
        linhas.append(("Beira de rio a recompor", app, "APP aberta que a lei manda recompor (regra da escadinha)"))
    return [dict(rotulo=r, valor=fmt_num(v, 1), explica=e) for r, v, e in linhas if v is not None]


def _titulo(li: dict) -> tuple[str, str]:
    """Mesmo selo do front (front/compartilhado/titulo.ts), com o que a conferência da certidão disse."""
    sit = li.get("matricula_situacao")
    f_mat = num(li, "f_matricula", padrao=0.0)
    pct = f"{f_mat * 100:.0f}%".replace(".", ",")
    if V(li.get("matricula_conferida")) is True:
        return (
            "Matrícula conferida no cartório",
            "Lemos a certidão da matrícula e ela bate com o cadastro do INCRA (SIGEF): cartório, número e área.",
        )
    if sit == "cancelada":
        return (
            "Matrícula encerrada ou cancelada",
            "A certidão diz que a matrícula foi encerrada. Vamos precisar da matrícula nova do imóvel.",
        )
    if sit in ("divergente", "revisar"):
        motivo = (li.get("matricula_motivo") or "").split(";")[0].strip()
        extra = f" O que vimos: {motivo}." if motivo else ""
        return (
            "Matrícula com algo a acertar",
            f"Lemos a certidão e algo não bate com o cadastro do INCRA.{extra} Vamos conversar sobre isso.",
        )
    if f_mat >= 0.5:
        return (
            "Matrícula a conferir",
            f"O cadastro do INCRA mostra matrícula em {pct} do imóvel. Falta ler a certidão no cartório.",
        )
    if li.get("caminho_terra") == "assentamento" or num(li, "assentamento_ha", padrao=0) > 0.5 * num(
        li, "ha", padrao=1
    ):
        return (
            "Lote de assentamento",
            "O imóvel fica em assentamento do INCRA. Ele pode entrar num projeto junto com os vizinhos, com o INCRA.",
        )
    if f_mat > 0.001:
        return (
            "Matrícula a conferir",
            f"Só {pct} do imóvel tem matrícula no cadastro do INCRA; o resto pode ser posse. Vamos conferir juntos.",
        )
    return (
        "Sem matrícula no cadastro do INCRA",
        "Não achamos matrícula no SIGEF para este imóvel. Pode ser posse; há caminhos para regularizar o título.",
    )


def _atencoes(li: dict) -> list[str]:
    a = []

    def ha(*c):
        return num(li, *c, padrao=0.0) or 0.0

    if ha("embargo_ha") > 1:
        a.append(f"Há embargo do Ibama sobre {fmt_num(ha('embargo_ha'), 1)} ha do imóvel.")
    if ha("desm_pos2020_ha") > 1:
        a.append(f"O satélite viu {fmt_num(ha('desm_pos2020_ha'), 1)} ha de desmatamento depois de 2020.")
    elif ha("desm_pos2008_ha") > 1:
        a.append(f"Houve {fmt_num(ha('desm_pos2008_ha'), 1)} ha de desmatamento depois de julho de 2008.")
    if ha("ti_ha", "ti_funai_ha") > 1:
        a.append(f"Parte do imóvel ({fmt_num(ha('ti_ha', 'ti_funai_ha'), 1)} ha) fica sobre terra indígena.")
    if ha("uc_ha") > 1:
        a.append(f"Parte do imóvel ({fmt_num(ha('uc_ha'), 1)} ha) fica dentro de unidade de conservação.")
    if ha("alerta_pos2020_ha") > 1 and ha("desm_pos2020_ha") <= 1:
        a.append(f"Há alerta de desmatamento do MapBiomas ({fmt_num(ha('alerta_pos2020_ha'), 1)} ha) depois de 2020.")
    if V(li.get("matricula_onus_graves")):
        a.append("A certidão da matrícula mostra penhora, bloqueio ou outra restrição: precisa resolver antes.")
    rl = ha("deficit_RL_alem_ha", "deficit_RL_ha")
    if rl > 1:
        a.append(f"Falta reserva legal ({fmt_num(rl, 1)} ha). A restauração pode ajudar a acertar isso.")
    return a[:MAX_ATENCOES]


def _documentos(li: dict) -> list[str]:
    d = [
        "Recibo do CAR (o código do imóvel está nesta folha)",
        "Certidão de inteiro teor da matrícula, tirada há menos de 30 dias",
        "CCIR, o Certificado de Cadastro de Imóvel Rural, do ano",
        "ITR dos últimos 5 anos",
    ]
    caminho = li.get("caminho_terra")
    if caminho == "posse_em_titulacao" or (num(li, "f_matricula", padrao=0) or 0) < 0.5:
        d.append("Papéis da posse e do pedido de título (INCRA ou órgão de terras do estado)")
    if (num(li, "embargo_ha", padrao=0) or 0) > 1:
        d.append("Termo de embargo e o que já foi feito para resolver")
    if (num(li, "deficit_RL_alem_ha", "deficit_RL_ha", padrao=0) or 0) > 1:
        d.append("Adesão ao Programa de Regularização Ambiental (PRA), se já fez")
    d.append("Documento de quem é dono, só na hora do contrato")
    return d[:MAX_DOCUMENTOS]


def _passos(li: dict) -> list[dict]:
    pequeno = porte(li) == "pequeno"
    grupo = (
        " Imóvel pequeno entra junto com os vizinhos num mesmo projeto: ninguém fica de fora pelo tamanho."
        if pequeno
        else ""
    )
    return [
        dict(n=1, titulo="Conversa", texto="A gente explica esta folha e tira suas dúvidas, sem compromisso."),
        dict(
            n=2,
            titulo="Documentos e visita",
            texto="Se você quiser seguir, conferimos a matrícula no cartório e alguém visita a terra para medir.",
        ),
        dict(
            n=3,
            titulo="Proposta por escrito",
            texto="Você recebe a proposta com valores, prazos e o que cabe a cada um." + grupo,
        ),
        dict(
            n=4,
            titulo="Restauração e pagamento",
            texto="A mata volta com acompanhamento; o pagamento segue o que estiver no contrato.",
        ),
    ]


def contexto(
    cod_imovel: str, hoje: dt.date | None = None, cache: dict | None = None, cod_municipio: int | None = None
) -> dict:
    li = linha_imovel(cod_imovel, cache, cod_municipio)
    fx = FX.do_imovel(li)
    rest = num(li, "comp_para_restaurar_ha", "carbono_ha")
    if fx.carbono.vazia:
        tc = "Ainda não temos a conta de carbono deste imóvel."
        tr = "Sem a conta de carbono, não dá para estimar quanto renderia."
    elif (fx.carbono.p90 or fx.carbono.p50 or 0) < 0.5:
        tc = (
            "Hoje a conta não mostra área onde a mata volte com crédito de carbono. Isso acontece, por exemplo, "
            "com embargo, desmatamento recente ou reserva legal faltando. Pode mudar depois de acertar os pontos "
            "da página 2."
        )
        tr = (
            "Outros caminhos, como acertar a reserva legal ou o pasto com árvores, podem fazer sentido: "
            "vamos conversar."
        )
    else:
        onde = (
            f"nos {fmt_num(rest, 1)} ha que podem voltar a ser mata" if rest else "na área que pode voltar a ser mata"
        )
        tc = (
            f"Se a mata voltar {onde}, ela pode tirar do ar entre {fmt_num(fx.carbono.p10)} e "
            f"{fmt_num(fx.carbono.p90)} toneladas de gás carbônico por ano. O mais provável é perto de "
            f"{fmt_num(fx.carbono.p50)}."
        )
        tr = (
            (
                f"Em créditos de carbono, isso daria entre {fmt_moeda(fx.receita.p10, fx.moeda)} e "
                f"{fmt_moeda(fx.receita.p90, fx.moeda)} por ano, antes dos custos da restauração e da parte de "
                "quem faz o projeto."
            )
            if not fx.receita.vazia
            else ""
        )
    titulo_rotulo, titulo_texto = _titulo(li)
    municipio = li.get("municipio") or str(li["cod_municipio"])
    uf = li.get("uf") or config.uf_do_municipio(li["cod_municipio"]) or ""
    return dict(
        data=fmt_data(hoje),
        municipio=f"{municipio} ({uf})" if uf else municipio,
        cod_imovel=cod_imovel,
        frase_visita="Ninguém da Raíz foi até a sua terra ainda: tudo aqui vem de cadastro e satélite.",
        numeros=_numeros(li),
        texto_carbono=tc,
        texto_receita=tr,
        faixas_regra=fx.regra,
        faixas_versao=fx.versao,
        titulo_rotulo=titulo_rotulo,
        titulo_texto=titulo_texto,
        atencoes=_atencoes(li),
        documentos=_documentos(li),
        fontes=FONTES,
        data_dados=(
            f"cadastro do CAR atualizado em {data_dos_dados(li)}"
            if data_dos_dados(li) != "—"
            else "dados públicos lidos pela Raíz"
        ),
        passos=_passos(li),
        contato=config.contato(),
        glossario=GLOSSARIO,
        versao=f"documentos {__version__} · {fx.versao}",
    )


def gerar(
    cod_imovel: str, saida: Path | None = None, hoje: dt.date | None = None, cod_municipio: int | None = None
) -> Path:
    saida = saida or pasta_gerados() / f"folha_dono_{cod_imovel}.docx"
    return renderizar("folha_dono.docx", contexto(cod_imovel, hoje, cod_municipio=cod_municipio), saida)
