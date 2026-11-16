"""Checagem de licenças das dependências (Python instaladas, npm do front e crates Rust).

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
    (re.compile(r"\bBUSL|\bBSL\b|Business Source", re.I), "BSL"),
    (re.compile(r"\bNC\b|Non[\s-]?Commercial|Não[\s-]?Comercial", re.I), "não comercial"),
    (re.compile(r"Commons Clause", re.I), "Commons Clause"),
    (re.compile(r"Elastic License|\bELv2\b", re.I), "Elastic License"),
    (re.compile(r"\bRSAL|Redis Source Available", re.I), "RSAL"),
]
PROPRIOS = {"raiz", "raiz-iov"}
LGPL = re.compile(r"\bLGPL|Lesser General Public|Library General Public", re.I)
GPL = re.compile(r"\bGPL|General Public License", re.I)


@dataclass
class Pacote:
    nome: str
    versao: str
    licenca: str
    origem: str  # python | npm | cargo
    situacao: str = ""  # ok | lgpl | gpl_servidor | gpl_sem_registro | proibida | desconhecida | conferida
    motivo: str = ""


# Nomes SPDX e os rótulos legados publicados nos metadados Python. Texto desconhecido
# exige conferência; não pode passar só por não conter uma palavra proibida.
PERMITIDAS = re.compile(
    r"(?:MIT(?:-0|-CMU| License)?|0BSD|[234]-Clause BSD License"
    r"|BSD(?:-[234]-Clause(?:-Clear)?| License| [234]-Clause(?: License)?)?"
    r"|Apache(?:-2\.0| 2\.0(?: License)?| Software License| License)?|ISC(?: License \(ISCL\))?"
    r"|MPL-2\.0|Mozilla Public License 2\.0 \(MPL 2\.0\)|OFL-1\.1|SIL Open Font License 1\.1 \(OFL 1\.1\)"
    r"|CNRI-Python|PSF-2\.0|Python-2\.0|Python Software Foundation License|PostgreSQL(?: License)?"
    r"|CC BY(?:-SA)? [234]\.0|CC0-1\.0|CC-BY(?:-SA)?-[234]\.0|Unlicense|The Unlicense \(Unlicense\)|Public Domain"
    r"|Zlib|zlib/libpng License|HPND|Historical Permission Notice and Disclaimer \(HPND\)"
    r"|Unicode-(?:DFS-2016|3\.0)|BlueOak-1\.0\.0|BSL-1\.0|Boost Software License 1\.0 \(BSL-1\.0\))",
    re.I,
)


def _classifica_simples(lic: str) -> tuple[str, str]:
    lic = lic.strip()
    # BSL-1.0 é o identificador SPDX da Boost, diferente de BUSL-1.1 (Business Source).
    if lic in {"BSL-1.0", "Boost Software License 1.0 (BSL-1.0)"}:
        return "ok", ""
    for rx, nome in PROIBIDAS:
        if rx.search(lic):
            return "proibida", nome
    if " WITH " in lic:
        base, excecao = lic.split(" WITH ", 1)
        if excecao not in {"LLVM-exception", "Classpath-exception-2.0", "GCC-exception-3.1"}:
            return "desconhecida", "exceção de licença não conferida"
        return _classifica_simples(base)
    if LGPL.search(lic):
        return "lgpl", "LGPL (biblioteca, permitida)"
    if GPL.search(lic):
        return "gpl", "GPL"
    if PERMITIDAS.fullmatch(lic):
        return "ok", ""
    return "desconhecida", "licença não declarada ou não reconhecida"


def classificar(lic: str) -> tuple[str, str]:
    """Em SPDX, OR permite escolha e AND exige todas. Respeita os parênteses.

    Uma expressão malformada ou um termo desconhecido não autoriza o pacote.
    """
    lic = (lic or "").strip()
    if not lic:
        return "desconhecida", "licença não declarada"
    # Sintaxe dupla antiga de crates: MIT/Apache-2.0.
    lic = re.sub(r"(?<=[A-Za-z0-9.])/(?=[A-Z][A-Za-z0-9.-]+(?:$|[ )]))", " OR ", lic)
    if not re.search(r"\s(?:AND|OR)\s", lic) and not lic.startswith("("):
        return _classifica_simples(lic)
    ordem = {"ok": 0, "lgpl": 1, "gpl": 2, "desconhecida": 3, "proibida": 4}
    tokens = [t.strip() for t in re.split(r"(\(|\)|\s+AND\s+|\s+OR\s+)", lic) if t.strip()]
    pos = 0

    def termo():
        nonlocal pos
        if pos >= len(tokens) or tokens[pos] in {"AND", "OR", ")"}:
            raise ValueError("termo ausente")
        if tokens[pos] == "(":
            pos += 1
            resultado = alternativas()
            if pos >= len(tokens) or tokens[pos] != ")":
                raise ValueError("parêntese ausente")
            pos += 1
            return resultado
        resultado = _classifica_simples(tokens[pos])
        pos += 1
        return resultado

    def conjuncao():
        nonlocal pos
        resultado = termo()
        while pos < len(tokens) and tokens[pos] == "AND":
            pos += 1
            resultado = max(resultado, termo(), key=lambda item: ordem[item[0]])
        return resultado

    def alternativas():
        nonlocal pos
        resultado = conjuncao()
        while pos < len(tokens) and tokens[pos] == "OR":
            pos += 1
            resultado = min(resultado, conjuncao(), key=lambda item: ordem[item[0]])
        return resultado

    try:
        resultado = alternativas()
        if pos != len(tokens):
            raise ValueError("expressão incompleta")
        return resultado
    except ValueError:
        return "desconhecida", "expressão de licença inválida"


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
        if nome and nome not in PROPRIOS and nome not in vistos:  # o próprio produto não entra
            vistos[nome] = Pacote(nome, d.version, _licenca_python(d), "python")
    return sorted(vistos.values(), key=lambda p: p.nome)


def pacotes_npm(lock: Path) -> list[Pacote]:
    """Lê o inventário completo do lock, inclusive pacotes aninhados e outras plataformas.

    Não depende de node_modules, que pode estar ausente ou conter só parte do lock.
    """
    j = json.loads(lock.read_text(encoding="utf-8"))
    if j.get("lockfileVersion") not in {2, 3} or not isinstance(j.get("packages"), dict):
        raise ValueError(f"inventário npm ausente ou incompatível: {lock}")
    out = []
    for caminho, pacote in j["packages"].items():
        if not caminho:
            continue  # o próprio aplicativo
        if pacote.get("link"):
            raise ValueError(f"dependência npm local precisa de conferência: {lock}: {caminho}")
        if "node_modules/" not in caminho or not pacote.get("version"):
            raise ValueError(f"dependência npm incompleta: {lock}: {caminho}")
        nome = pacote.get("name") or caminho.rsplit("node_modules/", 1)[-1]
        out.append(Pacote(nome, pacote["version"], str(pacote.get("license") or ""), "npm"))
    if not out:
        raise ValueError(f"inventário npm vazio: {lock}")
    return sorted(out, key=lambda p: (p.nome, p.versao))


def ler_registro(arquivo: Path) -> dict:
    if not arquivo.exists():
        return {"conferidas": {}, "gpl_no_servidor": {}}
    t = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    return {"conferidas": t.get("conferidas", {}), "gpl_no_servidor": t.get("gpl_no_servidor", {})}


def avaliar(pacotes: list[Pacote], registro: dict) -> list[Pacote]:
    for p in pacotes:
        sit, motivo = classificar(p.licenca)
        if sit == "desconhecida" and p.nome in registro["conferidas"]:
            conferida = str(registro["conferidas"][p.nome])
            sit2, motivo2 = classificar(conferida.split(" (conferido", 1)[0])
            sit, motivo = ("conferida", conferida) if sit2 in {"ok", "lgpl"} else (sit2, motivo2)
        if sit == "gpl":
            if p.origem == "python" and p.nome in registro["gpl_no_servidor"]:
                sit, motivo = "gpl_servidor", str(registro["gpl_no_servidor"][p.nome])
            else:
                sit, motivo = "gpl_sem_registro", "GPL fora de scripts/licencas.toml [gpl_no_servidor]"
        p.situacao, p.motivo = sit, motivo
    return pacotes


def falhas(pacotes: list[Pacote]) -> list[Pacote]:
    return [p for p in pacotes if p.situacao in {"proibida", "gpl_sem_registro", "desconhecida"}]


def pacotes_cargo(manifesto: Path) -> list[Pacote]:
    """Crates Rust da extensão, presos ao lock. Falha se não puder conferir o inventário."""
    import shutil
    import subprocess

    if not manifesto.is_file():
        raise FileNotFoundError(f"manifesto Rust ausente: {manifesto}")
    if shutil.which("cargo") is None:
        raise RuntimeError("cargo não encontrado: não foi possível conferir as licenças Rust")
    r = subprocess.run(
        ["cargo", "metadata", "--locked", "--format-version", "1", "--manifest-path", str(manifesto)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if r.returncode != 0:
        raise RuntimeError("cargo metadata falhou: não foi possível conferir as licenças Rust")
    j = json.loads(r.stdout)
    proprios = PROPRIOS | {"raiz_iov"}
    if not j.get("packages"):
        raise ValueError("inventário Rust vazio")
    return sorted(
        (
            Pacote(p["name"], p["version"], p.get("license") or "", "cargo")
            for p in j["packages"]
            if p["name"] not in proprios
        ),
        key=lambda p: p.nome,
    )
