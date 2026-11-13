"""Admissão global do motor: fila e 15 reservas numa ref atualizada por compare-and-swap.

A ref contém apenas unidades, parâmetros e identificadores do Actions. A troca usa
force-with-lease na própria ref (nunca na main), sem cancelar jobs. A reserva só sai
quando a API confirma o fim do job ou da rodada que não chegou a criá-lo.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import time
from pathlib import Path

REF = "refs/tags/raiz-fila-processamento"
TETO = 15
ESTADOS_ATIVOS = ("queued", "in_progress", "waiting", "pending", "requested")
PASSO_EXECUTOR = "Rodar pelo executor (fontes, adoção, motor e tarefas do produto) e publicar no Release dados"
MAX_FALHAS = 3
WORKFLOWS_LOTE = ("lote-para.yml", "retomar-lote-para.yml", "desbloqueio-lote.yml", "lote-nacional.yml")
# #55: workflow inteiro conferido neste commit imutável, max-parallel=5,
# preparo e publicação sequenciais. Nenhum outro head herda esta exceção.
CAPACIDADE_LEGADA_LOTE = {("retomar-lote-para.yml", "3546687c66ec07ef9bd875d181efcff57ff1d312"): 5}
# Destino imutável com E1/E2 e guardas: upgrade científico intencional nas origens antigas.
# A auditoria declara as versões e os deltas por origem, sem reetiquetar saídas legadas.
# Só promove continuações/retentativas pendentes elegíveis; reservas vivas ficam intactas.
PROMOCOES_CONTINUACAO = {
    "88860b64ee09f811b66e283f5c57997ebcdb3fd5": "be452620f868537251fa832a10cb14bfb5c8efe3",
    "b624b108b0350135003e1099d9c928fa7cc24151": "be452620f868537251fa832a10cb14bfb5c8efe3",
    "6a53cfbf514f369f694ea0bd3bc594ef8295a3b4": "be452620f868537251fa832a10cb14bfb5c8efe3",
    "bea53bd06c7178daf2a53c392e5a9d54c55e7bc7": "be452620f868537251fa832a10cb14bfb5c8efe3",
    "436c7b636f6a8867b47403a1dfad4e4c741dc150": "be452620f868537251fa832a10cb14bfb5c8efe3",
}


def comando(args: list[str], entrada: str | None = None) -> str:
    r = subprocess.run(args, input=entrada, capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(f"{args[0]} falhou ao consultar ou reservar processamento: {r.stderr.strip()[:200]}")
    return r.stdout


def api(caminho: str):
    return json.loads(comando(["gh", "api", caminho]))


def paginas(caminho: str, campo: str) -> list[dict]:
    """Todas as páginas; uma falha nunca vira uma lista vazia."""
    bruto = comando(["gh", "api", "--paginate", caminho]).strip()
    decodificador = json.JSONDecoder()
    dados = []
    while bruto:
        pagina, fim = decodificador.raw_decode(bruto)
        dados.append(pagina)
        bruto = bruto[fim:].lstrip()
    if not dados or any(not isinstance(p, dict) or not isinstance(p.get(campo), list) for p in dados):
        raise RuntimeError(f"resposta incompleta do Actions: {campo}")
    return [x for p in dados for x in p[campo]]


def rodadas(
    repo: str, workflow: str, adicionais=(), incluir_jobs: bool = True, incluir_lotes: bool = False
) -> dict[str, dict]:
    runs = {}
    workflows = tuple(dict.fromkeys((workflow, *(WORKFLOWS_LOTE if incluir_lotes else ()))))
    for nome in workflows:
        for status in ESTADOS_ATIVOS:
            for r in paginas(
                f"repos/{repo}/actions/workflows/{nome}/runs?status={status}&per_page=100", "workflow_runs"
            ):
                runs[str(r["id"])] = {**r, "_workflow": nome}
    for identificador in adicionais:
        if str(identificador) not in runs:
            r = api(f"repos/{repo}/actions/runs/{identificador}")
            nome = str(r.get("path", "")).split("@", 1)[0].rsplit("/", 1)[-1]
            runs[str(identificador)] = {**r, "_workflow": nome}
    for identificador, r in runs.items():
        if "status" not in r:
            raise RuntimeError(f"rodada {identificador} sem situação confirmada")
        if incluir_jobs:
            r["jobs"] = paginas(f"repos/{repo}/actions/runs/{identificador}/jobs?filter=latest&per_page=100", "jobs")
    return runs


def vazio() -> dict:
    return {"versao": 1, "planejadores": [], "fila": [], "reservas": []}


class Repositorio:
    """Estado persistente no Git; criar e trocar a ref são operações atômicas."""

    def ler(self) -> tuple[str, dict]:
        if not comando(["git", "ls-remote", "origin", REF]).strip():
            return "", vazio()
        comando(["git", "fetch", "--no-tags", "origin", REF])
        sha = comando(["git", "rev-parse", "FETCH_HEAD"]).strip()
        objeto = comando(["git", "cat-file", "-p", sha])
        try:
            estado = json.loads(objeto.split("\n\n", 1)[1])
            if estado["versao"] != 1 or any(
                not isinstance(estado[k], list) for k in ("planejadores", "fila", "reservas")
            ):
                raise ValueError("estrutura desconhecida")
            if len(estado["reservas"]) > TETO:
                raise ValueError("reservas acima do teto")
        except (IndexError, KeyError, TypeError, ValueError) as ex:
            raise RuntimeError("fila de processamento inválida; nenhuma vaga será aberta") from ex
        return sha, estado

    def trocar(self, anterior: str, estado: dict) -> bool:
        commit = comando(["git", "rev-parse", "HEAD"]).strip()
        objeto = (
            f"object {commit}\ntype commit\ntag raiz-fila-processamento\n"
            f"tagger Raiz Actions <actions@raiz.invalid> {int(time.time())} +0000\n\n"
            + json.dumps(estado, ensure_ascii=False, sort_keys=True)
            + "\n"
        )
        sha = comando(["git", "hash-object", "-t", "tag", "-w", "--stdin"], objeto).strip()
        r = subprocess.run(
            ["git", "push", f"--force-with-lease={REF}:{anterior}", "origin", f"{sha}:{REF}"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r.returncode == 0:
            return True
        # Apenas conflito de lease é repetível. Autenticação/rede não autoriza continuar sem trava.
        if "stale info" in r.stderr.lower() or "fetch first" in r.stderr.lower():
            return False
        raise RuntimeError(f"não foi possível reservar processamento: {r.stderr.strip()[:200]}")


def ocupada(unidade: str, ativas: set[str]) -> bool:
    uf = unidade.split("-", 1)[0]
    return unidade in ativas or uf in ativas or ("-" not in unidade and any(u.startswith(uf + "-") for u in ativas))


def enfileirar(estado: dict, pedidos: list[dict]) -> None:
    ids = {p["id"] for p in estado["fila"]} | {r["pedido"]["id"] for r in estado["reservas"]}
    for p in pedidos:
        if p["id"] not in ids:
            estado["fila"].append(p)
            ids.add(p["id"])


def promover_continuacoes(estado: dict) -> int:
    """Só retomadas pendentes auditadas; reservas, bloqueios e outros commits ficam intactos.

    Executado na própria transação de admissão, inclusive para pedidos que um
    executor antigo enfileirar depois de uma migração manual da fila.
    """
    promovidos = 0
    for pedido in estado["fila"]:
        continuacao = pedido.get("continuacao", 0)
        falhas = pedido.get("falhas", 0)
        origem = pedido.get("ref")
        destino = PROMOCOES_CONTINUACAO.get(origem)
        if (
            pedido.get("bloqueado")
            or type(continuacao) is not int
            or type(falhas) is not int
            or min(continuacao, falhas) < 0
            or not (continuacao > 0 or falhas > 0)
            or destino is None
        ):
            continue
        pedido["ref"] = destino
        pedido["promocao_publicador"] = {"origem": origem, "destino": destino}
        promovidos += 1
    return promovidos


def devolver_a_fila(estado: dict, reserva: dict, run: dict, jobs: list[dict]) -> None:
    pedido = dict(reserva["pedido"])
    if pedido.get("repetir") is False:
        return  # catálogo auxiliar: uma falha não vira uma unidade da matriz do motor
    pedido["falhas"] = int(pedido.get("falhas", 0)) + 1
    if run.get("conclusion") == "cancelled" or any(j.get("conclusion") == "cancelled" for j in jobs):
        pedido["bloqueado"] = "Execução cancelada: só um novo pedido explícito pode retomar."
    elif pedido["falhas"] >= MAX_FALHAS:
        pedido["bloqueado"] = f"{MAX_FALHAS} execuções falharam: corrigir o erro e fazer novo pedido explícito."
    if jobs and all(
        any(s.get("name") == PASSO_EXECUTOR and s.get("conclusion") == "success" for s in j.get("steps", []))
        for j in jobs
    ):
        # O cálculo terminou; falhou cache, assinatura ou continuação. Retomar pelas marcas.
        pedido["refazer"] = ""
    estado["fila"].append(pedido)


def reconciliar(estado: dict, runs: dict[str, dict], e_unidade) -> tuple[set[str], int]:
    restantes = []
    for reserva in estado["reservas"]:
        run = runs[reserva["run_id"]]  # ausência/erro interrompe; não libera por tempo decorrido
        if reserva["pedido"].get("escopo") == "rodada":
            tentativa = run.get("run_attempt")
            if type(tentativa) is not int:
                raise RuntimeError("tentativa do Lote não confirmada; reserva mantida")
            if tentativa >= reserva["pedido"]["tentativa"] and run["status"] == "completed":
                continue
            restantes.append(reserva)
            continue
        jobs = [j for j in run["jobs"] if j.get("name") == reserva["unidade"]]
        if jobs and all(j["status"] == "completed" for j in jobs):
            if any(j.get("conclusion") != "success" for j in jobs):
                devolver_a_fila(estado, reserva, run, jobs)
            continue
        if not jobs and run["status"] == "completed":
            devolver_a_fila(estado, reserva, run, jobs)  # preparar falhou: o pedido não desaparece
            continue
        restantes.append(reserva)
    estado["reservas"] = restantes
    estado["planejadores"] = [i for i in estado["planejadores"] if runs[i]["status"] != "completed"]
    reservadas = {(r["run_id"], r["unidade"]) for r in restantes}
    ativas = {r["unidade"] for r in restantes}
    legados = 0
    for identificador, run in runs.items():
        if run["status"] == "completed":
            continue
        if run.get("_workflow") in WORKFLOWS_LOTE:
            # Um Lote legado pode abrir outra matriz após esta consulta. Sem
            # protocolo CAS confirmado, reserva o pico auditado ou bloqueia pelo teto.
            gerenciado = identificador in estado["planejadores"] or any(
                r["run_id"] == identificador and r["pedido"].get("escopo") == "rodada" for r in restantes
            )
            if not gerenciado:
                legados += CAPACIDADE_LEGADA_LOTE.get((run["_workflow"], run.get("head_sha")), TETO)
            continue
        jobs = [j for j in run["jobs"] if e_unidade(j.get("name", ""))]
        for j in jobs:
            if j["status"] != "completed" and (identificador, j["name"]) not in reservadas:
                ativas.add(j["name"])
                legados += 1
        if not jobs and identificador not in estado["planejadores"]:
            # Plano legado pode abrir uma matriz inteira; não presumir que ocupa só uma vaga.
            legados += TETO
    return ativas, legados


def admitir(
    estado: dict,
    runs: dict[str, dict],
    run_id: str,
    candidatos: list[dict],
    e_unidade,
    limite: int = TETO,
    max_novos: int | None = None,
    manutencao=(),
    limite_manutencao: int = 4,
    consumir_fila: bool = True,
) -> list[dict]:
    ativas, legados = reconciliar(estado, runs, e_unidade)
    promover_continuacoes(estado)
    livres = max(0, min(limite, TETO) - len(estado["reservas"]) - legados)
    if max_novos is not None:
        livres = min(livres, max_novos)
    escolhidos = []
    pendentes = {p["id"] for p in estado["fila"]}
    bloqueadas = {p["unidade"] for p in estado["fila"] if p.get("bloqueado")}
    manut_ativas = sum(u in manutencao for u in ativas)
    for pedido in [*(estado["fila"] if consumir_fila else []), *candidatos]:
        if len(escolhidos) >= livres:
            break
        if pedido.get("bloqueado"):
            continue
        if pedido["unidade"] in bloqueadas and pedido["id"] not in pendentes:
            continue  # a rodada automática também não reabre cancelamento/erro persistente
        if ocupada(pedido["unidade"], ativas):
            continue
        manut = pedido["unidade"] in manutencao
        if manut and pedido["id"] not in pendentes and manut_ativas >= limite_manutencao:
            continue
        estado["reservas"].append({"run_id": run_id, "unidade": pedido["unidade"], "pedido": pedido})
        ativas.add(pedido["unidade"])
        escolhidos.append(pedido)
        manut_ativas += manut
    ids = {p["id"] for p in escolhidos}
    estado["fila"] = [p for p in estado["fila"] if p["id"] not in ids]
    return escolhidos


def transacao(repo: Repositorio, mudar, tentativas: int = 10):
    for _ in range(tentativas):
        anterior, estado = repo.ler()
        resultado = mudar(estado)
        if repo.trocar(anterior, estado):
            return resultado
        time.sleep(random.uniform(0.2, 1.0))
    raise RuntimeError("fila concorrida: não reservei vagas; os pedidos continuam persistidos")


def pedido(unidade: str, refazer, continuacao: int = 0, origem: str | None = None) -> dict:
    origem = origem or os.environ["GITHUB_RUN_ID"]
    return {
        "id": f"{origem}/{unidade}/{continuacao}",
        "unidade": unidade,
        "refazer": ",".join(sorted(refazer)),
        "continuacao": continuacao,
        "ref": comando(["git", "rev-parse", "HEAD"]).strip(),
    }


def reservar(
    candidatos: list[str],
    pedidos: list[str],
    refazer,
    e_unidade,
    limite: int,
    continuacao: int = 0,
    max_novos: int | None = None,
    manutencao=(),
    limite_manutencao: int = 4,
    consumir_fila: bool = True,
    repetir: bool = True,
    reserva_rodada: bool = False,
) -> list[dict]:
    repo = Repositorio()
    run_id = os.environ["GITHUB_RUN_ID"]
    explicitos = [pedido(u, refazer, continuacao) for u in pedidos]

    def registrar(estado):
        if run_id not in estado["planejadores"]:
            estado["planejadores"].append(run_id)
        enfileirar(estado, explicitos)

    transacao(repo, registrar)  # o pedido existe antes de qualquer consulta/admissão que possa falhar

    def alocar(estado):
        adicionais = set(estado["planejadores"]) | {r["run_id"] for r in estado["reservas"]}
        runs = rodadas(
            os.environ["GITHUB_REPOSITORY"],
            os.environ.get("RAIZ_WORKFLOW", "processar-estados.yml"),
            adicionais,
            incluir_lotes=True,
        )
        novos = [pedido(u, refazer, continuacao) for u in candidatos] if not pedidos else []
        if not repetir:
            novos = [{**p, "repetir": False} for p in novos]
        if reserva_rodada:
            tentativa = int(os.environ["GITHUB_RUN_ATTEMPT"])
            if tentativa < 1 or repetir or consumir_fila or pedidos:
                raise ValueError("reserva da rodada exige tentativa válida e não pode consumir ou repetir pedidos")
            novos = [{**p, "escopo": "rodada", "tentativa": tentativa} for p in novos]
        escolhidos = admitir(
            estado, runs, run_id, novos, e_unidade, limite, max_novos, manutencao, limite_manutencao, consumir_fila
        )
        return escolhidos, [p for p in estado["fila"] if p.get("bloqueado")]

    escolhidos, bloqueados = transacao(repo, alocar)
    if bloqueados:
        texto = "\n### Pedidos preservados, aguardando correção\n\n" + "\n".join(
            f"- {p['unidade']} ({p['id']}): {p['bloqueado']}" for p in bloqueados
        )
        print(texto)
        if caminho := os.environ.get("GITHUB_STEP_SUMMARY"):
            with Path(caminho).open("a", encoding="utf-8") as arquivo:
                arquivo.write(texto + "\n")
    return escolhidos


def guardar_continuacao(unidade: str, continuacao: int) -> None:
    p = pedido(unidade, (), continuacao)
    transacao(Repositorio(), lambda estado: enfileirar(estado, [p]))
