"""Painel vivo via uma ref pública exclusiva, com compare-and-swap e sem histórico.

O JSON contém eventos de MUNICÍPIOS (IBGE), nunca registros de imóveis. O resumo
deduplica tentativas por município antes de contar os 27 estados. Esta ref não
dispara processamento e não modifica main, releases, reservas ou tarefas.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

from raiz.executor.processamento_publico import CONTAGENS, MAX_LEASE, UFS, _data, estado_publico

REF = "refs/heads/status-processamento"
ARQUIVO = "processamento.json"
SITUACOES = {
    "pronto": "prontos",
    "em_execucao": "em_execucao",
    "com_erro": "com_erro",
    "pendente": "pendentes",
    "desconhecido": "desconhecidos",
}
CAMPOS = {
    "cod_ibge",
    "situacao",
    "unidade",
    "run_id",
    "run_attempt",
    "observado_em",
    "ultima_mudanca_em",
    "valido_ate",
}


@lru_cache(maxsize=1)
def municipios_ibge() -> dict[str, frozenset[str]]:
    from raiz.executor.tarefas import COD_UF, LISTA

    por_codigo = {str(cod): uf for uf, cod in COD_UF.items()}
    municipios = {uf: set() for uf in UFS}
    with LISTA.open(encoding="utf-8") as arquivo:
        for linha in csv.DictReader(arquivo):
            cod, uf = linha["codigo_ibge"], por_codigo[linha["codigo_uf"]]
            if not re.fullmatch(r"[0-9]{7}", cod) or cod[:2] != linha["codigo_uf"] or cod in municipios[uf]:
                raise ValueError("lista municipal inválida")
            municipios[uf].add(cod)
    if any(not cods for cods in municipios.values()):
        raise ValueError("lista municipal incompleta")
    return {uf: frozenset(cods) for uf, cods in municipios.items()}


def validar_eventos(eventos: object, *, agora: dt.datetime) -> list[dict]:
    """Recusa campos extras ANTES de qualquer operação de publicação."""
    ibge = municipios_ibge()
    if not isinstance(eventos, list) or len(eventos) > sum(map(len, ibge.values())):
        raise ValueError("eventos municipais fora do contrato público")
    vistos, limpos = set(), []
    for evento in eventos:
        if not isinstance(evento, dict) or set(evento) != CAMPOS:
            raise ValueError("evento com campos fora do contrato público")
        cod, unidade, run = evento["cod_ibge"], evento["unidade"], evento["run_id"]
        if not isinstance(cod, str) or not isinstance(unidade, str) or not isinstance(run, str):
            raise ValueError("identificação operacional inválida")
        uf = unidade[:2]
        if uf not in ibge or cod not in ibge[uf] or not re.fullmatch(rf"{uf}(?:-[1-9][0-9]?)?", unidade):
            raise ValueError("município ou unidade fora da lista oficial")
        if cod in vistos:
            raise ValueError("observação municipal duplicada")
        vistos.add(cod)
        if not isinstance(evento["situacao"], str) or evento["situacao"] not in SITUACOES:
            raise ValueError("situação operacional inválida")
        if not re.fullmatch(r"[1-9][0-9]{0,19}", run):
            raise ValueError("situação ou rodada inválida")
        if type(evento["run_attempt"]) is not int or not 1 <= evento["run_attempt"] <= 1000:
            raise ValueError("tentativa inválida")
        tempos = {k: _data(evento[k]) for k in ("observado_em", "ultima_mudanca_em", "valido_ate")}
        observado, mudanca, validade = tempos.values()
        if any(t is None for t in tempos.values()):
            raise ValueError("evento municipal sem tempo verificável")
        if not mudanca <= observado < validade or validade - observado > MAX_LEASE:
            raise ValueError("prazo de observação inválido")
        if observado > agora + dt.timedelta(seconds=30):
            raise ValueError("observação municipal no futuro")
        # Início/fim podem ocorrer no mesmo segundo; preservar a precisão evita
        # empatar observações distintas e favorece o evento realmente mais novo.
        limpos.append({**evento, **{k: v.isoformat() for k, v in tempos.items()}})
    return sorted(limpos, key=lambda e: e["cod_ibge"])


def _ordem(evento: dict) -> tuple:
    # Uma rodada antiga ainda viva não sobrepõe uma tentativa mais recente.
    return int(evento["run_id"]), evento["run_attempt"], _data(evento["observado_em"])


def juntar_eventos(anteriores: list[dict], novos: list[dict]) -> list[dict]:
    unidos = {e["cod_ibge"]: e for e in anteriores}
    for novo in novos:
        anterior = unidos.get(novo["cod_ibge"])
        if anterior is None or _ordem(novo) > _ordem(anterior):
            unidos[novo["cod_ibge"]] = novo
        elif _ordem(novo) == _ordem(anterior) and novo != anterior:
            raise ValueError("observações municipais conflitantes no mesmo instante")
    return [unidos[cod] for cod in sorted(unidos)]


def documento(eventos: list[dict], *, agora: dt.datetime) -> dict:
    eventos = validar_eventos(eventos, agora=agora)
    por_uf = {uf: [] for uf in UFS}
    for evento in eventos:
        por_uf[evento["unidade"][:2]].append(evento)
    estados = []
    for uf, cods in municipios_ibge().items():
        dados = por_uf[uf]
        if not dados:
            estados.append(estado_publico(uf, None, agora=agora))
            continue
        contagem = dict.fromkeys(CONTAGENS, 0)
        contagem["desconhecidos"] = len(cods) - len(dados)
        for evento in dados:
            situacao = evento["situacao"]
            if situacao == "em_execucao" and _data(evento["valido_ate"]) <= agora:
                situacao = "desconhecido"
            contagem[SITUACOES[situacao]] += 1
        observado = max(_data(e["observado_em"]) for e in dados)
        vivos = [
            _data(e["valido_ate"]) for e in dados if e["situacao"] == "em_execucao" and _data(e["valido_ate"]) > agora
        ]
        validade = min(vivos) if vivos else observado + dt.timedelta(seconds=120)
        # O limite estadual nunca ultrapassa a menor validade dos workers vivos.
        validade = min(validade, observado + dt.timedelta(seconds=120))
        agregado = {
            "versao": 1,
            "escopo": "uf",
            "unidade": uf,
            "municipios_total": len(cods),
            "municipios": contagem,
            "observado_em": observado.isoformat(),
            "ultima_mudanca_em": max(_data(e["ultima_mudanca_em"]) for e in dados).isoformat(),
            "valido_ate": validade.isoformat(),
        }
        estados.append(estado_publico(uf, agregado, agora=agora))
    return {"versao": 1, "gerado_em": agora.isoformat(), "estados": estados, "eventos": eventos}


def _ler_documento(bruto: str, *, agora: dt.datetime) -> list[dict]:
    try:
        dado = json.loads(bruto)
    except (ValueError, TypeError) as ex:
        raise ValueError("snapshot público inválido") from ex
    if not isinstance(dado, dict) or set(dado) != {"versao", "gerado_em", "estados", "eventos"}:
        raise ValueError("snapshot público com campos desconhecidos")
    gerado = _data(dado["gerado_em"])
    if (
        type(dado["versao"]) is not int
        or dado["versao"] != 1
        or gerado is None
        or gerado > agora + dt.timedelta(seconds=30)
    ):
        raise ValueError("snapshot público sem versão ou tempo verificável")
    eventos = validar_eventos(dado["eventos"], agora=agora)
    if documento(eventos, agora=gerado)["estados"] != dado["estados"]:
        raise ValueError("resumo público diverge dos eventos municipais")
    return eventos


class RepositorioStatus:
    """Operações Git limitadas à ref dedicada; sem checkout, índice ou FETCH_HEAD."""

    def __init__(self, pasta: Path):
        self.pasta = pasta
        origem = self._git(["remote", "get-url", "origin"]).stdout.strip()
        if not re.fullmatch(r"(?:https://github\.com/|git@github\.com:)bernardoemmel/raiz(?:\.git)?", origem, re.I):
            raise ValueError("origem do painel fora do repositório autorizado")

    def _git(self, args: list[str], entrada: str | None = None, *, exigir=True):
        ambiente = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Raíz",
            "GIT_AUTHOR_EMAIL": "raiz@users.noreply.github.com",
            "GIT_COMMITTER_NAME": "Raíz",
            "GIT_COMMITTER_EMAIL": "raiz@users.noreply.github.com",
            "GIT_TERMINAL_PROMPT": "0",
        }
        try:
            r = subprocess.run(
                ["git", "-C", str(self.pasta), *args],
                input=entrada,
                capture_output=True,
                text=True,
                timeout=60,
                env=ambiente,
            )
        except (OSError, subprocess.TimeoutExpired) as ex:
            raise RuntimeError("transporte do painel indisponível") from ex
        if exigir and r.returncode:
            raise RuntimeError("transporte do painel indisponível")
        return r

    def _referencia(self) -> str:
        r = self._git(["ls-remote", "--exit-code", "origin", REF], exigir=False)
        if r.returncode == 2 and not r.stdout.strip():
            return ""
        if r.returncode or not re.fullmatch(rf"[a-f0-9]{{40}}\s+{re.escape(REF)}\s*", r.stdout):
            raise RuntimeError("referência do painel não confirmada")
        return r.stdout.split()[0]

    def ler(self, *, agora: dt.datetime) -> tuple[str, list[dict]]:
        sha = self._referencia()
        if not sha:
            return "", []
        self._git(["fetch", "--no-tags", "--no-write-fetch-head", "origin", sha])
        arvore = self._git(["ls-tree", sha]).stdout
        if not re.fullmatch(rf"100644 blob [a-f0-9]{{40}}\t{ARQUIVO}\n", arvore):
            raise ValueError("ref do painel contém arquivos fora do contrato")
        bruto = self._git(["show", f"{sha}:{ARQUIVO}"]).stdout
        if len(bruto) > 4_000_000:
            raise ValueError("snapshot público excede o limite municipal")
        return sha, _ler_documento(bruto, agora=agora)

    def trocar(self, anterior: str, dado: dict) -> bool:
        bruto = json.dumps(dado, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        blob = self._git(["hash-object", "-w", "--stdin"], bruto).stdout.strip()
        arvore = self._git(["mktree"], f"100644 blob {blob}\t{ARQUIVO}\n").stdout.strip()
        # Sem -p: cada snapshot substitui o anterior sem acumular histórico público.
        commit = self._git(["commit-tree", arvore], "Atualiza contagens municipais do processamento\n").stdout.strip()
        r = self._git(
            ["push", "--porcelain", f"--force-with-lease={REF}:{anterior}", "origin", f"{commit}:{REF}"],
            exigir=False,
        )
        if r.returncode == 0:
            return True
        # Corrida depois do anúncio de refs é recusada pelo servidor com mensagem
        # diferente de "stale info". Consultar a ref confirma o CAS sem analisar
        # stderr (que pode conter detalhes de autenticação ou caminhos).
        atual = self._referencia()
        if atual == commit:
            return True  # o envio terminou, mas a conexão perdeu a confirmação
        if atual != anterior:
            return False
        raise RuntimeError("publicação do painel não confirmada")


def publicar_eventos(eventos: list[dict], *, repositorio: Path, tentativas: int = 4) -> dict:
    agora = dt.datetime.now(dt.UTC)
    novos = validar_eventos(eventos, agora=agora)
    if not novos:
        return {"municipios": 0, "estados": 0}
    remoto = RepositorioStatus(repositorio)
    for _ in range(tentativas):
        agora = dt.datetime.now(dt.UTC)
        sha, anteriores = remoto.ler(agora=agora)
        unidos = juntar_eventos(anteriores, novos)
        if remoto.trocar(sha, documento(unidos, agora=agora)):
            return {"municipios": len(unidos), "estados": len({e["unidade"][:2] for e in unidos})}
    raise RuntimeError("painel concorrente; observação aguarda a próxima publicação")
