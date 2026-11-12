"""Alertas de operação com escalonamento (E7 passo 9): quem opera sozinho precisa saber na hora quando algo parou.

    coletar()   olha o banco e a vigilância e diz o que está errado agora (lote que falhou ou travou, orçamento dos
                modelos, vigilância atrasada ou fonte com erro, prazo da Verra num evento de perda, fila de revisão e
                mensagens paradas, fazenda com problema num grupo pronto ou reservado)
    registrar() abre um alerta por problema (a chave impede abrir dois para o mesmo) e fecha sozinho o que era um
                estado e deixou de ser (o lote destravou, a vigilância voltou a rodar)
    escalar()   alerta que ninguém reconheceu sobe a escada de raiz/regras/padroes/alertas.yaml: ntfy normal, ntfy
                urgente e, havendo segunda pessoa, GoAlert; o último nível se repete até o limite de envios

Envio: ntfy pelo JSON de publicação (RAIZ_NTFY_URL e RAIZ_NTFY_TOPICO; RAIZ_NTFY_TOKEN se o servidor pedir) e GoAlert
pela integração genérica (RAIZ_GOALERT_URL). Sem essas variáveis, o envio é simulado e fica registrado no alerta, com
o mesmo texto que sairia. O Healthchecks continua sendo o alarme de fora do servidor (docs/operacao.md): se o servidor
cair, quem avisa é ele. Nada pessoal: só contagens, códigos e textos mascarados.

Rodar de 15 em 15 minutos: `raiz operacao alertas`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import httpx
import yaml
from sqlalchemy import Connection, Engine, text

from raiz import RAIZ_REPO
from raiz.config import config
from raiz.logs_seguros import sanitizar_estrutura, sanitizar_log

log = logging.getLogger(__name__)

ARQUIVO = RAIZ_REPO / "raiz" / "regras" / "padroes" / "alertas.yaml"
GRAVIDADES = ("aviso", "urgente", "critico")
NOME_TAREFA = {"funil": "funil", "carga": "carga", "coleta": "coleta", "filtros": "filtros", "direto": "direto"}


@lru_cache(maxsize=4)
def _politica(caminho: str, _mtime: int) -> dict:
    bruto = Path(caminho).read_bytes()
    d = yaml.safe_load(bruto)
    d["versao"] = f"{d['nome']}+{hashlib.sha256(bruto).hexdigest()[:8]}"
    return d


def politica(caminho: Path | None = None) -> dict:
    p = Path(caminho or ARQUIVO)
    return _politica(str(p), p.stat().st_mtime_ns)


@dataclass(frozen=True)
class Novo:
    origem: str
    chave: str
    gravidade: str
    titulo: str
    texto: str
    detalhe: dict = field(default_factory=dict)
    continuo: bool = True  # estado (fecha sozinho quando passa) ou fato (fecha quando alguém resolve)


# --------------------------------------------------------------------------- coletar


def _agora() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _lotes(con: Connection, regras: dict, agora: dt.datetime) -> list[Novo]:
    out = []
    jan = agora - dt.timedelta(hours=float(regras["lote_falhou"]["janela_horas"]))
    rs = con.execute(
        text("""select tarefa, count(*) as n, min(cod_municipio) as exemplo, max(iniciado_em) as ultimo
                from operacao.lote where estado = 'falha' and iniciado_em >= :j group by tarefa order by tarefa"""),
        {"j": jan},
    ).all()
    for r in rs:
        out.append(
            Novo(
                "lote_falhou",
                f"lote_falhou:{r.tarefa}:{agora.date().isoformat()}",
                regras["lote_falhou"]["gravidade"],
                f"{r.n} lote(s) de {r.tarefa} falharam",
                f"{r.n} município(s) falharam na tarefa {r.tarefa} nas últimas "
                f"{regras['lote_falhou']['janela_horas']} horas (exemplo: {r.exemplo}). "
                "O fim do log está no backoffice.",
                {"tarefa": r.tarefa, "falhas": int(r.n), "exemplo": r.exemplo},
                continuo=False,
            )
        )
    lim = agora - dt.timedelta(hours=float(regras["lote_travado"]["horas"]))
    rs = con.execute(
        text("""select tarefa, count(*) as n, min(iniciado_em) as desde from operacao.lote
                where estado = 'iniciado' and iniciado_em < :l group by tarefa order by tarefa"""),
        {"l": lim},
    ).all()
    for r in rs:
        out.append(
            Novo(
                "lote_travado",
                f"lote_travado:{r.tarefa}",
                regras["lote_travado"]["gravidade"],
                f"{r.n} lote(s) de {r.tarefa} parados",
                f"{r.n} lote(s) de {r.tarefa} começaram e não terminaram há mais de {regras['lote_travado']['horas']} "
                f"horas (o mais antigo desde {r.desde:%d/%m %H:%M} UTC).",
                {"tarefa": r.tarefa, "parados": int(r.n)},
            )
        )
    return out


def _orcamento(con: Connection, regras: dict, agora: dt.datetime) -> list[Novo]:
    from raiz.operacao.custo import gasto_do_mes

    orc = config().orcamento_mensal_usd
    if not orc:
        return []
    gasto = gasto_do_mes(con, agora.date())
    pct = 100 * gasto / orc
    mes = agora.strftime("%Y-%m")
    r = regras["orcamento"]
    for limite, grav in ((r["urgente_pct"], "urgente"), (r["aviso_pct"], "aviso")):
        if pct >= limite:
            return [
                Novo(
                    "orcamento",
                    f"orcamento:{mes}:{limite}",
                    grav,
                    f"Modelos: {pct:.0f}% do orçamento do mês",
                    f"Gasto com modelos em {mes}: US$ {gasto:.2f} de US$ {orc:.2f} ({pct:.0f}%).",
                    {"gasto_usd": round(gasto, 4), "orcamento_usd": orc, "pct": round(pct, 1)},
                )
            ]
    return []


def _vigilancia(vig, regras: dict, hoje: dt.date) -> list[Novo]:
    out = []
    s = vig.saude(hoje)
    if s.get("dias_desde_a_ultima") is None or s["dias_desde_a_ultima"] > int(regras["vigilancia_atrasada"]["dias"]):
        quando = s.get("ultima_rodada") or "nunca"
        out.append(
            Novo(
                "vigilancia_atrasada",
                "vigilancia_atrasada",
                regras["vigilancia_atrasada"]["gravidade"],
                "Vigilância diária atrasada",
                f"A última rodada da vigilância foi {quando}. Conferir o workflow Vigilância diária no GitHub.",
                {"ultima_rodada": s.get("ultima_rodada")},
            )
        )
    for nome, f in (s.get("fontes") or {}).items():
        if (f or {}).get("situacao") == "erro":
            out.append(
                Novo(
                    "vigilancia_fonte",
                    f"vigilancia_fonte:{nome}",
                    regras["vigilancia_fonte_com_erro"]["gravidade"],
                    f"Vigilância: fonte {nome} com erro",
                    f"A fonte {nome} falhou na última leitura: {sanitizar_log(str(f.get('erro') or ''))[:300]}",
                    {"fonte": nome},
                )
            )
    perdas_vistas = set()
    for pid in vig.projetos:
        for pe in vig.perdas(pid, hoje)[0]:
            perdas_vistas.add(pe["perda_id"])
            if pe["estado"] in ("descartada", "relatada"):
                continue
            pr = pe["prazo"]
            if pr["aviso_verra_situacao"] in ("urgente", "vencido"):
                out.append(
                    Novo(
                        "verra_prazo",
                        f"verra_aviso:{pe['perda_id']}",
                        regras["verra_aviso_urgente"]["gravidade"],
                        f"Verra: avisar a perda {pe['perda_id']} até {pr['aviso_verra_ate']:%d/%m/%Y}",
                        f"Evento de perda {pe['perda_id']} ({pe['estado']}) no projeto {pid}: "
                        "o aviso à Verra por e-mail "
                        f"vence em {pr['aviso_verra_ate']:%d/%m/%Y} ({pr['aviso_verra_dias_restantes']} dias). "
                        f"Rascunho: /vigilancia/projeto/{pid}/perdas/{pe['perda_id']}/aviso-verra. "
                        "O envio cabe ao proponente, nunca à Raíz. Registrar 'verra_avisada' só após confirmação dele.",
                        {"perda_id": pe["perda_id"], "projeto_id": pid, "dias": pr["aviso_verra_dias_restantes"]},
                    )
                )
            if pr["relatorio_situacao"] == "vencido":
                out.append(
                    Novo(
                        "verra_prazo",
                        f"verra_relatorio:{pe['perda_id']}",
                        regras["verra_prazo_vencido"]["gravidade"],
                        f"Verra: relatório da perda {pe['perda_id']} vencido",
                        f"O relatório de perda {pe['perda_id']} venceu em {pr['relatorio_ate']:%d/%m/%Y}; sem ele o "
                        "projeto não emite crédito.",
                        {"perda_id": pe["perda_id"], "projeto_id": pid},
                    )
                )
    for d in getattr(vig, "avisos_verra_informados", lambda _hoje: [])(hoje):
        if d["perda_id"] in perdas_vistas or not d["pode_exportar"] or d["dias_restantes"] > 7:
            continue
        prazo = dt.date.fromisoformat(d["prazo"])
        out.append(
            Novo(
                "verra_prazo",
                f"verra_aviso:{d['perda_id']}",
                regras["verra_aviso_urgente"]["gravidade"],
                f"Verra: prazo do proponente para {d['perda_id']} em {prazo:%d/%m/%Y}",
                f"Rascunho para o desenvolvedor cliente: {d['rascunho']}. "
                f"Prazo informado: {prazo:%d/%m/%Y} ({d['dias_restantes']} dias). "
                "Campos a preencher pelo proponente. A Raíz nunca envia o aviso à Verra.",
                {
                    "perda_id": d["perda_id"],
                    "projeto_id": d["projeto_id"],
                    "dias": d["dias_restantes"],
                    "responsavel_pelo_envio": "proponente",
                },
            )
        )
    return out


def _filas(con: Connection, regras: dict, agora: dt.datetime) -> list[Novo]:
    out = []
    lim = agora - dt.timedelta(hours=float(regras["revisao_parada"]["horas"]))
    n = con.execute(
        text("select count(*) from operacao.fila_revisao where estado = 'aberta' and criado_em < :l"), {"l": lim}
    ).scalar()
    if n:
        out.append(
            Novo(
                "revisao_parada",
                "revisao_parada",
                regras["revisao_parada"]["gravidade"],
                f"{n} revisão(ões) esperando há mais de {regras['revisao_parada']['horas']} horas",
                f"{n} caso(s) na fila de revisão esperam o fundador há mais de "
                f"{regras['revisao_parada']['horas']} horas.",
                {"abertas": int(n)},
            )
        )
    lim = agora - dt.timedelta(hours=float(regras["mensagem_esperando_aprovacao"]["horas"]))
    n = con.execute(
        text("""select count(*) from pessoal.mensagem_saida
                where estado = 'aguardando_aprovacao' and criado_em < :l"""),
        {"l": lim},
    ).scalar()
    if n:
        out.append(
            Novo(
                "mensagens_paradas",
                "mensagens_paradas",
                regras["mensagem_esperando_aprovacao"]["gravidade"],
                f"{n} mensagem(ns) para donos esperando aprovação",
                f"{n} mensagem(ns) para donos esperam aprovação há mais de "
                f"{regras['mensagem_esperando_aprovacao']['horas']} horas.",
                {"aguardando": int(n)},
            )
        )
    return out


def _pedidos(con: Connection, regras: dict, agora: dt.datetime) -> list[Novo]:
    rs = con.execute(
        text("""select a.id, a.pedido_id, a.cod_imovel, a.detalhe->>'motivo' as motivo, p.estado
                from negocio.alerta_pedido a join negocio.pedido p on p.id = a.pedido_id
                where a.tipo = 'fazenda_com_problema' and p.estado in ('grupo_pronto', 'reservado')
                and a.criado_em >= :d"""),
        {"d": agora - dt.timedelta(days=1)},
    ).all()
    return [
        Novo(
            "pedido_problema",
            f"pedido_problema:{r.id}",
            regras["pedido_fazenda_com_problema"]["gravidade"],
            f"Grupo {r.estado.replace('_', ' ')} com fazenda com problema",
            f"Fazenda {r.cod_imovel} do pedido {r.pedido_id} ({r.estado.replace('_', ' ')}): "
            f"{(r.motivo or 'problema').replace('_', ' ')}. O cliente já foi avisado; ver troca ou reserva.",
            {"pedido_id": str(r.pedido_id), "cod_imovel": r.cod_imovel, "motivo": r.motivo},
            continuo=False,
        )
        for r in rs
    ]


def _cascata(con: Connection, regras: dict, agora: dt.datetime) -> list[Novo]:
    """Cascata por confiança (E7 passo 10) subindo fora da faixa calibrada: o corte envelheceu."""
    from raiz.modelos import rota

    r = regras.get("cascata_fora_da_faixa")
    if not r:
        return []
    lo, hi = (rota.politica().get("confianca") or {}).get("faixa_subida", (0.2, 0.3))
    dias, margem = int(r.get("dias", 7)), float(r.get("margem", 0.15))
    rs = con.execute(
        text("""select tarefa, count(*) as n, count(*) filter (where via <> 'confianca') as sobe
                from operacao.decisao_cascata
                where rota = 'local' and corte is not null and criado_em >= :d group by tarefa"""),
        {"d": agora - dt.timedelta(days=dias)},
    ).all()
    out = []
    for x in rs:
        if x.n < int(r.get("minimo", 50)):
            continue
        f = x.sobe / x.n
        if f > hi + margem or f < lo - margem:
            out.append(
                Novo(
                    "cascata_faixa",
                    f"cascata_faixa:{x.tarefa}",
                    r["gravidade"],
                    f"Cascata de {x.tarefa}: {f:.0%} das perguntas subindo de modelo",
                    f"Nos últimos {dias} dias, {x.sobe} de {x.n} perguntas de {x.tarefa} subiram do Qwen para a "
                    f"votação; o corte foi calibrado para {lo:.0%} a {hi:.0%}. O corte pode ter envelhecido "
                    "(modelo, prompt ou mensagens mudaram): rode `raiz modelos calibrar` no servidor.",
                    {"tarefa": x.tarefa, "decisoes": int(x.n), "subiram": int(x.sobe), "fracao": round(f, 4)},
                )
            )
    return out


def coletar(engine: Engine, agora: dt.datetime | None = None, vigilancia=None) -> tuple[list[Novo], set[str]]:
    """O que está errado agora e quais origens foram olhadas (uma origem que falhou não fecha os alertas dela)."""
    agora = agora or _agora()
    regras = politica()["regras"]
    novos: list[Novo] = []
    olhadas: set[str] = set()
    checagens: list[tuple[set[str], Callable[[], list[Novo]]]] = []

    def no_banco(f):
        def rodar():
            with engine.connect() as con:
                return f(con, regras, agora)

        return rodar

    checagens += [
        ({"lote_falhou", "lote_travado"}, no_banco(_lotes)),
        ({"orcamento"}, no_banco(_orcamento)),
        ({"revisao_parada", "mensagens_paradas"}, no_banco(_filas)),
        ({"pedido_problema"}, no_banco(_pedidos)),
        ({"cascata_faixa"}, no_banco(_cascata)),
    ]
    if vigilancia is None:
        try:
            from raiz.vigilancia.servico import Vigilancia

            vigilancia = Vigilancia()
        except Exception as ex:  # noqa: BLE001
            log.warning("vigilância indisponível para os alertas: %s", type(ex).__name__)
    if vigilancia is not None:
        checagens.append(
            ({"vigilancia_atrasada", "vigilancia_fonte", "verra_prazo"},
             lambda: _vigilancia(vigilancia, regras, agora.date()))
        )  # fmt: skip
    for origens, f in checagens:
        try:
            novos += f()
            olhadas |= origens
        except Exception as ex:  # noqa: BLE001 (uma checagem quebrada não cala as outras)
            log.warning("checagem de %s falhou: %s", ",".join(sorted(origens)), sanitizar_log(str(ex))[:200])
    return novos, olhadas


# --------------------------------------------------------------------------- registrar


def registrar(
    con: Connection,
    novos: list[Novo],
    olhadas: set[str],
    versao: str | None = None,
    agora: dt.datetime | None = None,
) -> dict:
    """Abre os alertas novos e fecha os estados que passaram. `agora` é o relógio da rodada (o mesmo do escalar)."""
    versao = versao or politica()["versao"]
    agora = agora or _agora()
    abertos = 0
    for n in novos:
        if n.gravidade not in GRAVIDADES:
            raise ValueError(f"gravidade {n.gravidade}")
        r = con.execute(
            text("""insert into operacao.alerta (origem, chave, gravidade, titulo, texto, detalhe, regra_versao,
                    criado_em) values (:o, :c, :g, :ti, :tx, cast(:d as jsonb), :v, :agora)
                    on conflict (chave) where resolvido_em is null do nothing returning id"""),
            {
                "o": n.origem,
                "c": n.chave,
                "g": n.gravidade,
                "ti": sanitizar_log(n.titulo)[:200],
                "tx": sanitizar_log(n.texto)[:2000],
                "d": json.dumps(sanitizar_estrutura({**n.detalhe, "continuo": n.continuo}), default=str),
                "v": versao,
                "agora": agora,
            },
        ).first()
        abertos += r is not None
    # estado que deixou de valer fecha sozinho (só nas origens que foram olhadas agora)
    vivas = [n.chave for n in novos]
    fechados = con.execute(
        text("""update operacao.alerta set resolvido_em = :agora, resolucao = 'a condição acabou'
                where resolvido_em is null and (detalhe->>'continuo')::boolean
                and origem = any(:o) and not (chave = any(:v)) returning id"""),
        {"o": sorted(olhadas), "v": vivas, "agora": agora},
    ).all()
    return {"abertos": abertos, "fechados_sozinhos": len(fechados)}


# --------------------------------------------------------------------------- escalar e enviar


def nivel_devido(criado_em: dt.datetime, gravidade: str, agora: dt.datetime, pol: dict | None = None) -> int:
    pol = pol or politica()
    minutos = (agora - criado_em).total_seconds() / 60
    teto = int(pol["teto_por_gravidade"][gravidade])
    devido = 0
    for n in pol["niveis"]:
        if minutos >= float(n["depois_min"]):
            devido = int(n["nivel"])
    return min(devido, teto)


class Enviador:
    """ntfy e GoAlert de verdade quando configurados; senão, simulado (o texto fica no alerta, nada sai)."""

    def __init__(self, cliente: httpx.Client | None = None):
        self.cfg = config()
        self.cliente = cliente or httpx.Client(timeout=10)

    def ntfy(self, titulo: str, texto: str, prioridade: int, tags: list[str]) -> str:
        topico = self.cfg.ntfy_topico.get_secret_value() if self.cfg.ntfy_topico else None
        if not topico:
            return "simulado"
        h = {}
        if self.cfg.ntfy_token:
            h["Authorization"] = f"Bearer {self.cfg.ntfy_token.get_secret_value()}"
        corpo = {"topic": topico, "title": titulo, "message": texto, "priority": prioridade, "tags": tags}
        try:
            r = self.cliente.post(self.cfg.ntfy_url.rstrip("/"), json=corpo, headers=h)
            return "enviado" if r.status_code < 300 else "falhou"
        except httpx.HTTPError:
            return "falhou"

    def segunda_pessoa(self, titulo: str, texto: str) -> str | None:
        """GoAlert (integração genérica). None quando não há segunda pessoa configurada."""
        if not self.cfg.goalert_url:
            return None
        try:
            r = self.cliente.post(self.cfg.goalert_url.get_secret_value(), data={"summary": titulo, "details": texto})
            return "enviado" if r.status_code < 300 else "falhou"
        except httpx.HTTPError:
            return "falhou"


def _enviar(enviador: Enviador, a, degrau: dict) -> dict:
    tags = {"aviso": ["warning"], "urgente": ["rotating_light"], "critico": ["rotating_light", "skull"]}[a.gravidade]
    canal = degrau["canal"]
    estado = None
    if canal == "segunda_pessoa":
        estado = enviador.segunda_pessoa(a.titulo, a.texto)
        if estado is None:  # sem segunda pessoa: o fundador recebe de novo, urgente
            canal = "ntfy"
    if estado is None:
        estado = enviador.ntfy(a.titulo, a.texto, int(degrau["prioridade"]), tags)
    return {"nivel": int(degrau["nivel"]), "canal": canal, "estado": estado}


def escalar(con: Connection, agora: dt.datetime | None = None, enviador: Enviador | None = None) -> list[dict]:
    """Manda o que está devido: primeiro envio, subida de nível ou repetição do último nível."""
    agora = agora or _agora()
    pol = politica()
    enviador = enviador or Enviador()
    degraus = {int(n["nivel"]): n for n in pol["niveis"]}
    rs = con.execute(
        text("""select id, gravidade, titulo, texto, nivel, envios, criado_em, ultimo_envio_em from operacao.alerta
                where resolvido_em is null and reconhecido_em is null order by id""")
    ).all()
    feitos = []
    for a in rs:
        devido = nivel_devido(a.criado_em, a.gravidade, agora, pol)
        envios = list(a.envios or [])
        repetir = (
            devido == a.nivel
            and devido == int(pol["teto_por_gravidade"][a.gravidade])
            and devido > 0
            and a.ultimo_envio_em is not None
            and agora - a.ultimo_envio_em >= dt.timedelta(minutes=float(pol["repetir_ultimo_min"]))
        )
        if not (devido > a.nivel or repetir) or len(envios) >= int(pol["max_envios"]):
            continue
        e = {**_enviar(enviador, a, degraus[devido]), "em": agora.isoformat(timespec="seconds")}
        envios.append(e)
        con.execute(
            text("""update operacao.alerta set nivel = :n, envios = cast(:e as jsonb), ultimo_envio_em = :a
                    where id = :id"""),
            {"n": devido, "e": json.dumps(envios), "a": agora, "id": a.id},
        )
        feitos.append({"alerta": a.id, **e})
    return feitos


def reconhecer(con: Connection, alerta_id: int, quem: str) -> bool:
    r = con.execute(
        text("""update operacao.alerta set reconhecido_em = now(), reconhecido_por = :q
                where id = :id and reconhecido_em is null and resolvido_em is null returning id"""),
        {"id": alerta_id, "q": sanitizar_log(str(quem or "fundador"))[:40]},
    ).first()
    return r is not None


def resolver(con: Connection, alerta_id: int, quem: str, nota: str = "") -> bool:
    r = con.execute(
        text("""update operacao.alerta set resolvido_em = now(), resolucao = :n,
                reconhecido_em = coalesce(reconhecido_em, now()), reconhecido_por = coalesce(reconhecido_por, :q)
                where id = :id and resolvido_em is null returning id"""),
        {
            "id": alerta_id,
            "q": sanitizar_log(str(quem or "fundador"))[:40],
            "n": sanitizar_log(nota or "resolvido")[:300],
        },
    ).first()
    return r is not None


def ciclo(engine: Engine, agora: dt.datetime | None = None, vigilancia=None, enviador: Enviador | None = None) -> dict:
    agora = agora or _agora()
    novos, olhadas = coletar(engine, agora, vigilancia)
    with engine.begin() as con:
        reg = registrar(con, novos, olhadas, agora=agora)
        env = escalar(con, agora, enviador)
    return {**reg, "envios": env, "olhadas": sorted(olhadas)}
