"""Busca semanal: roda as fontes, compara com o que já foi visto e escreve a lista do que apareceu de novo.

Estado em dados/documentos/busca/busca.sqlite (só dado público: título, link, data e órgão; separado das leituras de
certidão, que nunca saem do servidor). Na primeira rodada de cada fonte tudo vira linha de base e não entra como
novidade: a lista começa a valer na semana seguinte.

Saída: novidades_<AAAA-MM-DD>.md (para ler e para abrir como issue) e novidades_<AAAA-MM-DD>.csv.
Rodar: python -m raiz.documentos busca semanal  (cron toda segunda, ou o workflow .github/workflows/busca-semanal.yml)
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from raiz.documentos.armazem import agora
from raiz.documentos.busca import fontes as F
from raiz.documentos.config import pasta_dados

ESQUEMA = """
create table if not exists item (
    fonte text not null,
    chave text not null,
    titulo text not null,
    url text,
    data text,
    orgao text,
    tipo text,
    marca text,
    detalhe_json text,
    primeira_vez text not null,
    ultima_vez text not null,
    ultima_mudanca text,
    primary key (fonte, chave)
);
create table if not exists rodada (
    id integer primary key,
    iniciada_em text not null,
    terminada_em text,
    resumo_json text
);
"""

NOMES = {
    "verra": "Verra (registro VCS)",
    "sfb": "Serviço Florestal Brasileiro",
    "ideflor_bio": "Ideflor-Bio (Pará)",
    "dou": "Diário Oficial da União",
}


@dataclass
class Novidade:
    tipo: str  # novo | mudou
    item: F.Item
    marca_antes: str | None = None


@dataclass
class Relatorio:
    data: dt.date
    fontes: list[F.ResultadoFonte]
    novidades: list[Novidade] = field(default_factory=list)
    linha_de_base: dict[str, int] = field(default_factory=dict)
    arquivo_md: Path | None = None
    arquivo_csv: Path | None = None

    @property
    def tem_novidade(self) -> bool:
        return bool(self.novidades)


class EstadoBusca:
    def __init__(self, caminho: str | Path | None = None):
        self.caminho = Path(caminho) if caminho else pasta_dados() / "busca" / "busca.sqlite"
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with self.con() as c:
            c.executescript(ESQUEMA)

    @contextmanager
    def con(self):
        c = sqlite3.connect(self.caminho)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    def conhece_fonte(self, fonte: str) -> bool:
        with self.con() as c:
            return c.execute("select 1 from item where fonte = ? limit 1", (fonte,)).fetchone() is not None

    def registrar(self, res: F.ResultadoFonte, quando: str) -> tuple[list[Novidade], bool]:
        """Grava os itens da fonte. Devolve (novidades, era_linha_de_base)."""
        base = not self.conhece_fonte(res.fonte)
        novs: list[Novidade] = []
        with self.con() as c:
            for it in res.itens:
                antes = c.execute(
                    "select marca from item where fonte = ? and chave = ?", (it.fonte, it.chave)
                ).fetchone()
                det = json.dumps(it.detalhe, ensure_ascii=False, sort_keys=True)
                if antes is None:
                    c.execute(
                        """insert into item (fonte, chave, titulo, url, data, orgao, tipo, marca, detalhe_json,
                           primeira_vez, ultima_vez) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            it.fonte,
                            it.chave,
                            it.titulo,
                            it.url,
                            it.data,
                            it.orgao,
                            it.tipo,
                            it.marca,
                            det,
                            quando,
                            quando,
                        ),
                    )
                    if not base:
                        novs.append(Novidade("novo", it))
                    continue
                mudou = it.marca is not None and antes["marca"] is not None and it.marca != antes["marca"]
                c.execute(
                    """update item set titulo = ?, url = ?, data = coalesce(?, data), orgao = ?, tipo = ?, marca = ?,
                       detalhe_json = ?, ultima_vez = ?, ultima_mudanca = case when ? then ? else ultima_mudanca end
                       where fonte = ? and chave = ?""",
                    (
                        it.titulo,
                        it.url,
                        it.data,
                        it.orgao,
                        it.tipo,
                        it.marca,
                        det,
                        quando,
                        mudou,
                        quando,
                        it.fonte,
                        it.chave,
                    ),
                )
                if mudou:
                    novs.append(Novidade("mudou", it, antes["marca"]))
        return novs, base

    def abrir_rodada(self) -> int:
        with self.con() as c:
            return c.execute("insert into rodada (iniciada_em) values (?)", (agora(),)).lastrowid

    def fechar_rodada(self, rid: int, resumo: dict) -> None:
        with self.con() as c:
            c.execute(
                "update rodada set terminada_em = ?, resumo_json = ? where id = ?",
                (agora(), json.dumps(resumo, ensure_ascii=False), rid),
            )


def rodar(
    estado: EstadoBusca | None = None,
    resultados: list[F.ResultadoFonte] | None = None,
    usar_firecrawl: bool = True,
    so: list[str] | None = None,
    hoje: dt.date | None = None,
    pasta: Path | None = None,
) -> Relatorio:
    hoje = hoje or dt.date.today()
    estado = estado or EstadoBusca()
    rid = estado.abrir_rodada()
    resultados = resultados if resultados is not None else F.todas(usar_firecrawl=usar_firecrawl, so=so)
    rel = Relatorio(hoje, resultados)
    quando = agora()
    for res in resultados:
        if not res.ok and not res.itens:
            continue
        novs, base = estado.registrar(res, quando)
        if base:
            rel.linha_de_base[res.fonte] = len(res.itens)
        rel.novidades += novs
    estado.fechar_rodada(rid, {r.fonte: dict(itens=len(r.itens), via=r.via, erro=r.erro) for r in resultados})
    escrever(rel, pasta or estado.caminho.parent)
    return rel


def _linha_md(n: Novidade) -> str:
    it = n.item
    titulo = f"[{it.titulo}]({it.url})" if it.url else it.titulo
    partes = [titulo]
    if it.data:
        partes.append(it.data)
    if it.orgao and it.fonte == "dou":
        partes.append(it.orgao)
    if n.tipo == "mudou":
        partes.append(f"mudou: {n.marca_antes or '?'} → {it.marca}" if it.fonte == "verra" else "página atualizada")
    elif it.marca and it.fonte == "verra":
        partes.append(it.marca)
    if it.detalhe.get("resumo"):
        partes.append(f"_{it.detalhe['resumo'][:220]}_")
    return "- " + " · ".join(partes)


def markdown(rel: Relatorio) -> str:
    total = len(rel.novidades)
    linhas = [f"# Registros e editais novos, semana de {rel.data.strftime('%d/%m/%Y')}", ""]
    linhas.append(f"{total} novidade{'s' if total != 1 else ''} nesta semana." if total else "Nada novo nesta semana.")
    linhas.append("")
    for res in rel.fontes:
        nome = NOMES.get(res.fonte, res.fonte)
        novs = [n for n in rel.novidades if n.item.fonte == res.fonte]
        linhas.append(f"## {nome}")
        if res.erro and not res.itens:
            linhas.append(f"Não deu para consultar: {res.erro}.")
        elif res.fonte in rel.linha_de_base:
            linhas.append(
                f"Primeira rodada: {rel.linha_de_base[res.fonte]} itens guardados como base. A partir da "
                "próxima semana, só o que for novo aparece aqui."
            )
        elif not novs:
            linhas.append("Nada novo.")
        for tipo, rotulo in (("novo", "Novos"), ("mudou", "Mudaram")):
            grupo = [n for n in novs if n.tipo == tipo]
            if grupo:
                linhas += ["", f"**{rotulo}**", *[_linha_md(n) for n in grupo]]
        if res.avisos:
            linhas += [
                "",
                "<details><summary>Avisos da consulta</summary>",
                "",
                *[f"- {a}" for a in res.avisos[:10]],
                "",
                "</details>",
            ]
        via = f"Consulta: {res.via}." if res.via else ""
        if via:
            linhas += ["", via]
        linhas.append("")
    linhas.append("Fontes públicas. Gerado por `python -m raiz.documentos busca semanal`.")
    return "\n".join(linhas) + "\n"


def escrever(rel: Relatorio, pasta: Path) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    rel.arquivo_md = pasta / f"novidades_{rel.data.isoformat()}.md"
    rel.arquivo_md.write_text(markdown(rel), encoding="utf-8")
    rel.arquivo_csv = pasta / f"novidades_{rel.data.isoformat()}.csv"
    with rel.arquivo_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tipo", "fonte", "chave", "titulo", "url", "data", "orgao", "marca", "marca_antes", "resumo"])
        for n in rel.novidades:
            it = n.item
            w.writerow(
                [
                    n.tipo,
                    it.fonte,
                    it.chave,
                    it.titulo,
                    it.url,
                    it.data,
                    it.orgao,
                    it.marca,
                    n.marca_antes,
                    it.detalhe.get("resumo"),
                ]
            )
