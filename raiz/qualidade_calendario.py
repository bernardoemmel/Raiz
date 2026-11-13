"""Projeção pública do calendário para o site, executável só com a biblioteca padrão.

Descarta textos livres e enriquecimentos privados do snapshot; usa exclusivamente
os rótulos e hosts do manifesto revisado. Recria também o ICS, sem copiar o feed
remoto. URLs com documentos, contato ou parâmetros pessoais são recusadas.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

from raiz import RAIZ_REPO
from raiz.calendario.feed import ics
from raiz.privacidade import cnpj_valido, cpf_valido, mascarar

DOCUMENTO_URL = re.compile(
    r"(?<![A-Z0-9])(?:[0-9A-Z]{2}\.[0-9A-Z]{3}\.[0-9A-Z]{3}/[0-9A-Z]{4}-\d{2}|"
    r"\d{3}\.\d{3}\.\d{3}-\d{2}|[0-9A-Z]{12}\d{2}|\d{11})(?![A-Z0-9])",
    re.I,
)

TITULOS = {
    "leilao_imovel": "Leilão de imóvel rural",
    "penhora": "Penhora de imóvel rural",
    "edital_bndes": "Edital do BNDES",
    "profloresta": "ProFloresta+",
    "fundo_amazonia": "Fundo Amazônia",
    "concessao": "Concessão florestal",
    "leilao_credito": "Leilão de créditos de carbono",
    "sbce": "SBCE",
    "verra": "Verra",
    "icvcm": "ICVCM",
    "sbti": "SBTi",
    "eudr": "EUDR",
}
MARCOS = {
    "evento": "data do evento",
    "propostas": "entrega de propostas",
    "inscricoes": "inscrições",
    "consulta": "fim da consulta",
    "vigencia": "início da aplicação",
    "penhora": "registro da penhora",
}
UFS = frozenset("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
CONTATO = re.compile(
    r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}|\+55[ -]?\d{2}[ -]?\d{4,5}[- ]?\d{4}"
    r"|\(\d{2}\)\s*\d{4,5}[- ]?\d{4}|(?<!\d)\d{2}[- ]\d{4,5}[- ]\d{4}(?!\d)"
)
CAMPO_PESSOAL = re.compile(
    r"(?i)(?:cpf|cnpj|e_?mail|telefone|phone|celular|whats|contato|contact|token|api_?key|secret|senha|password"
    r"|propriet[aá]rio|titular|dono|owner|(?:^|[_-])(?:nome|name|autor)(?:$|[_-]))"
)
LIMITE_BYTES = 10 * 1024**2


class ErroCalendarioPublico(ValueError):
    """Erro que pode ser exibido sem revelar conteúdo da entrada."""


def _falhar() -> None:
    raise ErroCalendarioPublico("calendário bloqueado: contrato público ou privacidade inválidos; valores omitidos")


def _texto(valor, padrao: str) -> str:
    if not isinstance(valor, str) or not re.fullmatch(padrao, valor):
        _falhar()
    return valor


def _data(valor) -> dt.date:
    _texto(valor, r"\d{4}-\d{2}-\d{2}")
    data = dt.date.fromisoformat(valor)
    if data == dt.date.max:
        _falhar()  # o fim exclusivo do evento ICS precisa caber no dia seguinte
    return data


def _instante(valor) -> dt.datetime:
    _texto(valor, r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})")
    return dt.datetime.fromisoformat(valor).astimezone(dt.UTC)


def _inteiro(valor) -> int:
    if type(valor) is not int or not 0 <= valor <= 2**31 - 1:
        _falhar()
    return valor


def validar_url_publica(valor, hosts: list[str]) -> str:
    if not isinstance(valor, str) or not valor.isascii() or any(ord(c) <= 32 or c == "\\" for c in valor):
        _falhar()
    url = urlsplit(valor)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.hostname not in hosts
        or url.username is not None
        or url.password is not None
        or url.port not in {None, 80 if url.scheme == "http" else 443}
    ):
        _falhar()
    # Fragmentos, inclusive :~:text=, nunca vão para o site nem para o feed.
    publico = urlunsplit((url.scheme, url.netloc, url.path, url.query, ""))
    claro = publico
    for _ in range(4):
        novo = unquote(claro)
        if novo == claro:
            break
        claro = novo
    if unquote(claro) != claro or any(ord(c) < 32 or c == "\\" for c in claro):
        _falhar()
    if any("." in d or cpf_valido(d) or cnpj_valido(d) for d in DOCUMENTO_URL.findall(claro)):
        _falhar()
    if mascarar(claro) != claro or CONTATO.search(claro):
        _falhar()
    if any(CAMPO_PESSOAL.search(chave) for chave, _ in parse_qsl(urlsplit(claro).query, keep_blank_values=True)):
        _falhar()
    if re.search(r"(?i)(?:bearer[ +]|\b(?:ghp_|github_pat_|sk_live_))", claro):
        _falhar()
    if re.search(r"(?i)(?:/|[-_])(?:proprietario|titular|dono|contato|cpf|cnpj|email|nome)(?:/|[-_=])", claro):
        _falhar()
    return publico


def _evento(item: dict, fontes: dict) -> dict:
    if not isinstance(item, dict):
        _falhar()
    fid = item.get("fonte_id")
    if not isinstance(fid, str) or fid not in fontes:
        _falhar()
    tipo, marco = item.get("tipo"), item.get("marco", "evento")
    if not isinstance(tipo, str) or tipo not in TITULOS or not isinstance(marco, str) or marco not in MARCOS:
        _falhar()
    referencia = item.get("referencia")
    if referencia is not None:
        _texto(referencia, r"\d{1,5}(?:[/.-]\d{1,4}){0,3}")
        if mascarar(referencia) != referencia:
            _falhar()
    data = _data(item.get("data"))
    prazo = _data(item["prazo"]) if item.get("prazo") is not None else None
    if prazo and prazo < data:
        _falhar()
    uf, municipio = item.get("uf"), item.get("municipio")
    if uf is not None and (not isinstance(uf, str) or uf not in UFS):
        _falhar()
    if municipio is not None:
        _texto(municipio, r"\d{7}")
    confianca = item.get("confianca")
    if type(confianca) not in {int, float} or not math.isfinite(confianca) or not 0 <= confianca <= 1:
        _falhar()
    situacao, vinculo = item.get("situacao", "previsto"), item.get("vinculo", "pendente")
    if (
        not isinstance(situacao, str)
        or situacao not in {"previsto", "cancelado", "adiado"}
        or not isinstance(vinculo, str)
        or vinculo not in {"car", "cns_matricula", "sigef", "pendente"}
    ):
        _falhar()
    cars = item.get("codigos_car", [])
    if not isinstance(cars, list) or len(cars) > 10000:
        _falhar()
    for car in cars:
        _texto(car, r"[A-Z]{2}-\d{7}-[A-F0-9]{32}")
        if car[:2] not in UFS:
            _falhar()
    cars = sorted(set(cars)) if vinculo in {"car", "pendente"} else []
    car_fonte_url = item.get("car_fonte_url")
    if car_fonte_url is not None:
        if not cars:
            _falhar()
        car_fonte_url = validar_url_publica(car_fonte_url, fontes[fid]["hosts"])
    return {
        "id": _texto(item.get("id"), r"[a-f0-9]{24}"),
        "tipo": tipo,
        "marco": marco,
        "referencia": referencia,
        "titulo": f"{TITULOS[tipo]}: {MARCOS[marco]}" + (f", edital {referencia}" if referencia else ""),
        "data": data.isoformat(),
        "prazo": prazo.isoformat() if prazo else None,
        "uf": uf,
        "municipio": municipio,
        "codigos_car": cars,
        "car_fonte_url": car_fonte_url,
        "vinculo": "car" if cars else "pendente",
        "fonte_id": fid,
        "fonte_nome": fontes[fid]["nome"],
        "fonte_url": validar_url_publica(item.get("fonte_url"), fontes[fid]["hosts"]),
        "coletado_em": _instante(item.get("coletado_em")).isoformat(),
        "atualizado_em": _instante(item["atualizado_em"]).isoformat() if item.get("atualizado_em") else None,
        "confianca": confianca,
        "situacao": situacao,
        "sequencia": _inteiro(item.get("sequencia", 0)),
    }


def _estado(item: dict, fontes: dict) -> dict:
    if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] not in fontes:
        _falhar()
    situacao = item.get("situacao")
    if not isinstance(situacao, str) or situacao not in {"ok", "parcial", "erro", "sem_data"}:
        _falhar()
    return {
        "id": item["id"],
        "nome": fontes[item["id"]]["nome"],
        "coletado_em": _instante(item.get("coletado_em")).isoformat(),
        "situacao": situacao,
        "erro": (
            "Fonte com leitura incompleta; consulte a publicação oficial." if situacao in {"erro", "parcial"} else None
        ),
        **{campo: _inteiro(item.get(campo, 0)) for campo in ("paginas", "eventos", "sem_data")},
    }


def projetar_snapshot(dados: dict) -> dict:
    """Devolve agenda+ICS reconstruídos. Nunca devolve campos livres da entrada."""
    if not isinstance(dados, dict) or any(not isinstance(dados.get(c), list) for c in ("eventos", "fontes")):
        _falhar()
    if len(dados["eventos"]) > 10000 or len(dados["fontes"]) > 100:
        _falhar()
    manifesto = json.loads((RAIZ_REPO / "front/compartilhado/calendario-fontes.json").read_text(encoding="utf-8"))
    fontes = {f["id"]: f for f in manifesto}
    eventos = [_evento(e, fontes) for e in dados["eventos"]]
    estados = [_estado(e, fontes) for e in dados["fontes"]]
    if len({e["id"] for e in eventos}) != len(eventos) or len({e["id"] for e in estados}) != len(estados):
        _falhar()
    eventos.sort(key=lambda e: (e["prazo"] or e["data"], e["id"]))
    agenda = {
        "eventos": eventos,
        "total": len(eventos),
        "fontes": estados,
        "coletado_em": max((e["coletado_em"] for e in estados), default=None),
    }
    modelos = [
        SimpleNamespace(
            **{
                **e,
                "coletado_em": _instante(e["coletado_em"]),
                "atualizado_em": _instante(e["atualizado_em"]) if e["atualizado_em"] else None,
                "dia": _data(e["prazo"] or e["data"]),
                "codigos_car_publicos": e["codigos_car"],
            }
        )
        for e in eventos
    ]
    return {"agenda": agenda, "ics": ics(modelos)}


def _normalizar_instantes(dado: dict) -> dict:
    return {
        k: _instante(v).isoformat() if k in {"coletado_em", "atualizado_em"} and v is not None else v
        for k, v in dado.items()
    }


def _erro_fonte_conhecido(erro) -> None:
    if erro is None or erro == "Fonte com leitura incompleta; consulte a publicação oficial.":
        return
    if (
        not isinstance(erro, str)
        or not erro
        or not re.fullmatch(
            r"(?:[0-9]{1,5} página\(s\) não puderam ser lidas; consulte a fonte oficial\.(?: )?)?"
            r"(?:Há atos cuja data não pôde ser confirmada\.(?: )?)?"
            r"(?:Limite de páginas da rodada atingido; cobertura parcial\.)?",
            erro,
        )
    ):
        _falhar()


def _validar_original(dados: dict, *, estado: bool) -> dict:
    """O Release publica os arquivos originais: nenhum campo extra pode ser ignorado."""
    projetado = projetar_snapshot(dados)
    agenda = projetado["agenda"]
    if set(dados) != set(agenda) or type(dados["total"]) is not int or dados["total"] != agenda["total"]:
        _falhar()
    if _normalizar_instantes({"coletado_em": dados["coletado_em"]})["coletado_em"] != agenda["coletado_em"]:
        _falhar()
    eventos = {e["id"]: e for e in agenda["eventos"]}
    for original in dados["eventos"]:
        esperado = dict(eventos[original["id"]])
        if estado:
            esperado.pop("titulo")
            cns, matricula, sigef = (original.get(c) for c in ("cns", "matricula", "sigef"))
            if cns is not None:
                _texto(cns, r"[0-9]{6}")
            if matricula is not None:
                # Identificador de registro, não um campo textual para o titular.
                _texto(matricula, r"(?:[A-Z]{0,3}[0-9]{1,12}[A-Z]{0,3})")
                if mascarar(matricula) != matricula:
                    _falhar()
            if not isinstance(sigef, list) or len(sigef) > 10000:
                _falhar()
            for codigo in sigef:
                _texto(codigo, r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}")
            esperado.update(cns=cns, matricula=matricula, sigef=sorted(set(sigef)))
            esperado["vinculo"] = original["vinculo"]
            esperado["codigos_car"] = sorted(set(original["codigos_car"]))
        if _normalizar_instantes(original) != esperado:
            _falhar()
    estados = {f["id"]: f for f in agenda["fontes"]}
    for original in dados["fontes"]:
        _erro_fonte_conhecido(original.get("erro"))
        normalizado = _normalizar_instantes(original)
        if "erro" not in normalizado:
            _falhar()
        normalizado["erro"] = estados[original["id"]]["erro"]
        if normalizado != estados[original["id"]]:
            _falhar()
    return projetado


def _ics_comparavel(texto: str) -> tuple:
    # Desfaz somente a dobra RFC 5545; a ordem dos eventos não altera o conteúdo.
    texto = texto.replace("\r\n", "\n").replace("\n ", "").replace("\n\t", "")
    if "\r" in texto:
        _falhar()
    cabecalho, *blocos = texto.split("BEGIN:VEVENT\n")
    if not blocos:
        return (texto, ())
    eventos = []
    for indice, bloco in enumerate(blocos):
        evento, separador, resto = bloco.partition("END:VEVENT\n")
        if not separador or resto != ("END:VCALENDAR\n" if indice == len(blocos) - 1 else ""):
            _falhar()
        eventos.append(evento)
    return cabecalho, tuple(sorted(eventos))


def validar_pasta(pasta: Path) -> dict[str, int]:
    """Confere estado, projeção pública e ICS originais antes de qualquer upload."""
    arquivos = [pasta / nome for nome in ("estado.json", "eventos.json", "eventos.ics")]
    if any(not p.is_file() or p.is_symlink() or p.stat().st_size > LIMITE_BYTES for p in arquivos):
        _falhar()

    def sem_repetidas(pares):
        resultado = {}
        for chave, valor in pares:
            if chave in resultado:
                _falhar()
            resultado[chave] = valor
        return resultado

    estado, publico = [json.loads(p.read_bytes(), object_pairs_hook=sem_repetidas) for p in arquivos[:2]]
    proj_estado = _validar_original(estado, estado=True)
    proj_publico = _validar_original(publico, estado=False)
    for proj in (proj_estado, proj_publico):
        proj["agenda"]["fontes"].sort(key=lambda f: f["id"])
    if proj_estado["agenda"] != proj_publico["agenda"]:
        _falhar()
    if _ics_comparavel(arquivos[2].read_bytes().decode("utf-8")) != _ics_comparavel(proj_estado["ics"]):
        _falhar()
    return {"arquivos": 3, "eventos": len(publico["eventos"]), "fontes": len(publico["fontes"])}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pasta", type=Path, help="valida os três arquivos originais do Release, sem alterá-los")
    args = parser.parse_args()
    try:
        if args.pasta:
            saida = validar_pasta(args.pasta)
        else:
            bruto = sys.stdin.buffer.read(LIMITE_BYTES + 1)
            if len(bruto) > LIMITE_BYTES:
                _falhar()
            saida = projetar_snapshot(json.loads(bruto))
    except Exception:
        print("calendário bloqueado: contrato público ou privacidade inválidos; valores omitidos", file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(saida, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
