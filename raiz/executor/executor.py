"""Executor do motor dentro do produto: roda um estado município a município, retoma de onde parou e refaz só o que
mudou.

Para cada município e tarefa (na ordem das dependências) a marca guarda a versão da tarefa, a assinatura das
entradas e o sha256 de cada saída. A assinatura junta:
  - a versão da tarefa (hash do código de que ela depende, e da regra quando há uma);
  - as fontes externas do município (CAR, SIGEF e embargos do espelho, rasters do MapBiomas do estado...);
  - o sha256 das saídas das tarefas de que ela depende.
A tarefa só roda de novo quando a assinatura muda. Se ela roda e a saída sai igual, as seguintes não rodam: a
mudança só se propaga até onde ela muda alguma coisa. A marca é gravada no armazém depois de CADA tarefa, depois das
saídas: matar o processo no meio perde no máximo a tarefa em curso.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import socket
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from raiz.executor.armazem import Armazem, ler_json, por_json, sha256_arquivo

log = logging.getLogger(__name__)


@dataclass
class Tarefa:
    nome: str
    depende: tuple[str, ...]
    saidas: tuple[str, ...]  # padrões com {cod}; a primeira é a principal
    versao: Callable[[], str]
    rodar: Callable[[str, int, Path], None]
    externas: Callable[[str, int, dict], dict] = field(default=lambda uf, cod, marca: {})
    pode_ficar_vazio: bool = False  # funil: município sem imóvel rural ativo (nada depois roda)


def _agora() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def ordenar(tarefas: list[Tarefa]) -> list[Tarefa]:
    """Ordem topológica (dependência antes de quem depende); erro se houver ciclo ou dependência desconhecida."""
    por = {t.nome: t for t in tarefas}
    feito, out, vendo = set(), [], set()

    def visita(t: Tarefa):
        if t.nome in feito:
            return
        if t.nome in vendo:
            raise ValueError(f"ciclo nas tarefas em {t.nome}")
        vendo.add(t.nome)
        for d in t.depende:
            if d not in por:
                raise ValueError(f"{t.nome} depende de {d}, que não existe")
            visita(por[d])
        vendo.discard(t.nome)
        feito.add(t.nome)
        out.append(t)

    for t in tarefas:
        visita(t)
    return out


class Executor:
    def __init__(self, armazem: Armazem, pasta_trabalho: Path, tarefas: list[Tarefa],
                 municipios: Callable[[str], list[int]] | None = None,
                 resumo: Callable[[str, Path, list[int]], Path | None] | None = None,
                 motor_versao: Callable[[], str] | None = None):  # fmt: skip
        self.a = armazem
        self.trabalho = Path(pasta_trabalho)
        self.tarefas = ordenar(tarefas)
        self.municipios = municipios
        self.resumo = resumo
        self.motor_versao = motor_versao or (lambda: "")
        self._versoes: dict[str, str] | None = None

    # --- versões e marcas ---------------------------------------------------------------------------------------

    def versoes(self) -> dict[str, str]:
        if self._versoes is None:
            self._versoes = {t.nome: t.versao() for t in self.tarefas}
        return self._versoes

    def pasta(self, uf: str) -> Path:
        p = self.trabalho / "saida" / uf.upper()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @staticmethod
    def chave_marca(uf: str, cod: int) -> str:
        return f"marcas/{uf.upper()}/{int(cod)}.json"

    @staticmethod
    def chave_saida(uf: str, arquivo: str) -> str:
        return f"saida/{uf.upper()}/{arquivo}"

    def marca(self, uf: str, cod: int) -> dict:
        return ler_json(self.a, self.chave_marca(uf, cod)) or {"uf": uf.upper(), "cod": int(cod), "tarefas": {}}

    def assinatura(self, t: Tarefa, uf: str, cod: int, marca: dict) -> str:
        entradas = {d: (marca["tarefas"].get(d) or {}).get("saidas") for d in t.depende}
        corpo = {"versao": self.versoes()[t.nome], "externas": t.externas(uf, cod, marca), "entradas": entradas}
        return hashlib.sha256(json.dumps(corpo, sort_keys=True, default=str).encode()).hexdigest()

    def plano(self, uf: str, cod: int, refazer: bool = False) -> list[str]:
        """Tarefas que rodariam agora (supondo que as anteriores saiam iguais). Para o painel e para decidir."""
        m = self.marca(uf, cod)
        out = []
        for t in self.tarefas:
            feito = m["tarefas"].get(t.nome)
            if any((m["tarefas"].get(d) or {}).get("vazio") for d in t.depende):
                continue
            if refazer or not feito or feito.get("erro") or feito.get("assinatura") != self.assinatura(t, uf, cod, m):
                out.append(t.nome)
        return out

    # --- um município ---------------------------------------------------------------------------------------------

    def _garantir_local(self, uf: str, marca: dict, t: Tarefa) -> None:
        """As saídas das tarefas anteriores precisam estar na pasta de trabalho (a máquina pode ter reiniciado)."""
        pasta = self.pasta(uf)
        for d in t.depende:
            for arq, sha in ((marca["tarefas"].get(d) or {}).get("saidas") or {}).items():
                p = pasta / arq
                if not p.exists() or sha256_arquivo(p) != sha:
                    if not self.a.baixar(self.chave_saida(uf, arq), p):
                        raise FileNotFoundError(f"{arq} não está no armazém ({self.a.descricao})")

    def processar_municipio(self, uf: str, cod: int, refazer: bool = False) -> dict:
        uf = uf.upper()
        pasta = self.pasta(uf)
        m = self.marca(uf, cod)
        m.setdefault("tarefas", {})
        res = {"cod": int(cod), "rodadas": [], "puladas": [], "vazio": False, "erro": None}
        for t in self.tarefas:
            if any((m["tarefas"].get(d) or {}).get("vazio") for d in t.depende) or any(
                (m["tarefas"].get(d) or {}).get("erro") for d in t.depende
            ):
                continue
            a = self.assinatura(t, uf, cod, m)
            feito = m["tarefas"].get(t.nome)
            if not refazer and feito and not feito.get("erro") and feito.get("assinatura") == a:
                res["puladas"].append(t.nome)
                continue
            try:
                self._garantir_local(uf, m, t)
                for padrao in t.saidas:  # saída velha não pode passar por nova se a tarefa falhar
                    (pasta / padrao.format(cod=cod)).unlink(missing_ok=True)
                t0 = time.time()
                t.rodar(uf, int(cod), pasta)
                saidas = {}
                for padrao in t.saidas:
                    p = pasta / padrao.format(cod=cod)
                    if p.exists():
                        meta = {"tarefa": t.nome, "versao": self.versoes()[t.nome], "data": _agora(), "uf": uf,
                                "cod_municipio": str(cod), "motor_versao": self.motor_versao()}  # fmt: skip
                        saidas[p.name] = self.a.por(self.chave_saida(uf, p.name), p, meta)["sha256"]
                principal = t.saidas[0].format(cod=cod)
                vazio = principal not in saidas
                if vazio and not t.pode_ficar_vazio:
                    raise RuntimeError(f"{t.nome} não gerou {principal}")
                m["tarefas"][t.nome] = {
                    "versao": self.versoes()[t.nome],
                    "assinatura": a,
                    "saidas": saidas,
                    "data": _agora(),
                    "segundos": round(time.time() - t0, 1),
                    "vazio": vazio,
                }
                if t.nome == self.tarefas[0].nome and not vazio:
                    m["caixa"] = _caixa(pasta, cod)
                res["rodadas"].append(t.nome)
                res["vazio"] = res["vazio"] or vazio
            except Exception as e:  # noqa: BLE001 - registra e segue para o próximo município
                m["tarefas"][t.nome] = {"versao": self.versoes()[t.nome], "assinatura": a, "saidas": {},
                                        "data": _agora(), "erro": f"{type(e).__name__}: {e}"[:500]}  # fmt: skip
                res["erro"] = {"tarefa": t.nome, "erro": f"{type(e).__name__}: {e}"[:500]}
                log.warning("%s %s %s: %s\n%s", uf, cod, t.nome, e, traceback.format_exc(limit=3))
            m["atualizada_em"] = _agora()
            por_json(self.a, self.chave_marca(uf, cod), m)
            if res["erro"]:
                break
        return res

    # --- um estado ------------------------------------------------------------------------------------------------

    def chave_estado(self, uf: str) -> str:
        return f"estado/{uf.upper()}.json"

    def rodar_uf(self, uf: str, cods: list[int] | None = None, refazer: bool = False, lanes: int = 1,
                 preparar: Callable[[str, list[str]], None] | None = None) -> dict:  # fmt: skip
        """Roda o estado inteiro (ou os municípios pedidos). Retoma: município com a marca em dia é pulado."""
        uf = uf.upper()
        cods = [int(c) for c in (cods or (self.municipios(uf) if self.municipios else []))]
        estado = {
            "uf": uf,
            "situacao": "em_andamento",
            "inicio": _agora(),
            "atualizado_em": _agora(),
            "total": len(cods),
            "feitos": 0,
            "rodados": 0,
            "vazios": 0,
            "erros": [],
            "refazer": refazer,
            "versoes": self.versoes(),
            "motor_versao": self.motor_versao(),
            "maquina": socket.gethostname(),
        }
        anterior = ler_json(self.a, self.chave_estado(uf)) or {}
        if anterior.get("situacao") == "em_andamento":
            estado["retomado_de"] = anterior.get("inicio")
        por_json(self.a, self.chave_estado(uf), estado)
        pendentes = [c for c in cods if refazer or self.plano(uf, c)]
        estado["feitos"] = len(cods) - len(pendentes)
        if preparar and pendentes:
            preparar(uf, sorted({t for c in pendentes[:50] for t in self.plano(uf, c, refazer)}))

        def anota(r: dict):
            estado["feitos"] += 1
            estado["rodados"] += bool(r["rodadas"])
            estado["vazios"] += r["vazio"]
            if r["erro"]:
                estado["erros"].append({"cod": r["cod"], **r["erro"]})
            estado["atualizado_em"] = _agora()
            por_json(self.a, self.chave_estado(uf), estado)

        if lanes <= 1 or len(pendentes) <= 1:
            for c in pendentes:
                anota(self.processar_municipio(uf, c, refazer))
        else:
            import multiprocessing as mp

            global _EXECUTOR
            _EXECUTOR = self
            with mp.get_context("fork").Pool(lanes, maxtasksperchild=20) as pool:
                for r in pool.imap_unordered(_trabalhador, [(uf, c, refazer) for c in pendentes]):
                    anota(r)
        if self.resumo:
            try:
                f = self.resumo(uf, self.pasta(uf), cods)
                if f is not None and Path(f).exists():
                    meta = {"tarefa": "resumo", "data": _agora(), "uf": uf, "motor_versao": self.motor_versao()}
                    self.a.por(self.chave_saida(uf, Path(f).name), Path(f), meta)
            except Exception as e:  # noqa: BLE001
                estado["erros"].append({"cod": None, "tarefa": "resumo", "erro": str(e)[:500]})
        estado["situacao"] = "com_erro" if estado["erros"] else "pronto"
        estado["fim"] = _agora()
        por_json(self.a, self.chave_estado(uf), estado)
        return estado


_EXECUTOR: Executor | None = None


def _trabalhador(args):
    uf, cod, refazer = args
    return _EXECUTOR.processar_municipio(uf, cod, refazer)


def _caixa(pasta: Path, cod: int) -> list[float] | None:
    """Caixa do município (dos polígonos do CAR), para as fontes recortadas por município."""
    f = pasta / f"geo_{cod}.parquet"
    if not f.exists():
        return None
    try:
        import geopandas as gpd

        g = gpd.read_parquet(f)
        g = g.set_crs(4674) if g.crs is None else g.to_crs(4674)
        return [round(float(x), 5) for x in g.total_bounds]
    except Exception:  # noqa: BLE001
        return None


def assinatura_arquivo(p: Path, conteudo: bool = False) -> str | None:
    """sha256 (arquivo pequeno do espelho) ou tamanho+data (raster grande), ou None se não existe."""
    p = Path(p)
    if not p.exists():
        return None
    if conteudo:
        return sha256_arquivo(p)
    st = p.stat()
    return f"{st.st_size}:{int(st.st_mtime)}"


def sha_texto(*partes: str) -> str:
    h = hashlib.sha256()
    for x in partes:
        h.update(str(x).encode())
        h.update(b"\0")
    return h.hexdigest()


def env_lanes(padrao: int = 1) -> int:
    try:
        return max(int(os.environ.get("LANES", padrao)), 1)
    except ValueError:
        return padrao
