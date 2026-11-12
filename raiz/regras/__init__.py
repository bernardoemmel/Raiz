"""Parâmetros legais versionados (E2 passo 1): leitura, consulta por data e por rótulos, versão nomeada.

    from raiz.regras import parametros
    p = parametros()
    p.valor("rl_percentual", "2026-11-12", amazonia_legal=True, vegetacao="floresta")   # 80
    p.escadinha_m(m_fiscal=1.5)                                                       # 8
    p.versao  # 'regras-2026b+<hash do arquivo>' -> vai em cada previsão (regras_versao)

Um valor só é devolvido se a data cair na vigência legal; valor marcado como pendente nunca é devolvido.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PASTA = Path(__file__).with_name("parametros")


class ParametroAusente(LookupError):
    pass


@dataclass(frozen=True)
class Valor:
    parametro: str
    rotulos: dict
    valor: Any
    artigo: str | None
    urn: str | None
    vigencia_inicio: dt.date | None
    vigencia_fim: dt.date | None
    adotado_em: dt.date | None
    pendente: str | None
    observacao: str | None
    nivel: str = "federal"  # federal | estadual (camada estadual, E2 passo 5)
    area: dict | None = None  # área de validade: {"uf": "PI"} ou {"uf": "PA", "zona": "..."}
    norma: str | None = None


def _no_intervalo(x: float, txt: str) -> bool:
    """x está no intervalo escrito como "[a, b)", "(a, inf)" etc.?"""
    txt = txt.strip()
    a, b = (float(t) for t in txt[1:-1].split(","))
    acima = x >= a if txt[0] == "[" else x > a
    abaixo = x <= b if txt[-1] == "]" else x < b
    return acima and abaixo


def _data(v) -> dt.date | None:
    if v is None or isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v))


class Parametros:
    def __init__(self, arquivos: list[Path]):
        self.valores: list[Valor] = []
        self.nomes: dict[str, dict] = {}
        h = hashlib.sha256()
        versoes = set()
        for arq in sorted(arquivos):
            h.update(arq.read_bytes())
            doc = yaml.safe_load(arq.read_text(encoding="utf-8"))
            versoes.add(doc["versao"])
            urn_base = (doc.get("lei_base") or {}).get("urn", "")
            nivel = doc.get("nivel", "federal")
            for nome, p in doc["parametros"].items():
                if nivel == "federal" or nome not in self.nomes:
                    self.nomes[nome] = {k: v for k, v in p.items() if k != "valores"}
                for v in p["valores"]:
                    frag = v.get("urn_frag")
                    self.valores.append(
                        Valor(
                            nome,
                            v.get("rotulos") or {},
                            v.get("valor"),
                            v.get("artigo"),
                            (urn_base + frag) if frag else None,
                            _data(v.get("vigencia_inicio")),
                            _data(v.get("vigencia_fim")),
                            _data(v.get("adotado_em")),
                            v.get("pendente"),
                            v.get("observacao"),
                            nivel,
                            v.get("area") or ({"uf": doc["uf"]} if nivel != "federal" else None),
                            v.get("norma") or (doc.get("norma") or {}).get("nome"),
                        )
                    )
        if len(versoes) != 1:
            raise ValueError(f"arquivos de parâmetros com versões diferentes: {sorted(versoes)}")
        self.versao = f"{versoes.pop()}+{h.hexdigest()[:8]}"

    def candidatos(self, nome: str, data: dt.date | str | None = None, nivel: str = "federal") -> list[Valor]:
        if nome not in self.nomes:
            raise ParametroAusente(nome)
        d = _data(data) or dt.date.today()
        return [
            v
            for v in self.valores
            if v.parametro == nome
            and v.nivel == nivel
            and not v.pendente
            and v.vigencia_inicio is not None
            and v.vigencia_inicio <= d
            and (v.vigencia_fim is None or d <= v.vigencia_fim)
        ]

    def valor(self, nome: str, data: dt.date | str | None = None, **rotulos) -> Any:
        """Valor cujos rótulos batem com os pedidos (rótulo não informado no valor vale para qualquer pedido)."""
        bate = [v for v in self.candidatos(nome, data) if all(rotulos.get(k) == x for k, x in v.rotulos.items())]
        if len(bate) != 1:
            raise ParametroAusente(f"{nome} {rotulos} em {data}: {len(bate)} valores")
        return bate[0].valor

    def registro(self, nome: str, data=None, **rotulos) -> Valor:
        bate = [v for v in self.candidatos(nome, data) if all(rotulos.get(k) == x for k, x in v.rotulos.items())]
        if len(bate) != 1:
            raise ParametroAusente(f"{nome} {rotulos}")
        return bate[0]

    # --- consultas com faixa (módulos fiscais, largura do rio) ----------------------------------------------------

    def _faixa(self, nome: str, chave_ate: str, x: float, data=None, **extra):
        cands = [v for v in self.candidatos(nome, data) if chave_ate in v.rotulos]
        cands = [v for v in cands if all(v.rotulos.get(k, extra[k]) == extra[k] for k in extra)]
        for v in sorted(cands, key=lambda v: v.rotulos[chave_ate]):
            if x <= v.rotulos[chave_ate]:
                return v
        return None

    def _intervalo(self, nome: str, chave: str, x: float, data=None, **extra) -> Valor:
        """Valor cujo rótulo `chave` é um intervalo ("[0, 10)", "(600, inf)") que contém x."""
        for v in self.candidatos(nome, data):
            if any(v.rotulos.get(k) != w for k, w in extra.items()) or chave not in v.rotulos:
                continue
            if _no_intervalo(x, v.rotulos[chave]):
                return v
        raise ParametroAusente(f"{nome}: {chave}={x} fora de todos os intervalos")

    def escadinha_m(self, m_fiscal: float, largura_rio_m: float | None = None, data=None, corpo: str = "rio") -> float:
        """Faixa de APP a recompor em área consolidada (art. 61-A; Decreto 7.830, art. 19, § 4º). Rio acima de 4 MF
        sem largura conhecida: 20 m até 10 MF e o mínimo de 30 m acima, como o motor."""
        if corpo == "nascente":
            return float(self.valor("app_escadinha_m", data, corpo="nascente"))
        if corpo in ("lago", "vereda"):
            v = self._faixa("app_escadinha_m", "mf_ate", m_fiscal, data, corpo=corpo)
            if v is None:
                v = next(
                    c for c in self.candidatos("app_escadinha_m", data) if c.rotulos == {"corpo": corpo, "mf_acima": 4}
                )
            return float(v.valor)
        v = self._faixa("app_escadinha_m", "mf_ate", m_fiscal, data, corpo="rio")
        if v is not None and "largura_rio_ate_m" not in v.rotulos:
            return float(v.valor)
        if m_fiscal <= 10 and (largura_rio_m is None or largura_rio_m <= 10):
            return float(self._faixa("app_escadinha_m", "mf_ate", 10, data, corpo="rio").valor)
        regra = next(
            c.valor for c in self.candidatos("app_escadinha_m", data) if c.rotulos == {"corpo": "rio", "mf_acima": 4}
        )
        if largura_rio_m is None:
            return float(regra["minimo"])
        return float(min(max(largura_rio_m / 2, regra["minimo"]), regra["maximo"]))

    def app_art4_m(
        self,
        corpo: str,
        largura_rio_m: float | None = None,
        superficie_ha: float | None = None,
        urbana: bool = False,
        data=None,
    ) -> float:
        """Faixa de APP fora de área consolidada (art. 4º). Rio sem largura medida: a menor faixa (30 m)."""
        if corpo == "rio":
            return float(self._intervalo("app_rio_m", "largura_rio_m", largura_rio_m or 0.0, data).valor)
        if corpo == "lago":
            if urbana:
                return float(self.valor("app_lago_m", data, zona="urbana"))
            return float(self._intervalo("app_lago_m", "superficie_ha", superficie_ha or 0.0, data, zona="rural").valor)
        return float(self.valor({"nascente": "app_nascente_m", "vereda": "app_vereda_m"}[corpo], data))

    def faixa_app_m(
        self,
        corpo: str,
        m_fiscal: float,
        consolidada: bool,
        largura_rio_m: float | None = None,
        superficie_ha: float | None = None,
        urbana: bool = False,
        data=None,
    ) -> float:
        """Faixa de APP de um trecho: escadinha do art. 61-A se for área consolidada, senão o art. 4º."""
        if consolidada:
            return self.escadinha_m(m_fiscal, largura_rio_m, data, corpo=corpo)
        return self.app_art4_m(corpo, largura_rio_m, superficie_ha, urbana, data)

    def teto_61b(self, m_fiscal: float, data=None) -> float | None:
        """Teto da APP a recompor em fração da área (art. 61-B); None acima de 4 MF (sem teto)."""
        v = self._faixa("app_teto_61b", "mf_ate", m_fiscal, data)
        return None if v is None else v.valor / 100

    def estadual(self, nome: str, uf: str, data=None, zona: str | None = None, **rotulos) -> Valor | None:
        """Regra estadual que vale para a UF (e para a zona, se a regra tiver uma) na data, ou None. Regra pendente
        nunca vale. Duas regras estaduais para o mesmo caso é erro de tabela."""
        if nome not in self.nomes:
            return None
        bate = [
            v
            for v in self.candidatos(nome, data, nivel="estadual")
            if (v.area or {}).get("uf") == uf.upper()
            and (v.area or {}).get("zona") in (None, zona)
            and all(rotulos.get(k) == x for k, x in v.rotulos.items())
        ]
        if len(bate) > 1:
            raise ParametroAusente(f"{nome} {uf} {rotulos}: {len(bate)} regras estaduais")
        return bate[0] if bate else None

    def estaduais_ativas(self, data=None) -> list[Valor]:
        """Regras estaduais em vigor (não pendentes). As regras em Catala precisam ter cada uma delas."""
        return [v for nome in self.nomes for v in self.candidatos(nome, data, nivel="estadual")]

    def rl_percentual(self, uf: str, bioma: str, data=None) -> float:
        """Mesma leitura do motor: na Amazônia Legal, floresta (bioma Amazônia) 80, Cerrado 35, demais 20; fora, 20.
        Uma regra estadual em vigor para a UF e o bioma (camada estadual) vem antes da federal."""
        e = self.estadual("rl_percentual", uf, data, bioma=bioma)
        if e is not None:
            return float(e.valor)
        ufs = self.valor("amazonia_legal_ufs", data)
        if uf.upper() not in ufs:
            return float(self.valor("rl_percentual", data, amazonia_legal=False))
        veg = {"Amazônia": "floresta", "Cerrado": "cerrado"}.get(bioma, "campos_gerais")
        return float(self.valor("rl_percentual", data, amazonia_legal=True, vegetacao=veg))


@lru_cache
def parametros(pasta: Path = PASTA) -> Parametros:
    """Federal (parametros/*.yaml) e camada estadual (parametros/estadual/*.yaml), todos na mesma versão."""
    return Parametros([*pasta.glob("*.yaml"), *pasta.glob("estadual/*.yaml")])


def publicar(con, p: Parametros | None = None) -> tuple[str, bool]:
    """Grava a versão no banco (uma vez; versão já publicada não muda). Devolve (versão, nova)."""
    import json

    from sqlalchemy import text

    p = p or parametros()
    if con.execute(text("select 1 from regras.versao where nome = :n"), {"n": p.versao}).first():
        return p.versao, False
    con.execute(
        text("insert into regras.versao (nome, n_valores) values (:n, :q)"), {"n": p.versao, "q": len(p.valores)}
    )
    for v in p.valores:
        con.execute(
            text("""insert into regras.parametro (versao, parametro, rotulos, valor, artigo, urn_lexml, vigencia_inicio,
                    vigencia_fim, adotado_em, pendente, observacao)
                    values (:ve, :pa, cast(:ro as jsonb), cast(:va as jsonb), :ar, :ur, :vi, :vf, :ad, :pe, :ob)"""),
            dict(
                ve=p.versao,
                pa=v.parametro,
                ro=json.dumps(v.rotulos if v.nivel == "federal" else {**v.rotulos, "nivel": v.nivel, "area": v.area}),
                va=json.dumps(v.valor, default=str),
                ar=v.artigo,
                ur=v.urn,
                vi=v.vigencia_inicio,
                vf=v.vigencia_fim,
                ad=v.adotado_em,
                pe=v.pendente,
                ob=v.observacao,
            ),
        )
    return p.versao, True
