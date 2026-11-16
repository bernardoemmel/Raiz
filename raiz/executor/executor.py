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
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from raiz.executor.armazem import Armazem, ler_json, por_json, sha256_arquivo
from raiz.logs_seguros import sanitizar_log

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
        self._processamento: dict | None = None

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

    def _saidas_adotaveis(self, t: Tarefa, uf: str, cod: int) -> dict[str, str] | None:
        """Só atribui a versão atual quando todos os arquivos presentes comprovam essa origem."""
        versao = self.versoes()[t.nome]
        if not isinstance(versao, str) or not versao or versao == "publicado":
            return None
        saidas = {}
        for padrao in t.saidas:
            arq = padrao.format(cod=cod)
            meta = self.a.meta(self.chave_saida(uf, arq))
            if meta is None:
                continue
            if not meta.get("sha256") or meta.get("versao") != versao:
                return None
            if meta.get("tarefa") not in (None, t.nome):
                return None
            saidas[arq] = meta["sha256"]
        return saidas if t.saidas[0].format(cod=cod) in saidas else None

    def _adocao_comprovada(self, t: Tarefa, uf: str, cod: int, feito: dict) -> bool:
        """Marcas adotadas antigas não legitimam CSV legado por terem uma assinatura atual."""
        if not feito.get("adotado"):
            return True
        saidas = self._saidas_adotaveis(t, uf, cod)
        return bool(saidas) and feito.get("versao") == self.versoes()[t.nome] and feito.get("saidas") == saidas

    def _saidas_marcadas_comprovadas(self, t: Tarefa, uf: str, feito: dict) -> bool:
        """Uma marca antiga não conclui arquivos trocados durante outra publicação."""
        if feito.get("versao") != self.versoes()[t.nome]:
            return False
        saidas = feito.get("saidas") or {}
        if not saidas:
            return bool(feito.get("vazio") and t.pode_ficar_vazio)
        local = getattr(self.a, "local", self.a)
        for arquivo, digest in saidas.items():
            chave = self.chave_saida(uf, arquivo)
            meta = self.a.meta(chave) or {}
            if meta.get("sha256") != digest or meta.get("versao") != self.versoes()[t.nome]:
                return False
            if hasattr(local, "_p"):
                try:
                    if sha256_arquivo(local._p(chave)) != digest:
                        return False
                except OSError:
                    return False
        return True

    def plano(self, uf: str, cod: int, refazer: bool = False) -> list[str]:
        """Tarefas que rodariam agora (supondo que as anteriores saiam iguais). Para o painel e para decidir."""
        m = self.marca(uf, cod)
        out = []
        for t in self.tarefas:
            feito = m["tarefas"].get(t.nome)
            if any((m["tarefas"].get(d) or {}).get("vazio") for d in t.depende):
                continue
            if (
                refazer
                or not feito
                or feito.get("erro")
                or not self._adocao_comprovada(t, uf, cod, feito)
                or not self._saidas_marcadas_comprovadas(t, uf, feito)
                or feito.get("assinatura") != self.assinatura(t, uf, cod, m)
            ):
                out.append(t.nome)
        return out

    def _conclusao_comprovada(self, uf: str, cod: int) -> bool:
        """Telemetria não confunde marca existente com saídas íntegras da versão atual."""
        marca = self.marca(uf, cod)
        for tarefa in self.tarefas:
            if any((marca["tarefas"].get(d) or {}).get("vazio") for d in tarefa.depende):
                continue
            feito = marca["tarefas"].get(tarefa.nome) or {}
            if feito.get("erro") or not self._saidas_marcadas_comprovadas(tarefa, uf, feito):
                return False
        return True

    # --- um município ---------------------------------------------------------------------------------------------

    def confirmar_integridade(self, uf: str, cod: int) -> bool:
        """Sela só a partição cujas tarefas, versões e bytes foram conferidos."""
        from raiz.executor.integridade import identidade

        marca = self.marca(uf, cod)
        if self.plano(uf, cod) or not self._conclusao_comprovada(uf, cod):
            if marca.pop("integridade", None) is not None:
                por_json(self.a, self.chave_marca(uf, cod), marca)
            return False
        selo = identidade(uf, cod, self.tarefas, marca)
        anterior = marca.get("integridade") or {}
        if any(anterior.get(k) != v for k, v in selo.items()):
            marca["integridade"] = {**selo, "conferido_em": _agora()}
            por_json(self.a, self.chave_marca(uf, cod), marca)
        return True

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
        if self._processamento is None:
            return self._processar_municipio(uf, cod, refazer)
        from raiz.executor.processamento import acompanhar

        with acompanhar(self._processamento, cod) as evento:
            resultado = self._processar_municipio(uf, cod, refazer)
            evento["erro"] = resultado["erro"] is not None
            evento["tarefas_rodadas"] = resultado["rodadas"]
            return resultado

    def _processar_municipio(self, uf: str, cod: int, refazer: bool = False) -> dict:
        uf = uf.upper()
        pasta = self.pasta(uf)
        m = self.marca(uf, cod)
        m.setdefault("tarefas", {})
        if self.plano(uf, cod, refazer) and m.pop("integridade", None) is not None:
            por_json(self.a, self.chave_marca(uf, cod), m)
        res = {"cod": int(cod), "rodadas": [], "puladas": [], "vazio": False, "erro": None}
        for t in self.tarefas:
            if any((m["tarefas"].get(d) or {}).get("vazio") for d in t.depende) or any(
                (m["tarefas"].get(d) or {}).get("erro") for d in t.depende
            ):
                continue
            a = self.assinatura(t, uf, cod, m)
            feito = m["tarefas"].get(t.nome)
            if (
                not refazer
                and feito
                and not feito.get("erro")
                and self._adocao_comprovada(t, uf, cod, feito)
                and self._saidas_marcadas_comprovadas(t, uf, feito)
                and feito.get("assinatura") == a
            ):
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
                erro = sanitizar_log(f"{type(e).__name__}: {e}")[:500]
                m["tarefas"][t.nome] = {"versao": self.versoes()[t.nome], "assinatura": a, "saidas": {},
                                        "data": _agora(), "erro": erro}  # fmt: skip
                res["erro"] = {"tarefa": t.nome, "erro": erro}
                log.warning("%s %s %s: %s\n%s", uf, cod, t.nome, erro, sanitizar_log(traceback.format_exc(limit=3)))
            m["atualizada_em"] = _agora()
            por_json(self.a, self.chave_marca(uf, cod), m)
            if res["erro"]:
                break
        if not self.confirmar_integridade(uf, cod) and res["erro"] is None:
            res["erro"] = {"tarefa": "integridade", "erro": "fontes, versões ou saídas mudaram durante a execução"}
        return res

    # --- um estado ------------------------------------------------------------------------------------------------

    def chave_estado(self, uf: str) -> str:
        return f"estado/{uf.upper()}.json"

    def rodar_uf(
        self,
        uf: str,
        cods: list[int] | None = None,
        refazer: bool = False,
        lanes: int = 1,
        preparar: Callable[[str, list[str]], None] | None = None,
        ate_s: float | None = None,
    ) -> dict:
        """Roda o estado inteiro (ou os municípios pedidos). Retoma: município com a marca em dia é pulado.
        ate_s: para de começar municípios novos depois desse tempo (o GitHub Actions corta o job em 6 horas) e publica
        o que fez; a próxima rodada continua dali. Os municípios em curso têm RAIZ_GRACA_MIN (10) minutos para
        terminar; o que passar disso é interrompido (fica sem marca e roda na próxima vez), para a publicação caber."""
        uf = uf.upper()
        cronometro_estado = time.monotonic()
        limite = time.time() + ate_s if ate_s is not None else None
        if hasattr(self.a, "garantir_uf"):
            self.a.garantir_uf(uf)  # Release: baixa o estado (saídas, marcas e andamento) uma vez
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
        from raiz.executor import processamento

        self._processamento = processamento.contexto(self.trabalho, uf)
        self._processamento["versoes"] = self.versoes()
        sem_tarefa_pendente = set(cods) - set(pendentes)
        prontos_antes = {cod for cod in sem_tarefa_pendente if self.confirmar_integridade(uf, cod)}
        self._processamento["nao_comprovados"] = sem_tarefa_pendente - prontos_antes
        publicacao_bloqueada = False
        ultimo_painel = 0.0
        trava_andamento = threading.Lock()
        estado["publicacao"] = {"pendente": False, "falhas": 0}

        def registrar_andamento(*, forcar_painel=False):
            nonlocal ultimo_painel
            estado["processamento"] = processamento.resumir(self._processamento, cods, prontos_antes)
            por_json(self.a, self.chave_estado(uf), estado)
            habilitado = (os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GITHUB_JOB") == "processar"
                          and os.environ.get("UNIDADE") == self._processamento["unidade"])  # fmt: skip
            if habilitado and (forcar_painel or time.monotonic() - ultimo_painel >= 90):
                ultimo_painel = time.monotonic()
                try:
                    from raiz import RAIZ_REPO
                    from raiz.executor.status_publico import publicar_eventos

                    publicar_eventos(processamento.eventos_publicos(self._processamento, cods, prontos_antes),
                                     repositorio=RAIZ_REPO, tentativas=4)  # fmt: skip
                except Exception as ex:  # noqa: BLE001 - painel não interrompe cálculo nem persistência
                    log.warning("painel de processamento pendente (%s)", type(ex).__name__)

        def andamento(*, forcar_painel=False):
            with trava_andamento:
                registrar_andamento(forcar_painel=forcar_painel)

        def falha_publicacao(ex: Exception):
            nonlocal publicacao_bloqueada
            publicacao_bloqueada = True
            estado["publicacao"].update(pendente=True, erro_tipo=type(ex).__name__, atualizado_em=_agora())
            estado["publicacao"]["falhas"] += 1
            andamento()
            log.warning("publicação pendente (%s); cálculo e marcas locais continuam preservados", type(ex).__name__)

        andamento(forcar_painel=True)
        if preparar and pendentes:
            preparar(uf, sorted({t for c in pendentes[:50] for t in self.plano(uf, c, refazer)}))

        def anota(r: dict):
            estado["feitos"] += 1
            estado["rodados"] += bool(r["rodadas"])
            estado["vazios"] += r["vazio"]
            if r["erro"]:
                estado["erros"].append({"cod": r["cod"], **r["erro"]})
            estado["atualizado_em"] = _agora()
            andamento()
            if hasattr(self.a, "talvez_publicar") and not publicacao_bloqueada:
                try:
                    publicou = self.a.talvez_publicar(uf)
                except Exception as ex:  # noqa: BLE001 - transporte não interrompe tarefas científicas em curso
                    falha_publicacao(ex)
                    return
                if publicou:  # os retratos usam a mesma cadência, em pacotes separados
                    from raiz.aprendizado.retratos import pasta_padrao
                    from raiz.aprendizado.transporte import publicar

                    try:
                        publicar(pasta_padrao(), self.a, uf)
                    except Exception as ex:  # noqa: BLE001 - o passo final do Actions tenta novamente e expõe falha
                        log.warning(
                            "histórico pendente de publicação (%s); retratos locais preservados", type(ex).__name__
                        )

        def no_prazo() -> bool:
            return limite is None or time.time() < limite

        parou = False
        if lanes <= 1 or len(pendentes) <= 1:
            # Mesmo o último município pode levar horas. O pai acompanha o heartbeat
            # sem abrir outro worker e sem esperar o cálculo terminar para publicar.
            parar_monitor = threading.Event()

            def acompanhar_serial():
                while not parar_monitor.wait(processamento.INTERVALO_S):
                    try:
                        andamento()
                    except Exception as ex:  # noqa: BLE001 - telemetria não interrompe ciência
                        log.warning("andamento local pendente (%s)", type(ex).__name__)

            monitor = threading.Thread(target=acompanhar_serial, daemon=True)
            monitor.start()
            try:
                for c in pendentes:
                    if not no_prazo():
                        parou = True
                        break
                    anota(self.processar_municipio(uf, c, refazer))
            finally:
                parar_monitor.set()
                monitor.join()
        else:
            import multiprocessing as mp

            global _EXECUTOR
            _EXECUTOR = self
            graca = float(os.environ.get("RAIZ_GRACA_MIN", 10)) * 60
            with mp.get_context("fork").Pool(lanes, maxtasksperchild=20) as pool:
                it = pool.imap_unordered(_trabalhador, [(uf, c, refazer) for c in pendentes])
                while True:
                    try:
                        espera = 30 if limite is None else min(30, max(limite + graca - time.time(), 0.1))
                        r = it.next(timeout=espera)
                    except StopIteration:
                        break
                    except mp.TimeoutError:
                        andamento()
                        if limite is not None and time.time() >= limite + graca:
                            parou = True
                            pool.terminate()
                            break
                        continue
                    anota(r)
                    if not no_prazo():
                        parou = True
                        pool.terminate()  # os que estavam no meio ficam sem marca e rodam na próxima vez
                        break
        if self.resumo and os.environ.get("RAIZ_SEM_RESUMO") != "1":  # fatia: o resumo do estado inteiro é feito fora
            try:
                f = self.resumo(uf, self.pasta(uf), cods)
                if f is not None and Path(f).exists():
                    meta = {"tarefa": "resumo", "data": _agora(), "uf": uf, "motor_versao": self.motor_versao()}
                    self.a.por(self.chave_saida(uf, Path(f).name), Path(f), meta)
            except Exception as e:  # noqa: BLE001
                estado["erros"].append({"cod": None, "tarefa": "resumo", "erro": sanitizar_log(str(e))[:500]})
        processamento.encerrar(self._processamento)
        estado["situacao"] = "parado_no_prazo" if parou else ("com_erro" if estado["erros"] else "pronto")
        estado["fim"] = _agora()
        estado["segundos_executor"] = round(time.monotonic() - cronometro_estado, 6)
        andamento(forcar_painel=True)
        if hasattr(self.a, "publicar") and getattr(self.a, "token", None):
            try:
                self.a.publicar(uf)
            except Exception as ex:  # noqa: BLE001 - o workflow always preserva checkpoint privado independente
                falha_publicacao(ex)
                self._processamento = None
                raise RuntimeError(
                    "cálculo registrado localmente; publicação pendente, recuperar checkpoint privado"
                ) from None
            estado["publicacao"]["pendente"] = False
            estado["publicacao"]["confirmada_em"] = _agora()
            andamento()
        self._processamento = None
        return estado

    def adotar(self, uf: str, cods: list[int] | None = None) -> dict:
        """Adota saídas sem marca somente quando sua versão corresponde à tarefa atual.

        Arquivos legados, sem versão ou divergentes permanecem intactos e sem
        marca de concluído; o executor poderá recalculá-los pelo fluxo normal.
        """
        uf = uf.upper()
        if hasattr(self.a, "garantir_uf"):
            self.a.garantir_uf(uf)
        if cods is None:
            import re

            cods = sorted({int(m.group(1)) for k in self.a.listar(f"saida/{uf}/")
                           if (m := re.search(r"/imoveis_(\d{7})\.csv$", k))})  # fmt: skip
        out = {"adotados": 0, "ja_tinham_marca": 0, "tarefas": {}}
        for cod in cods:
            if self.a.meta(self.chave_marca(uf, cod)):
                out["ja_tinham_marca"] += 1
                continue
            m = {"uf": uf, "cod": int(cod), "tarefas": {}, "adotado_em": _agora()}
            # a caixa entra na assinatura do funil (alertas na área do município): sem ela, todo alerta novo do estado
            # refaria o funil de todos os municípios adotados
            geo = self.chave_saida(uf, f"geo_{int(cod)}.parquet")
            if self.a.meta(geo) and self.a.baixar(geo, self.pasta(uf) / f"geo_{int(cod)}.parquet"):
                m["caixa"] = _caixa(self.pasta(uf), cod)
            for t in self.tarefas:
                if any(d not in m["tarefas"] for d in t.depende):
                    continue
                saidas = self._saidas_adotaveis(t, uf, cod)
                if saidas is None:
                    continue
                origem = self.a.meta(self.chave_saida(uf, t.saidas[0].format(cod=cod)))
                m["tarefas"][t.nome] = {"versao": self.versoes()[t.nome], "assinatura": self.assinatura(t, uf, cod, m),
                                        "saidas": saidas, "data": origem.get("data"), "adotado": True}  # fmt: skip
                out["tarefas"][t.nome] = out["tarefas"].get(t.nome, 0) + 1
            if m["tarefas"]:
                por_json(self.a, self.chave_marca(uf, cod), m)
                out["adotados"] += 1
        if hasattr(self.a, "publicar") and getattr(self.a, "token", None) and out["adotados"]:
            self.a.publicar(uf)
        return out


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
    """sha256 (arquivo pequeno do espelho) ou tamanho (raster grande, arquivo nacional), ou None se não existe.
    Sem a data do arquivo: no GitHub Actions o cache é baixado de novo e a data muda sem o conteúdo mudar, o que
    refaria o estado inteiro. Coleção ou ano novo muda o nome do arquivo; exportação nova muda o tamanho."""
    p = Path(p)
    if not p.exists():
        return None
    if conteudo:
        return sha256_arquivo(p)
    return str(p.stat().st_size)


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
