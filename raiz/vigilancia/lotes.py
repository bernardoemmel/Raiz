"""Lotes de clientes, catálogo privado e rascunhos sem envio.

O pedido salvo identifica o destinatário interno. Um lote não é convertido em projeto Verra: registro,
proponente, causa e perda de carbono continuam a preencher pelo desenvolvedor. Nenhum contato pessoal é lido.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import text

from raiz.vigilancia.armazem import Armazem
from raiz.vigilancia.config import Config
from raiz.vigilancia.fontes import data
from raiz.vigilancia.pedidos import chave_alerta
from raiz.vigilancia.poligonos import uf_mun_do_codigo
from raiz.vigilancia.privacidade import mascarar

ARQUIVO = "lotes-vigilancia.json"
VALIDADE = dt.timedelta(hours=36)
FONTES = frozenset({"deter", "mapbiomas_alerta", "firms"})
CAR = re.compile(r"^[A-Z]{2}-[0-9]{7}-[0-9A-F]{32}$")


class ErroLotes(ValueError):
    """Diagnóstico controlado, sem valor de variável, dado pessoal ou corpo remoto."""


def diagnostico(erro: Exception) -> str:
    if isinstance(erro, ErroLotes):
        return str(erro)
    return f"fonte privada dos lotes indisponível ({type(erro).__name__}); confira banco, acesso e esquema"


@dataclass(frozen=True)
class Lote:
    pedido_id: str
    cliente_id: int
    desde: dt.date
    imoveis: tuple[str, ...]


def _car(valor: str) -> str:
    codigo = str(valor).upper().replace(".", "").strip()
    if not CAR.fullmatch(codigo):
        raise ErroLotes("catálogo de lotes contém código do CAR inválido")
    return codigo


def catalogo_do_banco(engine, agora: dt.datetime | None = None) -> dict:
    """Todos os pedidos não cancelados de clientes ativos; nunca filtra por área ou tamanho da fazenda."""
    agora = agora or dt.datetime.now(dt.UTC)
    with engine.connect() as con:
        linhas = (
            con.execute(
                text("""
            select p.id, p.cliente_id, p.criado_em, p.opcao_escolhida,
                   coalesce(f.itens, '[]'::jsonb) as fazendas, s.opcoes
            from negocio.pedido p join negocio.cliente c on c.id=p.cliente_id and c.ativo
            left join lateral (
                select jsonb_agg(jsonb_build_object('cod_imovel', cod_imovel, 'papel', papel)) as itens
                from negocio.pedido_fazenda where pedido_id=p.id
            ) f on true
            left join lateral (
                select opcoes from negocio.pedido_sugestao where pedido_id=p.id order by id desc limit 1
            ) s on true
            where p.estado <> 'cancelado' order by p.id
        """)
            )
            .mappings()
            .all()
        )
    lotes = []
    for linha in linhas:
        codigos = _codigos(linha["fazendas"], linha["opcoes"], linha["opcao_escolhida"])
        if codigos:
            lotes.append(
                {
                    "pedido_id": str(linha["id"]),
                    "cliente_id": int(linha["cliente_id"]),
                    "desde": linha["criado_em"].date().isoformat(),
                    "imoveis": codigos,
                }
            )
    return {"versao": 1, "gerado_em": agora.isoformat(), "lotes": lotes}


def _codigos(fazendas, opcoes, escolhida):
    itens = fazendas
    # Linhas 'fora' significam edição deliberada; não ressuscitar a sugestão antiga.
    if not itens:
        opcao = next((o for o in opcoes or [] if o.get("id") == (escolhida or "barata")), None)
        itens = (opcao or {}).get("itens") or []
    return sorted({_car(i["cod_imovel"]) for i in itens if i.get("papel") in {"lote", "reserva"}})


def validar_catalogo(catalogo: dict, agora: dt.datetime | None = None) -> list[Lote]:
    agora = agora or dt.datetime.now(dt.UTC)
    if set(catalogo) != {"versao", "gerado_em", "lotes"} or catalogo["versao"] != 1:
        raise ErroLotes("contrato do catálogo de lotes inválido")
    gerado = dt.datetime.fromisoformat(catalogo["gerado_em"])
    if gerado.tzinfo is None or gerado > agora + dt.timedelta(minutes=5) or agora - gerado > VALIDADE:
        raise ErroLotes("catálogo de lotes vencido ou com data inválida; atualize pelo banco")
    saida, vistos = [], set()
    for item in catalogo["lotes"]:
        if set(item) != {"pedido_id", "cliente_id", "desde", "imoveis"}:
            raise ErroLotes("catálogo de lotes contém campo não permitido")
        pedido = str(uuid.UUID(str(item["pedido_id"])))
        cliente = item["cliente_id"]
        if type(cliente) is not int or cliente <= 0 or pedido in vistos:
            raise ErroLotes("dono ou identidade do lote inválidos")
        desde = dt.date.fromisoformat(item["desde"])
        if desde > gerado.date() or not isinstance(item["imoveis"], list):
            raise ErroLotes("data ou lista de imóveis do lote inválida")
        codigos = tuple(sorted({_car(c) for c in item["imoveis"]}))
        saida.append(Lote(pedido, cliente, desde, codigos))
        vistos.add(pedido)
    return saida


def engine_configurado():
    """Não tenta o banco padrão de desenvolvimento quando a configuração de produção está ausente."""
    if not os.environ.get("RAIZ_BANCO_URL"):
        return None
    from raiz.banco import engine

    return engine(os.environ["RAIZ_BANCO_URL"])


def carregar_catalogo(cfg: Config, engine=None, agora: dt.datetime | None = None) -> tuple[list[Lote], dict]:
    """Falha fechada: ausência de banco/snapshot privado nunca amplia a vigilância a todos os imóveis."""
    from raiz.vigilancia.publicacao import Release

    if engine is not None:
        dados = catalogo_do_banco(engine, agora)
        origem = "banco"
    else:
        release = Release(cfg)
        ativos = release.ativos()  # reconfere visibilidade privada antes de ler
        if ARQUIVO not in ativos:
            raise ErroLotes("sem catálogo privado dos lotes: configure RAIZ_BANCO_URL ou exportar-lotes --publicar")
        dados = json.loads(release.baixar(ativos[ARQUIVO]))
        origem = "arquivo_privado"
    return validar_catalogo(dados, agora), {"origem": origem, "gerado_em": dados["gerado_em"]}


def exportar_catalogo(cfg: Config, engine, agora: dt.datetime | None = None) -> dict:
    from raiz.vigilancia.publicacao import Release

    if engine is None:
        raise ErroLotes("defina RAIZ_BANCO_URL para exportar os lotes atuais")
    dados = catalogo_do_banco(engine, agora)
    lotes = validar_catalogo(dados, agora)
    Release(cfg).subir(ARQUIVO, json.dumps(dados, separators=(",", ":")).encode(), "application/json")
    return {
        "lotes": len(lotes),
        "imoveis": len({c for lote in lotes for c in lote.imoveis}),
        "gerado_em": dados["gerado_em"],
        "destino": "arquivo_privado",
    }


def ciclo(cfg: Config, engine) -> dict:
    """Ponte automática servidor→Actions→painel: renova catálogo e importa relatórios a cada 15 minutos."""
    from raiz.vigilancia.publicacao import Release, baixar_estado

    if engine is None:
        raise ErroLotes("defina RAIZ_BANCO_URL para a ponte dos lotes")
    if not cfg.chave:
        raise ErroLotes("defina RAIZ_VIGILANCIA_CHAVE para recuperar os rascunhos privados")
    resultado = exportar_catalogo(cfg, engine)
    arm = Armazem(cfg.estado)
    baixar_estado(arm, Release(cfg), cfg.chave)
    documentos = arm.ler_privado_json("rascunhos_lotes.json", {}) or {}
    resultado["avisos_painel_novos"] = registrar_no_banco(engine, list(documentos.values()))
    resultado["envios_externos"] = 0
    return resultado


class PoligonosLotes:
    """Recorta polígonos e caixas antes de coletar; só cobre CAR processado, nunca extrapola por centroide."""

    def __init__(self, poligonos, lotes: list[Lote]):
        self.original = poligonos
        self.codigos = {c for lote in lotes for c in lote.imoveis}
        self.assinatura = hashlib.sha256("\n".join(sorted(self.codigos)).encode()).hexdigest()[:16]
        self.por_mun: dict[tuple[str, int], set[str]] = {}
        self.geometrias = {}
        self.presentes: set[str] = set()
        ufs = set(poligonos.ufs())
        for codigo in self.codigos:
            uf, mun = uf_mun_do_codigo(codigo)
            if uf in ufs:
                self.por_mun.setdefault((uf, mun), set()).add(codigo)
        for (uf, mun), codigos in self.por_mun.items():
            g = poligonos.imoveis(uf, mun)
            g = g[g.cod_imovel.isin(codigos) & g.geometry.notna() & ~g.geometry.is_empty].copy()
            self.geometrias[uf, mun] = g
            self.presentes.update(g.cod_imovel)

    def ufs(self):
        return sorted({uf for (uf, _), g in self.geometrias.items() if len(g)})

    def versoes(self):
        versoes = self.original.versoes()
        return {uf: f"{versoes[uf]}|lotes:{self.assinatura}" for uf in self.ufs()}

    def indice(self, uf):
        return {mun: list(g.to_crs(4674).total_bounds) for (u, mun), g in self.geometrias.items() if u == uf and len(g)}

    def imoveis(self, uf, mun):
        return self.geometrias[uf, mun].copy()

    def info_imovel(self, codigo):
        return self.original.info_imovel(codigo) if codigo in self.presentes else None

    def geometria_imoveis(self, codigos):
        return self.original.geometria_imoveis(sorted(set(codigos) & self.presentes))


def _link(valor):
    if not isinstance(valor, str):
        return None
    p = urlsplit(valor)
    return mascarar(valor) if p.scheme == "https" and p.hostname and not p.username and not p.password else None


def _numero(valor):
    try:
        import math

        n = float(valor)
        return round(n, 4) if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def rascunho(lote: Lote, alerta: dict, hoje: dt.date) -> dict:
    """Somente campos estruturados, sem nomes, relato livre ou inferência de emissão de créditos."""
    fonte, tipo = str(alerta["fonte"]), str(alerta["tipo"])
    if fonte not in FONTES or tipo not in {"fogo", "desmatamento", "degradacao"}:
        raise ErroLotes("ocorrência fora do escopo da vigilância dos lotes")
    cod = _car(alerta["alvo_id"])
    if cod not in lote.imoveis:
        raise ErroLotes("alerta não pertence às fazendas deste lote")
    data_evento = data(alerta.get("data_evento"))
    data_evento = data_evento.isoformat() if data_evento else None
    chave = f"firms|{cod}|{data_evento}" if fonte == "firms" and data_evento else alerta["alerta_id"]
    identificador = hashlib.sha256(f"{lote.cliente_id}|{lote.pedido_id}|{chave}".encode()).hexdigest()
    numero = None if fonte == "firms" else _numero(alerta.get("area_sobreposta_ha"))
    evento = data_evento or "a conferir pelo desenvolvedor"
    area = f"{numero:.4f} ha" if numero is not None else "a conferir pelo desenvolvedor"
    link = _link(alerta.get("link"))
    texto = (
        f"# Rascunho de ocorrência no lote\n\nPedido: {lote.pedido_id}.\n"
        f"Destinatário interno: desenvolvedor responsável pelo pedido (conta {lote.cliente_id}).\n"
        f"CAR: {cod}.\nFonte: {fonte}; tipo: {tipo}; imagem/evento: {evento}.\n"
        f"Sobreposição geométrica: {area}. Fonte: {link or 'link não informado'}.\n\n"
        "Este alerta de sensoriamento remoto exige conferência e não confirma perda de carbono. "
        "Um foco NOAA-20/21 indica calor no pixel; sua área não é uma medição de área queimada.\n\n"
        "Projeto registrado, proponente, causa, área afetada confirmada, estoque e perda de carbono: "
        "a preencher pelo desenvolvedor. Prazo regulatório: a conferir pelo proponente segundo o padrão "
        "aplicável; não foi inferido a partir do lote.\n\n"
        f"Preparado em {hoje.isoformat()}. Rascunho não enviado. Conferir imagens e evidência de campo "
        "antes de aprovar o relatório.\n"
    )
    return {
        "id": identificador,
        "pedido_id": lote.pedido_id,
        "cliente_id": lote.cliente_id,
        "cod_imovel": cod,
        "alerta_id": str(alerta["alerta_id"]),
        "chave_fato": chave_alerta(alerta),
        "alerta_ids": [str(alerta["alerta_id"])],
        "evidencias": [
            {
                "alerta_id": str(alerta["alerta_id"]),
                "fonte_url": link,
                "sobreposicao_pixel_ha": _numero(alerta.get("area_sobreposta_ha")) if fonte == "firms" else None,
            }
        ],
        "fonte": fonte,
        "tipo": tipo,
        "data_evento": data_evento,
        "area_sobreposta_ha": numero,
        "fonte_url": link,
        "regra_versao": str(alerta.get("regra_versao") or ""),
        "estado": "rascunho_nao_enviado",
        "gerado_em": hoje.isoformat(),
        "relatorio": texto,
    }


def preparar_rascunhos(arm: Armazem, lotes: list[Lote], hoje: dt.date, presentes: set[str]) -> list[dict]:
    from raiz.vigilancia import aprendizado

    alertas = arm.alertas("imovel")
    if not len(alertas):
        return []
    vigentes = aprendizado.vigentes(arm.marcacoes())
    falsos = set(vigentes.loc[~vigentes.verdadeiro.astype(bool), "alerta_id"]) if len(vigentes) else set()
    existentes = arm.ler_privado_json("rascunhos_lotes.json", {}) or {}
    disponiveis = {}
    retirados = []
    for identificador, documento in existentes.items():
        ids = set(documento.get("alerta_ids") or [documento["alerta_id"]])
        if ids and ids <= falsos and documento.get("estado") != "descartado_por_revisao":
            documento = {
                **documento,
                "estado": "descartado_por_revisao",
                "revisado_em": hoje.isoformat(),
                "relatorio": "# Ocorrência descartada por revisão\n\n"
                "Todas as evidências deste rascunho foram marcadas como falso positivo. "
                "Não usar este documento como relatório de perda. Nada foi enviado.\n",
            }
            existentes[identificador] = documento
            retirados.append(documento)
    for lote in lotes:
        candidatos = alertas[alertas.alvo_id.isin(set(lote.imoveis) & presentes)]
        for alerta in candidatos.to_dict("records"):
            if (
                alerta["fonte"] not in FONTES
                or alerta["tipo"] not in {"fogo", "desmatamento", "degradacao"}
                or not bool(alerta["novo"])
                or bool(alerta["borda"])
                or alerta["alerta_id"] in falsos
                or data(alerta["visto_em"]) is None
                or data(alerta["visto_em"]) < lote.desde
            ):
                continue
            d = rascunho(lote, alerta, hoje)
            if d["id"] in disponiveis:
                # NOAA-20/21 no mesmo CAR e dia: uma comunicação com várias evidências, sem somar pixels.
                atual = disponiveis[d["id"]]
                atual["alerta_ids"] = sorted(set(atual["alerta_ids"] + d["alerta_ids"]))
                atual["evidencias"] += d["evidencias"]
            else:
                disponiveis[d["id"]] = d
    for identificador, documento in disponiveis.items():
        antigo = existentes.get(identificador)
        if antigo:
            documento["gerado_em"] = antigo["gerado_em"]
        documento["relatorio"] += (
            f"\nEvidências: {len(documento['alerta_ids'])} registros. "
            "Sobreposições não são somadas como área afetada.\n"
        )
        existentes[identificador] = documento
    arm.gravar_privado_json("rascunhos_lotes.json", existentes)
    return [*disponiveis.values(), *retirados]


def registrar_no_banco(engine, rascunhos: list[dict]) -> int:
    """Trava o pedido e reconfere dono/estado; grava só no painel. Não chama nenhum enviador."""
    from raiz.pedidos.servico import _alerta

    total = 0
    for d in rascunhos:
        with engine.begin() as con:
            p = con.execute(
                text("""select p.id, p.opcao_escolhida from negocio.pedido p
                join negocio.cliente c on c.id=p.cliente_id and c.ativo
                where p.id=:p and p.cliente_id=:c and p.estado <> 'cancelado' for update of p"""),
                {"p": d["pedido_id"], "c": d["cliente_id"]},
            ).first()
            if p is None:
                continue
            fazendas = (
                con.execute(
                    text("select cod_imovel,papel from negocio.pedido_fazenda where pedido_id=:p"),
                    {"p": d["pedido_id"]},
                )
                .mappings()
                .all()
            )
            opcoes = con.execute(
                text("""select opcoes from negocio.pedido_sugestao
                where pedido_id=:p order by id desc limit 1"""),
                {"p": d["pedido_id"]},
            ).scalar_one_or_none()
            if d["cod_imovel"] not in _codigos(fazendas, opcoes, p.opcao_escolhida):
                continue
            if d.get("estado") == "descartado_por_revisao":
                con.execute(
                    text("""update negocio.alerta_pedido
                    set detalhe=jsonb_set(detalhe,'{rascunho_vigilancia}',cast(:d as jsonb))
                    where pedido_id=:p and detalhe->>'chave'=:k"""),
                    {"p": d["pedido_id"], "k": d["chave_fato"], "d": json.dumps(d)},
                )
                continue  # revisão não cria outro alerta nem notificação
            mensagem = f"Alerta {d['fonte']} no CAR {d['cod_imovel']}: rascunho de relatório disponível; nada enviado."
            if _alerta(
                con,
                d["pedido_id"],
                "fazenda_com_problema",
                d["cod_imovel"],
                mensagem,
                {"motivo": d["tipo"], "rascunho_vigilancia": d},
                d["chave_fato"],
            ):
                con.execute(
                    text("""insert into negocio.notificacao
                    (cliente_id,pedido_id,tipo,canal,texto,estado) values
                    (:c,:p,'vigilancia_lote','painel',:t,'na_fila')"""),
                    {"c": d["cliente_id"], "p": d["pedido_id"], "t": mensagem},
                )
                total += 1
            else:
                # Acrescentar confirmação de outro satélite atualiza o rascunho, sem outro aviso.
                con.execute(
                    text("""update negocio.alerta_pedido
                    set detalhe=jsonb_set(detalhe,'{rascunho_vigilancia}',cast(:d as jsonb))
                    where pedido_id=:p and detalhe->>'chave'=:k"""),
                    {"p": d["pedido_id"], "k": d["chave_fato"], "d": json.dumps(d)},
                )
    return total


def relatorios_do_pedido(engine, pedido_id: str, cliente_id: int) -> list[dict]:
    from raiz.pedidos.servico import _linha_pedido

    with engine.connect() as con:
        _linha_pedido(con, pedido_id, cliente_id)
        dados = con.execute(
            text("""select detalhe->'rascunho_vigilancia' from negocio.alerta_pedido
            where pedido_id=:p and detalhe ? 'rascunho_vigilancia' order by id desc"""),
            {"p": pedido_id},
        ).scalars()
        # O cliente é reconferido também dentro do documento congelado, inclusive após correção de titularidade.
        return [d for d in dados if d and d.get("cliente_id") == cliente_id and d.get("pedido_id") == pedido_id]
