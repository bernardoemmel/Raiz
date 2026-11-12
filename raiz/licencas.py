"""Checagem de licenças das dependências (Python instaladas e npm em web/node_modules).

Regra do CLAUDE.md: proibidas AGPL, EUPL, SSPL, BSL e qualquer não comercial (NC). GPL só em serviço no servidor,
nunca embutido no produto distribuído: cada pacote GPL precisa estar em scripts/licencas.toml [gpl_no_servidor] com o
motivo. Também barramos licenças que não são abertas (Commons Clause, Elastic License, RSAL). Pacote sem licença
declarada precisa ser conferido à mão e registrado em [conferidas].
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

PROIBIDAS = [
    (re.compile(r"\bAGPL|Affero", re.I), "AGPL"),
    (re.compile(r"\bEUPL|European Union Public", re.I), "EUPL"),
    (re.compile(r"\bSSPL|Server Side Public", re.I), "SSPL"),
    (re.compile(r"\bBUSL|\bBSL-1|Business Source", re.I), "BSL"),
    (re.compile(r"-NC\b|-NC-|Non-?Commercial|NãoComercial", re.I), "não comercial"),
    (re.compile(r"Commons Clause", re.I), "Commons Clause"),
    (re.compile(r"Elastic License|\bELv2\b", re.I), "Elastic License"),
    (re.compile(r"\bRSAL|Redis Source Available", re.I), "RSAL"),
]
LGPL = re.compile(r"\bLGPL|Lesser General Public|Library General Public", re.I)
GPL = re.compile(r"\bGPL|General Public License", re.I)


@dataclass
class Pacote:
    nome: str
    versao: str
    licenca: str
    origem: str  # python | npm
    situacao: str = ""  # ok | lgpl | gpl_servidor | gpl_sem_registro | proibida | desconhecida | conferida
    motivo: str = ""


def _classifica_simples(lic: str) -> tuple[str, str]:
    for rx, nome in PROIBIDAS:
        if rx.search(lic):
            return "proibida", nome
    if LGPL.search(lic):
        return "lgpl", "LGPL (biblioteca, permitida)"
    if GPL.search(lic):
        return "gpl", "GPL"
    return "ok", ""


def classificar(lic: str) -> tuple[str, str]:
    """Classifica uma licença (texto curto ou expressão SPDX). Em 'A OR B' vale a melhor opção; em 'A AND B', a
    pior."""
    lic = (lic or "").strip()
    if not lic or lic.upper() in {"UNKNOWN", "NONE", "UNLICENSED", "SEE LICENSE IN LICENSE", "OTHER/PROPRIETARY"}:
        return "desconhecida", "licença não declarada"
    ordem = {"ok": 0, "lgpl": 1, "gpl": 2, "proibida": 3}
    melhor = None
    for alt in re.split(r"\s+OR\s+|\s*/\s*(?=[A-Z])", lic.replace("(", " ").replace(")", " ")):
        partes = [_classifica_simples(p) for p in re.split(r"\s+AND\s+", alt) if p.strip()]
        if not partes:
            continue
        pior = max(partes, key=lambda x: ordem[x[0]])
        if melhor is None or ordem[pior[0]] < ordem[melhor[0]]:
            melhor = pior
    return melhor or ("desconhecida", "licença não declarada")


def _licenca_python(d: metadata.Distribution) -> str:
    m = d.metadata
    if m.get("License-Expression"):
        return m["License-Expression"]
    cls = [c.split("::")[-1].strip() for c in (m.get_all("Classifier") or []) if c.startswith("License ::")]
    cls = [c for c in cls if c not in {"OSI Approved", "Other/Proprietary License"}]
    if cls:
        return " OR ".join(cls)
    lic = (m.get("License") or "").strip()
    # alguns pacotes põem o texto inteiro da licença; o texto da GPL-3 cita a Affero, então só vale a 1ª linha
    return lic.splitlines()[0][:200] if lic else ""


def pacotes_python() -> list[Pacote]:
    vistos = {}
    for d in metadata.distributions():
        nome = (d.metadata.get("Name") or "").lower()
        if nome and nome != "raiz" and nome not in vistos:  # o próprio produto não entra
            vistos[nome] = Pacote(nome, d.version, _licenca_python(d), "python")
    return sorted(vistos.values(), key=lambda p: p.nome)


def pacotes_npm(node_modules: Path) -> list[Pacote]:
    out = []
    if not node_modules.is_dir():
        return out
    for pj in list(node_modules.glob("*/package.json")) + list(node_modules.glob("@*/*/package.json")):
        try:
            j = json.loads(pj.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        lic = j.get("license") or ""
        if isinstance(lic, dict):
            lic = lic.get("type", "")
        if not lic and isinstance(j.get("licenses"), list):
            lic = " OR ".join(x.get("type", "") if isinstance(x, dict) else str(x) for x in j["licenses"])
        out.append(Pacote(j.get("name", pj.parent.name), j.get("version", ""), str(lic), "npm"))
    return sorted(out, key=lambda p: p.nome)


def ler_registro(arquivo: Path) -> dict:
    if not arquivo.exists():
        return {"conferidas": {}, "gpl_no_servidor": {}}
    t = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    return {"conferidas": t.get("conferidas", {}), "gpl_no_servidor": t.get("gpl_no_servidor", {})}


def avaliar(pacotes: list[Pacote], registro: dict) -> list[Pacote]:
    for p in pacotes:
        sit, motivo = classificar(p.licenca)
        if p.nome in registro["conferidas"]:
            conferida = str(registro["conferidas"][p.nome])
            sit2, motivo2 = classificar(conferida)
            sit, motivo = ("conferida", conferida) if sit2 in {"ok", "lgpl"} else (sit2, motivo2)
        if sit == "gpl":
            if p.nome in registro["gpl_no_servidor"]:
                sit, motivo = "gpl_servidor", str(registro["gpl_no_servidor"][p.nome])
            else:
                sit, motivo = "gpl_sem_registro", "GPL fora de scripts/licencas.toml [gpl_no_servidor]"
        p.situacao, p.motivo = sit, motivo
    return pacotes


def falhas(pacotes: list[Pacote]) -> list[Pacote]:
    return [p for p in pacotes if p.situacao in {"proibida", "gpl_sem_registro", "desconhecida"}]
