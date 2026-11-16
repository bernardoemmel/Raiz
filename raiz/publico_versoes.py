"""Ficha pública básica datada. O conteúdo congela; a autorização de acesso nunca congela.

A origem é a própria linha histórica de resultado_imovel e sua rodada, nunca o cadastro atual.
Não compartilha o histórico privado de fichas pagas. Não há nome, CAR, geometria nem número pago
na tabela, no hash ou no documento. Revogar o aceite bloqueia também os links já emitidos.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import html
import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Connection, Engine, text

from raiz import markdown as markdown_mod

CODIGO = re.compile(r"[0-9A-HJKMNP-TV-Z]{6,8}", re.IGNORECASE | re.ASCII)
VERSAO = re.compile(r"(\d{4}-\d{2}-\d{2})-r([1-9][0-9]{0,18})-([0-9a-f]{64})")
FONTE = "CAR (SICAR/SFB); situação básica calculada pelo motor Raíz na rodada indicada."
SITUACOES = {"apto": "Apto", "com_pendencia": "Com pendência", "nao_apto": "Não apto"}
SEM_CACHE = {"Cache-Control": "private, no-store", "Vary": "Accept"}
UFS_IBGE = dict(
    zip(
        "11 12 13 14 15 16 17 21 22 23 24 25 26 27 28 29 31 32 33 35 41 42 43 50 51 52 53".split(),
        "RO AC AM RR PA AP TO MA PI CE RN PB PE AL SE BA MG ES RJ SP PR SC RS MS MT GO DF".split(),
        strict=True,
    )
)


@lru_cache(maxsize=1)
def _municipios() -> dict[str, str]:
    with (Path(__file__).parent / "executor" / "municipios.csv").open(encoding="utf-8") as f:
        return {m["codigo_ibge"]: m["nome"] for m in csv.DictReader(f)}


def local_basico(cod_ibge, municipio, uf) -> tuple[str | None, str | None]:
    """Valida rótulos históricos em catálogo fechado, sem preencher ausentes com o cadastro atual.

    Texto livre pode conter nome de pessoa. Um nome divergente do catálogo fica não informado,
    inclusive quando houve renomeação; só uma rodada conferida pode fornecer um novo rótulo.
    """
    cod = str(cod_ibge)
    nome = _municipios().get(cod)
    mun = nome if nome and isinstance(municipio, str) and municipio.strip().casefold() == nome.casefold() else None
    estado = uf if nome and uf == UFS_IBGE.get(cod[:2]) else None
    return mun, estado


def codigo_valido(codigo: str) -> bool:
    return bool(CODIGO.fullmatch(codigo))


def _area(valor) -> float | None:
    if valor is None:
        return None
    x = float(valor)
    return x if math.isfinite(x) and x >= 0 else None


def _situacao(etapa: str | None) -> str | None:
    """Traduz a foto histórica da carga; nunca reaplica as regras atuais sobre uma rodada antiga.

    cadastro e sem_problema eram os pontos de saída do funil (bloqueio e falta de área apta).
    com_matricula é o nome histórico da etapa hoje chamada caminho_terra. Uma etapa ausente ou
    ainda não reconhecida exige conferência; não é evidência de aptidão nem de reprovação.
    """
    return {
        "cadastro": "com_pendencia",
        "sem_problema": "nao_apto",
        "apta": "apto",
        "com_matricula": "apto",
        "caminho_terra": "apto",
        "titulo_conferido": "apto",
        "aceite": "apto",
    }.get(etapa)


@dataclass(frozen=True)
class VersaoPublica:
    codigo: str
    rodada_id: int
    data_corte: dt.date
    municipio: str | None
    uf: str | None
    area_car_ha: float | None
    situacao_basica: str | None
    fonte: str
    sha256: str
    registrada_em: dt.datetime

    @property
    def identificador(self) -> str:
        return f"{self.data_corte.isoformat()}-r{self.rodada_id}-{self.sha256}"

    @property
    def caminho(self) -> str:
        return f"/p/{self.codigo}/v/{self.identificador}"


def _autorizado(con: Connection, codigo: str) -> bool:
    # O consentimento é consultado em TODA leitura, inclusive de snapshots antigos.
    return (
        con.execute(
            text("""select 1 from negocio.codigo_curto k join negocio.aceite a using (cod_imovel)
                where k.codigo=:c and a.estado='aceito' for share of a, k"""),
            {"c": codigo},
        ).first()
        is not None
    )


def _registrar(con: Connection, codigo: str, rodada_id: int | None = None) -> VersaoPublica | None:
    filtro = "and r.rodada_id=:r" if rodada_id is not None else ""
    r = (
        con.execute(
            text(f"""select k.codigo, r.rodada_id, ro.data_corte, r.cod_municipio_ibge, r.municipio, r.uf, r.ha,
                        e.etapa
                 from negocio.codigo_curto k
                 join funil.resultado_imovel r on r.cod_imovel=k.cod_imovel
                 join funil.rodada ro on ro.id=r.rodada_id
                 left join funil.etapa_rodada e on e.rodada_id=r.rodada_id and e.cod_imovel=r.cod_imovel
                 where k.codigo=:c and ro.tipo='municipio' {filtro}
                 order by ro.data_corte desc, ro.id desc limit 1"""),
            {"c": codigo, "r": rodada_id},
        )
        .mappings()
        .first()
    )
    if r is None:
        return None
    # Lista positiva antes de calcular o hash; a consulta também dispensa os insumos pagos.
    municipio, uf = local_basico(r["cod_municipio_ibge"], r["municipio"], r["uf"])
    basico = {
        "codigo": r["codigo"],
        "rodada_id": r["rodada_id"],
        "data_corte": r["data_corte"].isoformat(),
        "municipio": municipio,
        "uf": uf,
        "area_car_ha": _area(r["ha"]),
        "situacao_basica": _situacao(r["etapa"]),
        "fonte": FONTE,
    }
    assinatura = hashlib.sha256(
        json.dumps(basico, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    con.execute(
        text("""insert into negocio.ficha_publica_versao
                (codigo,rodada_id,data_corte,municipio,uf,area_car_ha,situacao_basica,fonte,sha256)
                values (:codigo,:rodada_id,:data_corte,:municipio,:uf,:area_car_ha,:situacao_basica,:fonte,:sha256)
                on conflict (codigo,rodada_id) do nothing"""),
        {**basico, "sha256": assinatura},
    )
    # Uma correção do motor precisa de nova rodada: reler a origem não altera a versão já registrada.
    return _ler(con, codigo, r["rodada_id"])


def _ler(con: Connection, codigo: str, rodada_id: int) -> VersaoPublica | None:
    r = (
        con.execute(
            text("""select codigo,rodada_id,data_corte,municipio,uf,area_car_ha,situacao_basica,
                            fonte,sha256,registrada_em from negocio.ficha_publica_versao
                            where codigo=:c and rodada_id=:r"""),
            {"c": codigo, "r": rodada_id},
        )
        .mappings()
        .first()
    )
    return VersaoPublica(**r) if r else None


def registrar(engine: Engine, codigo: str, rodada_id: int | None = None) -> VersaoPublica | None:
    """Registra uma rodada verdadeira, se consentida; sem id, escolhe a mais recente pela data de corte."""
    if not codigo_valido(codigo):
        return None
    codigo = codigo.upper()
    with engine.begin() as con:
        return _registrar(con, codigo, rodada_id) if _autorizado(con, codigo) else None


def obter(engine: Engine, codigo: str, identificador: str) -> tuple[VersaoPublica, VersaoPublica | None] | None:
    """Lê só uma versão já emitida. O aviso aponta apenas para uma rodada cronologicamente posterior."""
    m = VERSAO.fullmatch(identificador)
    if not codigo_valido(codigo) or m is None:
        return None
    try:
        dt.date.fromisoformat(m[1])
    except ValueError:
        return None
    codigo = codigo.upper()
    with engine.begin() as con:
        if not _autorizado(con, codigo):
            return None
        v = _ler(con, codigo, int(m[2]))
        if v is None or v.identificador != identificador:
            return None
        _registrar(con, codigo)
        # Um snapshot posterior continua verdadeiro mesmo se a retenção apagar a origem privada.
        ultimo_id = con.execute(
            text("""select rodada_id from negocio.ficha_publica_versao
                                        where codigo=:c order by data_corte desc,rodada_id desc limit 1"""),
            {"c": codigo},
        ).scalar_one()
        atual = _ler(con, codigo, ultimo_id)
        nova = atual if atual and (atual.data_corte, atual.rodada_id) > (v.data_corte, v.rodada_id) else None
        return v, nova


def _linhas(v: VersaoPublica) -> list[tuple[str, str]]:
    area = (
        "Não informada"
        if v.area_car_ha is None
        else f"{v.area_car_ha:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " ha"
    )
    return [
        ("Código da fazenda", v.codigo),
        ("Município", v.municipio or "Não informado"),
        ("Estado", v.uf or "Não informado"),
        ("Área do polígono do CAR", area),
        ("Situação básica", SITUACOES.get(v.situacao_basica, "Ainda não conferida")),
        ("Dados até", v.data_corte.strftime("%d/%m/%Y")),
        ("Rodada", str(v.rodada_id)),
        ("Versão registrada em", v.registrada_em.astimezone(dt.UTC).strftime("%d/%m/%Y às %H:%M UTC")),
    ]


def pagina_markdown(v: VersaoPublica, nova: VersaoPublica | None, base_url: str) -> str:
    t = markdown_mod.texto
    base = base_url.rstrip("/")
    linhas = [f"# Ficha básica {v.codigo} · {v.data_corte.strftime('%d/%m/%Y')}", ""]
    if nova:
        linhas += [
            (
                f"Há uma versão mais recente: [dados até {nova.data_corte.strftime('%d/%m/%Y')}, "
                f"rodada {nova.rodada_id}]({base}{nova.caminho})."
            ),
            "",
        ]
    linhas += [f"- **{chave}:** {t(valor)}" for chave, valor in _linhas(v)]
    linhas += [
        "",
        f"Fonte: {t(v.fonte)}",
        "",
        "A situação básica é uma triagem; não certifica a propriedade nem garante créditos.",
        "",
        f"[Link desta versão]({base}{v.caminho}).",
        "",
        f"Identificador: {v.identificador}.",
        "",
        "O conteúdo desta versão não muda. A consulta depende do consentimento vigente.",
        "",
    ]
    return "\n".join(linhas)


def pagina(v: VersaoPublica, nova: VersaoPublica | None, base_url: str) -> str:
    e = html.escape
    url = e(base_url.rstrip("/") + v.caminho, quote=True)
    titulo = f"Ficha básica {v.codigo} · {v.data_corte.strftime('%d/%m/%Y')}"
    aviso = ""
    if nova:
        destino = e(base_url.rstrip("/") + nova.caminho, quote=True)
        aviso = (
            f'<aside aria-label="Atualização">Há uma versão mais recente: <a href="{destino}">'
            f"dados até {nova.data_corte.strftime('%d/%m/%Y')}, rodada {nova.rodada_id}</a>.</aside>"
        )
    campos = "".join(f"<dt>{e(chave)}</dt><dd>{e(valor)}</dd>" for chave, valor in _linhas(v))
    return f'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(titulo)} · Raíz</title>
<link rel="canonical" href="{url}"><link rel="alternate" type="text/markdown" href="{url}.md">
<meta property="og:type" content="website"><meta property="og:title" content="{e(titulo)}">
<meta property="og:url" content="{url}"><meta name="description" content="Ficha pública básica datada da Raíz.">
<style>body{{margin:0;background:#f4f1ea;color:#15231b;font:18px/1.5 system-ui,sans-serif}}
main{{max-width:720px;padding:24px;margin:auto}}h1{{font-size:1.7rem}}a{{color:#1d5a39}}
a:focus-visible{{outline:3px solid #15231b;outline-offset:4px}}dt{{font-weight:700}}dd{{margin:0 0 16px}}
aside{{border:2px solid #1d5a39;padding:12px}}.identificador{{overflow-wrap:anywhere;font-size:14px}}</style></head>
<body><main><h1>{e(titulo)}</h1>{aviso}<dl>{campos}</dl><p>Fonte: {e(v.fonte)}</p>
<p>A situação básica é uma triagem; não certifica a propriedade nem garante créditos.</p>
<p><a href="{url}">Link desta versão</a> · <a href="{url}.md">Ler em Markdown</a></p>
<p class="identificador">Identificador: {v.identificador}</p>
<p>O conteúdo desta versão não muda. A consulta depende do consentimento vigente.</p></main></body></html>'''
