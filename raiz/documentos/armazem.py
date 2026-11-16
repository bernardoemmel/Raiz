"""Armazém das leituras (SQLite em dados/documentos/documentos.sqlite, fora do git).

- leitura: cada leitura de certidão ou edital, com o modelo que respondeu, as versões do prompt, do esquema, das regras
  e do leitor, os tokens e o custo. Nunca muda depois de gravada (gatilho no banco): reler cria outra linha. O
  registro_hash (sha256 da linha em forma canônica) prova depois que ninguém trocou a leitura.
- conferencia: a leitura comparada com o certidoes_<mun>.csv do motor, por imóvel do CAR. Também só cresce.
- gabarito: o resultado real (a certidão conferida por gente, pelo ONR ou pelo cartório) que confirma ou desmente a
  leitura. Correção = registrar de novo; vale o último.

Só entra aqui texto já limpo (sem nome, CPF e CNPJ mascarados). O PDF não entra: só o sha256 dele.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from raiz.documentos.config import pasta_dados

ESQUEMA = """
create table if not exists leitura (
    id integer primary key,
    tipo text not null,
    chave text not null,
    arquivo_sha256 text not null,
    paginas integer,
    modelo_pedido text not null,
    modelo text,
    prompt_versao text not null,
    esquema_versao text not null,
    regras_versao text,
    leitor_versao text not null,
    esforco text,
    lido_em text not null,
    duracao_ms integer,
    tokens_entrada integer,
    tokens_saida integer,
    tokens_cache_leitura integer,
    tokens_cache_escrita integer,
    custo_usd real,
    situacao_documento text,
    confianca text,
    dados_json text not null,
    derivados_json text,
    erro text,
    registro_hash text not null unique
);
create index if not exists leitura_chave on leitura (tipo, chave);
create trigger if not exists leitura_nao_muda before update on leitura
    begin select raise(abort, 'leitura é imutável: leia de novo para criar outra'); end;
create trigger if not exists leitura_nao_some before delete on leitura
    begin select raise(abort, 'leitura é imutável'); end;

create table if not exists conferencia (
    id integer primary key,
    leitura_id integer not null references leitura (id),
    cod_imovel text,
    registro_cns text,
    registro_matricula text,
    situacao text not null,
    precisa_confirmar integer not null,
    motivos_json text not null,
    regras_versao text not null,
    conferido_em text not null,
    motor_arquivo text,
    motor_ha_sobre_car real
);
create index if not exists conferencia_imovel on conferencia (cod_imovel);
create trigger if not exists conferencia_nao_muda before update on conferencia
    begin select raise(abort, 'conferência é imutável: confira de novo para criar outra'); end;

create table if not exists gabarito (
    id integer primary key,
    leitura_id integer references leitura (id),
    chave text not null,
    alvo text not null,
    valor_real text,
    confirma integer,
    fonte text not null,
    observado_em text not null,
    registrado_em text not null,
    nota text
);
create index if not exists gabarito_leitura on gabarito (leitura_id, alvo);

-- última conferência de cada (imóvel, matrícula)
create view if not exists conferencia_vigente as
select c.* from conferencia c
where c.id = (select max(c2.id) from conferencia c2
              where coalesce(c2.cod_imovel, '') = coalesce(c.cod_imovel, '')
                and c2.registro_cns is c.registro_cns and c2.registro_matricula is c.registro_matricula);

-- último gabarito de cada (leitura, alvo)
create view if not exists gabarito_vigente as
select g.* from gabarito g
where g.id = (select max(g2.id) from gabarito g2 where g2.leitura_id is g.leitura_id and g2.alvo = g.alvo);

create table if not exists cache_decisao (
    id integer primary key,
    arquivo_sha256 text not null,
    leitura_id integer references leitura (id),
    decidido_em text not null,
    decisao_json text not null
);
create index if not exists leitura_arquivo on leitura (tipo, arquivo_sha256);
create trigger if not exists cache_decisao_nao_muda before update on cache_decisao
    begin select raise(abort, 'decisão de cache é imutável'); end;
create trigger if not exists cache_decisao_nao_some before delete on cache_decisao
    begin select raise(abort, 'decisão de cache é imutável'); end;
"""


def agora() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def _canonico(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


@dataclass
class Leitura:
    tipo: str
    chave: str
    arquivo_sha256: str
    modelo_pedido: str
    prompt_versao: str
    esquema_versao: str
    leitor_versao: str
    dados: dict
    paginas: int | None = None
    modelo: str | None = None
    regras_versao: str | None = None
    esforco: str | None = None
    lido_em: str | None = None
    duracao_ms: int | None = None
    tokens_entrada: int | None = None
    tokens_saida: int | None = None
    tokens_cache_leitura: int | None = None
    tokens_cache_escrita: int | None = None
    custo_usd: float | None = None
    situacao_documento: str | None = None
    confianca: str | None = None
    derivados: dict | None = None
    erro: str | None = None
    id: int | None = None
    registro_hash: str | None = None

    def linha(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k not in ("id", "registro_hash", "dados", "derivados")}
        d["dados_json"] = _canonico(self.dados)
        d["derivados_json"] = _canonico(self.derivados) if self.derivados is not None else None
        return d


class Armazem:
    def __init__(self, caminho: str | Path | None = None):
        self.caminho = Path(caminho) if caminho else pasta_dados() / "documentos.sqlite"
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with self.con() as c:
            c.executescript(ESQUEMA)

    @contextmanager
    def con(self):
        c = sqlite3.connect(self.caminho)
        c.row_factory = sqlite3.Row
        c.execute("pragma foreign_keys = on")
        c.execute("pragma journal_mode = wal")
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    # --- leituras -------------------------------------------------------------------------------------------------

    def gravar_leitura(self, leitura: Leitura) -> int:
        leitura.lido_em = leitura.lido_em or agora()
        linha = leitura.linha()
        linha["registro_hash"] = hashlib.sha256(_canonico(linha).encode("utf-8")).hexdigest()
        cols = ", ".join(linha)
        marcas = ", ".join(f":{k}" for k in linha)
        with self.con() as c:
            existente = c.execute(
                "select id from leitura where registro_hash = :h", {"h": linha["registro_hash"]}
            ).fetchone()
            if existente:
                leitura.id = existente["id"]
            else:
                leitura.id = c.execute(f"insert into leitura ({cols}) values ({marcas})", linha).lastrowid
        leitura.registro_hash = linha["registro_hash"]
        return leitura.id

    def leitura(self, leitura_id: int) -> Leitura | None:
        with self.con() as c:
            r = c.execute("select * from leitura where id = ?", (leitura_id,)).fetchone()
        return _para_leitura(r) if r else None

    def leituras(self, tipo: str | None = None, chave: str | None = None) -> list[Leitura]:
        sql, p = "select * from leitura where 1=1", []
        if tipo:
            sql, p = sql + " and tipo = ?", p + [tipo]
        if chave:
            sql, p = sql + " and chave = ?", p + [chave]
        with self.con() as c:
            return [_para_leitura(r) for r in c.execute(sql + " order by id", p).fetchall()]

    def conferir_hash(self, leitura_id: int) -> bool:
        """Refaz o hash da linha gravada e compara com o registro_hash: prova que a leitura não foi trocada."""
        lt = self.leitura(leitura_id)
        if lt is None:
            return False
        linha = lt.linha()
        return hashlib.sha256(_canonico(linha).encode("utf-8")).hexdigest() == lt.registro_hash

    def gravar_cache_decisao(self, arquivo_sha256: str, decisao: dict) -> None:
        with self.con() as c:
            c.execute(
                """insert into cache_decisao (arquivo_sha256, leitura_id, decidido_em, decisao_json)
                   values (?, ?, ?, ?)""",
                (arquivo_sha256, decisao.get("leitura_id"), agora(), _canonico(decisao)),
            )

    # --- conferências ---------------------------------------------------------------------------------------------

    def gravar_conferencia(
        self,
        leitura_id: int,
        situacao: str,
        motivos: list[dict],
        regras_versao: str,
        cod_imovel: str | None = None,
        registro_cns: str | None = None,
        registro_matricula: str | None = None,
        precisa_confirmar: bool = False,
        motor_arquivo: str | None = None,
        motor_ha_sobre_car: float | None = None,
    ) -> int:
        with self.con() as c:
            return c.execute(
                """insert into conferencia (leitura_id, cod_imovel, registro_cns, registro_matricula, situacao,
                   precisa_confirmar, motivos_json, regras_versao, conferido_em, motor_arquivo, motor_ha_sobre_car)
                   values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    leitura_id,
                    cod_imovel,
                    registro_cns,
                    registro_matricula,
                    situacao,
                    int(precisa_confirmar),
                    _canonico(motivos),
                    regras_versao,
                    agora(),
                    motor_arquivo,
                    motor_ha_sobre_car,
                ),
            ).lastrowid

    def conferencias_por_leitura(self, leitura_id: int | None = None) -> list[dict]:
        """A última conferência de cada (leitura, imóvel): é a previsão que cada leitura fez, mesmo depois de uma
        leitura mais nova da mesma matrícula passar a valer."""
        sql = """select c.*, l.modelo, l.lido_em, l.prompt_versao, l.arquivo_sha256, l.chave
                 from conferencia c join leitura l on l.id = c.leitura_id
                 where c.id = (select max(c2.id) from conferencia c2 where c2.leitura_id = c.leitura_id
                               and coalesce(c2.cod_imovel, '') = coalesce(c.cod_imovel, ''))"""
        p: list = []
        if leitura_id is not None:
            sql, p = sql + " and c.leitura_id = ?", [leitura_id]
        with self.con() as c:
            return [dict(r) for r in c.execute(sql + " order by c.id", p).fetchall()]

    def conferencias_vigentes(self, cod_imoveis: list[str] | None = None) -> list[dict]:
        with self.con() as c:
            rows = c.execute(
                """select cv.*, l.modelo, l.lido_em, l.leitor_versao, l.prompt_versao, l.derivados_json,
                          l.dados_json, l.arquivo_sha256, l.chave, l.registro_hash
                   from conferencia_vigente cv join leitura l on l.id = cv.leitura_id order by cv.id"""
            ).fetchall()
        out = [dict(r) for r in rows]
        if cod_imoveis is not None:
            alvo = set(cod_imoveis)
            out = [r for r in out if r["cod_imovel"] in alvo]
        return out

    # --- gabaritos ------------------------------------------------------------------------------------------------

    def gravar_gabarito(
        self,
        chave: str,
        alvo: str,
        fonte: str,
        valor_real: str | None = None,
        confirma: bool | None = None,
        leitura_id: int | None = None,
        observado_em: str | None = None,
        nota: str | None = None,
    ) -> int:
        if valor_real is None and confirma is None:
            raise ValueError("gabarito sem valor: diga o valor real ou se confirma")
        with self.con() as c:
            return c.execute(
                """insert into gabarito (leitura_id, chave, alvo, valor_real, confirma, fonte, observado_em,
                   registrado_em, nota) values (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    leitura_id,
                    chave,
                    alvo,
                    valor_real,
                    None if confirma is None else int(confirma),
                    fonte,
                    observado_em or dt.date.today().isoformat(),
                    agora(),
                    nota,
                ),
            ).lastrowid

    def gabaritos(self, leitura_id: int | None = None) -> list[dict]:
        sql, p = "select * from gabarito_vigente", []
        if leitura_id is not None:
            sql, p = sql + " where leitura_id = ?", [leitura_id]
        with self.con() as c:
            return [dict(r) for r in c.execute(sql + " order by id", p).fetchall()]


def _para_leitura(r: sqlite3.Row) -> Leitura:
    d = dict(r)
    dados = json.loads(d.pop("dados_json") or "{}")
    der = d.pop("derivados_json")
    return Leitura(dados=dados, derivados=json.loads(der) if der else None, **d)
