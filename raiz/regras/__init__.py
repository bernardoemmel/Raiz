"""Parâmetros legais versionados (E2 passo 1): leitura, consulta por data e por rótulos, versão nomeada.

    from raiz.regras import parametros
    p = parametros()
    p.valor("rl_percentual", "2026-11-12", amazonia_legal=True, vegetacao="floresta")   # 80
    p.escadinha_m(m_fiscal=1.5)                                                       # 8
    p.versao  # 'regras-2026a+<hash do arquivo>' -> vai em cada previsão (regras_versao)

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
            for nome, p in doc["parametros"].items():
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
                        )
                    )
        if len(versoes) != 1:
            raise ValueError(f"arquivos de parâmetros com versões diferentes: {sorted(versoes)}")
        self.versao = f"{versoes.pop()}+{h.hexdigest()[:8]}"

    def candidatos(self, nome: str, data: dt.date | str | None = None) -> list[Valor]:
        if nome not in self.nomes:
            raise ParametroAusente(nome)
        d = _data(data) or dt.date.today()
        return [
            v
            for v in self.valores
            if v.parametro == nome
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

    def escadinha_m(self, m_fiscal: float, largura_rio_m: float | None = None, data=None) -> float:
        """Faixa de APP a recompor em área consolidada (art. 61-A). Acima de 4 MF sem largura conhecida: 20 m até
        10 MF (rio até 10 m) e o mínimo de 30 m acima de 10 MF, como o motor."""
        v = self._faixa("app_escadinha_m", "mf_ate", m_fiscal, data)
        if v is not None and "largura_rio_ate_m" not in v.rotulos:
            return float(v.valor)
        if m_fiscal <= 10 and (largura_rio_m is None or largura_rio_m <= 10):
            return float(self._faixa("app_escadinha_m", "mf_ate", 10, data).valor)
        regra = next(c.valor for c in self.candidatos("app_escadinha_m", data) if "mf_acima" in c.rotulos)
        if largura_rio_m is None:
            return float(regra["minimo"])
        return float(min(max(largura_rio_m / 2, regra["minimo"]), regra["maximo"]))

    def teto_61b(self, m_fiscal: float, data=None) -> float | None:
        """Teto da APP a recompor em fração da área (art. 61-B); None acima de 4 MF (sem teto)."""
        v = self._faixa("app_teto_61b", "mf_ate", m_fiscal, data)
        return None if v is None else v.valor / 100

    def rl_percentual(self, uf: str, bioma: str, data=None) -> float:
        """Mesma leitura do motor: na Amazônia Legal, floresta (bioma Amazônia) 80, Cerrado 35, demais 20; fora, 20."""
        ufs = self.valor("amazonia_legal_ufs", data)
        if uf.upper() not in ufs:
            return float(self.valor("rl_percentual", data, amazonia_legal=False))
        veg = {"Amazônia": "floresta", "Cerrado": "cerrado"}.get(bioma, "campos_gerais")
        return float(self.valor("rl_percentual", data, amazonia_legal=True, vegetacao=veg))


@lru_cache
def parametros(pasta: Path = PASTA) -> Parametros:
    return Parametros(list(pasta.glob("*.yaml")))


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
                ro=json.dumps(v.rotulos),
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
