"""Completa metadados dos arquivos já publicados, sem executar o motor geográfico.

No Actions, ``--reservar`` roda só com a biblioteca padrão antes de instalar
dependências. ``--publicar`` exige a reserva ainda presente. Cada UF usa um
espelho temporário próprio; o índice remoto é o checkpoint de cada entrega.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
import traceback
from email.utils import parsedate_to_datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
UNIDADE = "catalogo"
# SHA-256 dos workflows completos em 1e6d6f6 e c3ec39e (os dois leiautes
# pré-matrix.ref auditados): checkout padrão, sem troca posterior de commit.
WORKFLOWS_CHECKOUT_HEAD = {
    "dd0da1a5d2f1af64030ec74316babc284ca23263b2268baff2aee4618632a77c",
    "d804e0b7bb327bc7058ab199691fcfcbb8f5ba8b75d951a135e21e357d6b79d6",
}
_COMPATIBILIDADE: dict[tuple[str, str, str], bool] = {}
_CHECKOUT_HEAD: dict[tuple[str, str], bool] = {}
_NOMES_PRIVADOS_RELATORIO: dict[str, str] = {}
MARGEM_REQUISICOES = 250


class ProcessamentoInseguro(RuntimeError):
    """O catálogo deve terminar sem alterar dados nem cancelar o processamento."""


def checkout_do_head(repo: str, sha: str, fila) -> bool:
    """Reconhece só os workflows históricos auditados que executavam head_sha.

    Conferir o arquivo inteiro impede falsos positivos de um parser YAML parcial
    e de passos posteriores que alterem o checkout. Sem dependências antes do uv
    sync: qualquer workflow diferente exige a referência preservada na reserva.
    """
    chave = (repo, sha)
    if chave not in _CHECKOUT_HEAD:
        objeto = fila.api(f"repos/{repo}/contents/.github/workflows/processar-estados.yml?ref={sha}")
        if objeto.get("encoding") != "base64":
            raise ValueError("workflow do checkout não confirmado")
        dados = base64.b64decode("".join(objeto["content"].split()), validate=True)
        _CHECKOUT_HEAD[chave] = hashlib.sha256(dados).hexdigest() in WORKFLOWS_CHECKOUT_HEAD
    return _CHECKOUT_HEAD[chave]


def conferir_processamento_seguro(relatorio: dict | None = None) -> dict:
    """Snapshot fresco dos runs e da fila; hashes de commits imutáveis podem usar cache.

    A referência da matriz pode ser anterior ao head do workflow. Pedidos ainda
    na fila também são conferidos, pois podem começar durante a catalogação.
    A consulta se repete sob cada trava antes de publicar; não é uma barreira
    contra alguém iniciar manualmente um workflow histórico após a consulta.
    """
    fila, rodar = modulos_fila()
    repo = os.environ["GITHUB_REPOSITORY"]
    resultado = {
        "publicador_sha256": hashlib.sha256((RAIZ / "raiz/executor/armazem.py").read_bytes()).hexdigest(),
        "conferido_em": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seguro": False,
        "rodadas_legadas": [],
        "pedidos_legados": [],
        "checkouts_head_confirmados": [],
    }
    try:
        _, estado = fila.Repositorio().ler()
        reservas = [r for r in estado["reservas"] if rodar._e_unidade(r["unidade"])]
        runs = fila.rodadas(repo, "processar-estados.yml", {r["run_id"] for r in reservas}, incluir_jobs=False)

        def compativel(sha):
            if not isinstance(sha, str) or not re.fullmatch(r"[a-fA-F0-9]{40}", sha):
                raise ValueError("referência do código não confirmada")
            # Ancestralidade não prova o contrato após um squash e não impede
            # regressões em descendentes. Exige os bytes auditados do publicador,
            # inclusive travas sem expiração e o destino privado autenticado.
            esperado = resultado["publicador_sha256"]
            chave = (repo, sha, esperado)
            if chave not in _COMPATIBILIDADE:
                objeto = fila.api(f"repos/{repo}/contents/raiz/executor/armazem.py?ref={sha}")
                if objeto.get("encoding") != "base64":
                    raise ValueError("conteúdo do publicador não confirmado")
                codigo = base64.b64decode("".join(objeto["content"].split()), validate=True)
                _COMPATIBILIDADE[chave] = hashlib.sha256(codigo).hexdigest() == esperado
            return _COMPATIBILIDADE[chave]

        for run_id, run in sorted(runs.items()):
            if run["status"] == "completed":
                continue
            if not str(run_id).isdigit() or run["status"] not in fila.ESTADOS_ATIVOS:
                raise ValueError("situação da rodada não confirmada")
            head_compativel = compativel(run.get("head_sha"))
            padrao = head_compativel and checkout_do_head(repo, run["head_sha"], fila)
            if not padrao and "jobs" not in run:
                run["jobs"] = fila.paginas(
                    f"repos/{repo}/actions/runs/{run_id}/jobs?filter=latest&per_page=100", "jobs"
                )
            unidades = sorted({j["name"] for j in run.get("jobs", []) if rodar._e_unidade(j.get("name", ""))})
            if padrao:
                resultado["checkouts_head_confirmados"].append(run_id)
            elif head_compativel:
                for job in run["jobs"]:
                    if rodar._e_unidade(job.get("name", "")) and job["status"] != "completed":
                        if not any(r["run_id"] == run_id and r["unidade"] == job["name"] for r in reservas):
                            # Um rerun pode repetir matrix.ref depois que a reserva
                            # original saiu da fila; head_sha não prova esse checkout.
                            raise ValueError("referência efetiva da matriz não confirmada")
            refs = {run.get("head_sha")}
            for reserva in reservas:
                if reserva["run_id"] != run_id:
                    continue
                jobs = [j for j in run.get("jobs", []) if j.get("name") == reserva["unidade"]]
                if jobs and all(j["status"] == "completed" for j in jobs):
                    continue
                refs.add(reserva["pedido"].get("ref"))
            for sha in sorted(refs, key=lambda ref: str(ref)):
                if not compativel(sha):
                    resultado["rodadas_legadas"].append(
                        {
                            "run_id": run_id,
                            "unidades": unidades,
                            "ref": sha,
                            "url": f"https://github.com/{repo}/actions/runs/{run_id}",
                        }
                    )
        for pedido in estado["fila"]:
            if pedido.get("bloqueado") or not rodar._e_unidade(pedido["unidade"]):
                continue
            if not compativel(pedido.get("ref")):
                resultado["pedidos_legados"].append({"unidade": pedido["unidade"], "ref": pedido["ref"]})
        resultado["seguro"] = not (resultado["rodadas_legadas"] or resultado["pedidos_legados"])
        resultado["codigo"] = "sem_processamento_legado" if resultado["seguro"] else "aguardando_processamento_legado"
    except Exception:
        # Mensagens de git/gh podem conter respostas autenticadas. O diagnóstico
        # público descreve a falha de confirmação, sem copiar essas mensagens.
        resultado["codigo"] = "consulta_de_processamento_nao_confirmada"
    relatorio = relatorio if relatorio is not None else {}
    relatorio["seguranca_processamento"] = resultado
    salvar_relatorio(relatorio)
    if not resultado["seguro"]:
        detalhes = "; ".join(
            f"{', '.join(r['unidades']) or 'planejamento'} (rodada {r['run_id']})" for r in resultado["rodadas_legadas"]
        )
        mensagem = (
            "Catálogo bloqueado: processamento sem contrato privado seguro ou segurança não confirmada"
            + (f": {detalhes}" if detalhes else ".")
            + " Aguarde o término natural das rodadas e dos pedidos legados; não cancele os jobs. "
            "Nenhuma publicação foi autorizada por esta conferência."
        )
        if caminho := os.environ.get("GITHUB_STEP_SUMMARY"):
            with Path(caminho).open("a", encoding="utf-8") as arquivo:
                arquivo.write("\n### Catálogo aguardando processamento seguro\n\n" + mensagem + "\n")
        raise ProcessamentoInseguro(mensagem)
    return resultado


def modulos_fila():
    sys.path.insert(0, str(RAIZ / "motor"))
    import fila_processamento
    import rodar_estado

    return fila_processamento, rodar_estado


def contexto_actions(unidade: str = UNIDADE) -> str:
    job = UNIDADE if unidade == UNIDADE else "processar"
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_JOB") != job:
        raise RuntimeError(f"execute pelo job {job} autorizado para esta publicação")
    if unidade != UNIDADE:
        _, rodar = modulos_fila()
        if not rodar._e_unidade(unidade) or unidade != os.environ.get("UNIDADE"):
            raise RuntimeError("unidade de processamento ausente ou incompatível com o job")
    if not os.environ.get("GITHUB_RUN_ID") or not os.environ.get("GITHUB_REPOSITORY"):
        raise RuntimeError("identificação do Actions ausente; não inicio processamento")
    return os.environ["GITHUB_RUN_ID"]


def confirmar_reserva(unidade: str = UNIDADE) -> None:
    run_id = contexto_actions(unidade)
    fila, _ = modulos_fila()
    if unidade == UNIDADE:
        try:
            tentativa = int(os.environ["GITHUB_RUN_ATTEMPT"])
            if tentativa < 1:
                raise ValueError
        except (KeyError, ValueError):
            raise RuntimeError("tentativa do catálogo não confirmada; nenhum arquivo será processado") from None

        def confirmar(estado):
            reservas = [r for r in estado["reservas"] if r["run_id"] == run_id and r["unidade"] == unidade]
            if len(reservas) != 1:
                raise RuntimeError("job sem reserva global para esta unidade; nenhum arquivo será processado")
            pedido = reservas[0]["pedido"]
            anterior = pedido.get("tentativa", 1)
            if pedido.get("repetir") is not False or type(anterior) is not int or not 1 <= anterior <= tentativa:
                raise RuntimeError("reserva do catálogo incompatível com a tentativa; processamento recusado")
            # O CAS protege também reservas legadas, antes da primeira leitura
            # pesada. Um snapshot completed da tentativa anterior não libera a vaga.
            pedido.update(escopo="rodada", tentativa=tentativa)

        fila.transacao(fila.Repositorio(), confirmar)
        return
    _, estado = fila.Repositorio().ler()
    reserva = next((r for r in estado["reservas"] if r["run_id"] == run_id and r["unidade"] == unidade), None)
    if reserva is None:
        raise RuntimeError("job sem reserva global para esta unidade; nenhum arquivo será processado")
    if unidade != UNIDADE:
        executor = os.environ.get("RAIZ_EXECUTOR_REF", "")
        publicador = os.environ.get("RAIZ_PUBLICADOR_REF", "")
        if not all(re.fullmatch(r"[a-fA-F0-9]{40}", ref) for ref in (executor, publicador)):
            raise RuntimeError("referências do executor e do publicador não confirmadas")
        if reserva["pedido"].get("ref") != executor:
            raise RuntimeError("referência do executor diverge da reserva; nenhum arquivo será processado")
        if fila.comando(["git", "rev-parse", "HEAD"]).strip() != publicador:
            raise RuntimeError("checkout do publicador diverge do commit do workflow")


def minutos_para_finalizar() -> float:
    """Usa o relógio do job de 345 min, deixando dez minutos para atestar/cache."""
    try:
        inicio = float(os.environ["RAIZ_INICIO"])
        minutos = (inicio + 335 * 60 - time.time()) / 60
        if not math.isfinite(inicio) or inicio <= 0 or not math.isfinite(minutos) or minutos <= 1:
            raise ValueError("prazo insuficiente")
    except (KeyError, ValueError):
        raise RuntimeError("sem prazo seguro para finalizar metadados; progresso preservado para retomada") from None
    return min(300.0, minutos)


def reservar_vaga() -> None:
    run_id = contexto_actions()
    fila, rodar = modulos_fila()
    # A última continuação pode chegar depois do cron. Promover só a fila pela
    # mesma regra auditada, sem admitir cálculo nem tocar nas reservas vivas.
    _, pendentes = fila.Repositorio().ler()
    if fila.promover_continuacoes(pendentes):
        fila.transacao(fila.Repositorio(), fila.promover_continuacoes)
    conferir_processamento_seguro()  # não ocupa uma vaga esperando os jobs legados
    _, estado = fila.Repositorio().ler()
    if any(r["run_id"] == run_id and r["unidade"] == UNIDADE for r in estado["reservas"]):
        confirmar_reserva()
        return  # a tentativa atual foi confirmada por CAS antes de reutilizar a vaga
    # A consulta inclui os runs legados do motor e todos os runs com reserva.
    # Não drena pedidos de UF nem devolve catalogo à matriz após uma falha.
    escolhidos = fila.reservar(
        candidatos=[UNIDADE],
        pedidos=[],
        refazer=(),
        e_unidade=rodar._e_unidade,
        limite=15,
        max_novos=1,
        consumir_fila=False,
        repetir=False,
        reserva_rodada=True,
    )
    if [p["unidade"] for p in escolhidos] != [UNIDADE]:
        raise RuntimeError("sem vaga entre os 15 jobs de processamento; tente novamente após uma vaga ser liberada")
    print("Uma vaga global reservada para o catálogo; nenhum job existente foi interrompido.", flush=True)


def eh_ficha(nome: str) -> bool:
    return nome == "croissant.json" or nome.startswith("croissant_")


def uf_do_asset(nome: str) -> str | None:
    resultado = re.search(r"_([A-Z]{2})\.(?:tar\.gz|parquet|json)(?:\.json)?$", nome)
    return resultado[1] if resultado else None


def conferir_orcamento(relatorio: dict) -> bool:
    """Margem compartilhada, não reserva: cota curta vira checkpoint sem esperar uma hora."""
    fila, _ = modulos_fila()
    try:
        core = fila.api("rate_limit")["resources"]["core"]
        restantes, reset = core["remaining"], core["reset"]
        if type(restantes) is not int or type(reset) is not int or min(restantes, reset) < 0:
            raise ValueError("cota inválida")
    except Exception:
        relatorio["adiado_por_cota"] = True
        relatorio["orcamento_api"] = {"codigo": "consulta_de_cota_nao_confirmada"}
        salvar_relatorio(relatorio)
        raise ProcessamentoInseguro(
            "Cota da API não confirmada; retomada preservada sem iniciar outra unidade."
        ) from None
    suficiente = restantes >= MARGEM_REQUISICOES
    relatorio["orcamento_api"] = {"restantes": restantes, "minimo": MARGEM_REQUISICOES, "reset_epoch": reset}
    if not suficiente:
        relatorio["adiado_por_cota"] = True
        print("Cota da API abaixo da margem; preservando as unidades pendentes para outra execução.", flush=True)
    salvar_relatorio(relatorio)
    return suficiente


def transporte_com_retry(prazo: float, transporte=None, espera_total: list[float] | None = None):
    """Repete só respostas de quota; nunca repete DELETE+POST como uma operação inteira."""
    import httpx

    espera_total = espera_total if espera_total is not None else [0.0]

    class Transporte(httpx.BaseTransport):
        def __init__(self):
            self.base = transporte or httpx.HTTPTransport()

        def handle_request(self, request):
            for tentativa in range(3):
                resposta = self.base.handle_request(request)
                quota = resposta_de_cota(resposta)
                if request.url.host not in {"api.github.com", "uploads.github.com"} or not quota or tentativa == 2:
                    return resposta
                try:
                    if valor := resposta.headers.get("retry-after"):
                        try:
                            espera = float(valor)
                        except ValueError:
                            espera = parsedate_to_datetime(valor).timestamp() - time.time()
                    elif valor := resposta.headers.get("x-ratelimit-reset"):
                        espera = float(valor) - time.time()
                    else:
                        espera = 60.0
                    if not math.isfinite(espera):
                        return resposta
                    espera = max(0.0, espera)
                except (TypeError, ValueError, OverflowError):
                    return resposta
                # Nunca monopoliza uma trava durante o reset de uma hora. A
                # margem de quota é conferida antes de começar cada unidade.
                if espera_total[0] + espera > 60 or time.monotonic() + espera > prazo:
                    return resposta
                resposta.close()
                if espera:
                    print(
                        f"API pediu espera de {math.ceil(espera)} s; repetindo somente a requisição recusada.",
                        flush=True,
                    )
                    time.sleep(espera)  # no máximo 60 s somados em todos os clientes deste job
                    espera_total[0] += espera
            raise AssertionError("tentativas de quota sem resposta")

        def close(self):
            self.base.close()

    return Transporte()


def resposta_de_cota(resposta) -> bool:
    return resposta is not None and (
        resposta.status_code == 429
        or (
            resposta.status_code == 403
            and (resposta.headers.get("x-ratelimit-remaining") == "0" or "retry-after" in resposta.headers)
        )
    )


def classe_armazem(prazo: float | None = None):
    from raiz.atestacao import registrar
    from raiz.executor.armazem import ArmazemRelease

    prazo = prazo if prazo is not None else time.monotonic() + 280 * 60
    espera_total = [0.0]

    class ArmazemCatalogo(ArmazemRelease):
        def __init__(self, *args, **kwargs):
            if kwargs.get("cliente") is None:
                import httpx

                kwargs["cliente"] = httpx.Client(
                    timeout=300,
                    follow_redirects=True,
                    headers={"User-Agent": "raiz-catalogo"},
                    transport=transporte_com_retry(prazo, espera_total=espera_total),
                )
            super().__init__(*args, **kwargs)

        def _baixar_asset(self, nome, fresco=False):
            dados = super()._baixar_asset(nome, fresco=True)
            if dados is not None:
                # Hash dos bytes efetivamente lidos. Upload posterior com o mesmo
                # nome substitui esse hash pelo dos bytes novos em atestar.txt.
                registrar(nome, dados, privado=self.privado)
            return dados

        def _subir(self, rel, nome, dados, tipo="application/octet-stream"):
            try:
                self._subir_com_recuperacao(rel, nome, dados, tipo)
            except Exception:
                raise ProcessamentoInseguro(
                    "Publicação interrompida; originais já preservados permanecem no arquivo privado."
                ) from None

        def _subir_com_recuperacao(self, rel, nome, dados, tipo="application/octet-stream"):
            # Originais completos nunca entram em artifacts do Actions. Antes
            # do DELETE, uma cópia imutável é enviada e relida no arquivo privado.
            from raiz.executor.armazem import destino_privado

            if time.monotonic() >= prazo:
                raise RuntimeError("prazo de publicação encerrado; nenhum novo arquivo será substituído")
            if self.privado:
                self._exigir_privado()
            original = next((a for a in rel["assets"] if a["name"] == nome), None)
            digest_novo = hashlib.sha256(dados).hexdigest()
            if original and original.get("digest") == "sha256:" + digest_novo:
                registrar(nome, dados, privado=self.privado)
                return
            identidade = f"{self.repo}/{self.tag}/{nome}"
            prefixo = hashlib.sha256(identidade.encode()).hexdigest()[:24]
            marcador = Path(os.environ["RUNNER_TEMP"]) / "recuperacao-release" / (prefixo + ".json")
            if original:
                destino = destino_privado()
                if destino is None:
                    raise PermissionError("substituição exige destino privado para preservar o original")
                arquivo = ArmazemRelease(
                    *destino,
                    token=os.environ.get("RAIZ_DADOS_PRIVADOS_TOKEN", ""),
                    cliente=self.cli,
                    privado=True,
                )
                with arquivo._erros_privados("preservar original"):
                    arquivo._exigir_privado()
                    anterior = self._baixar_ativo(original) if self.privado else self._baixar_asset(nome, fresco=True)
                    if anterior is None:
                        raise RuntimeError("original indisponível; substituição recusada")
                    digest = hashlib.sha256(anterior).hexdigest()
                    if original.get("digest") and original["digest"] != "sha256:" + digest:
                        raise RuntimeError("original diverge do digest da API; substituição recusada")
                    backup = f"recuperacao-{prefixo}-{digest}"
                    meta = json.dumps(
                        {
                            "origem": identidade,
                            "asset_id": original["id"],
                            "sha256": digest,
                            "tamanho": len(anterior),
                            "arquivo": backup + ".bin",
                        },
                        sort_keys=True,
                    ).encode()
                    # Conteúdo + origem identificam um backup; o asset_id pode
                    # mudar numa regravação idêntica e não substitui o manifesto.
                    for sufixo, conteudo in ((".bin", anterior), (".json", meta)):
                        nome_backup = backup + sufixo
                        with arquivo._trava("trava-" + prefixo, 1800):
                            existente = arquivo._baixar_asset(nome_backup, fresco=True)
                            if existente is None:
                                arquivo._subir(arquivo._release(), nome_backup, conteudo)
                                existente = arquivo._baixar_asset(nome_backup, fresco=True)
                            if sufixo == ".bin" and existente != conteudo:
                                raise RuntimeError("cópia privada não confirmada; substituição recusada")
                            if sufixo == ".json":
                                confirmado = json.loads(existente or b"null")
                                if not confirmado or any(
                                    confirmado.get(k) != json.loads(meta)[k]
                                    for k in ("origem", "sha256", "tamanho", "arquivo")
                                ):
                                    raise RuntimeError("manifesto privado não confirmado; substituição recusada")
                    marcador.parent.mkdir(parents=True, exist_ok=True)
                    marcador.write_bytes(meta)
            if time.monotonic() >= prazo:
                raise RuntimeError("prazo encerrado após preservar o original; arquivo remoto não foi removido")
            super()._subir(rel, nome, dados, tipo)
            marcador.unlink(missing_ok=True)

    return ArmazemCatalogo


def referencias(indice: dict) -> dict:
    fichas = dict(indice.get("fichas") or {})
    for uf, entrada in indice.get("estados", {}).items():
        fichas.update(entrada.get("fichas") or {})
        if entrada.get("croissant"):
            fichas[f"raiz_{uf}.tar.gz"] = entrada["croissant"]
    return fichas


def arquivos_produto(armazem) -> list[dict]:
    """Infraestrutura e cópias históricas não geram metadados recursivos."""
    return [
        a
        for a in armazem._assets()
        if not a["name"].startswith(
            (
                "cache_",
                "historico-",
                "recuperacao-",
                "artifact-",
                "artifacts-",
                "actions-",
                "backup-",
                "corte-",
                "inventario-",
                "migracao-",
                "checkpoint-",
                "catalogo-relatorio-",
                "retomada_",
                "lote_PA_entradas_",
                "lote_PA_checkpoint_",
                "lote_PA_calculado_",
            )
        )
    ]


def catalogar_lotes(armazem, pasta: Path) -> list[dict]:
    """Produtos finais imutáveis: só publica derivados, sob a trava global do chamador."""
    from raiz import lote_publicado as lote
    from raiz import metadados
    from raiz.atestacao import registrar
    from raiz.metadados_lote import croissant_tar_csv

    if not armazem.privado:
        raise PermissionError("produtos completos do lote exigem arquivo privado")
    armazem._exigir_privado()
    ativos = {a["name"]: a for a in arquivos_produto(armazem)}
    resultados = []
    for nome in sorted(n for n in ativos if lote.eh_manifesto(n)):
        with tempfile.TemporaryDirectory(prefix="lote-", dir=pasta) as temp:
            raiz = Path(temp)

            def baixar(ativo, destino):
                dados = armazem._baixar_ativo(ativo)
                digest = hashlib.sha256(dados).hexdigest()
                if ativo.get("digest") != "sha256:" + digest:
                    raise ValueError("digest do produto imutável não confirmado")
                destino.write_bytes(dados)
                destino.chmod(0o600)
                registrar(ativo["name"], dados, privado=True)

            arquivo_manifesto = raiz / "manifesto.json"
            baixar(ativos[nome], arquivo_manifesto)
            base_url = armazem.url_metadados(nome).removesuffix(nome)
            manifesto, digest = lote.ler_manifesto(arquivo_manifesto, nome, base_url=base_url)
            pacotes = {}
            for tipo, ref in manifesto["arquivos"].items():
                ativo = ativos.get(ref["nome"], {})
                if (
                    ativo.get("id") != ref["asset_id"]
                    or ativo.get("size") != ref["bytes"]
                    or ativo.get("digest") != "sha256:" + ref["sha256"]
                ):
                    raise ValueError("referência imutável do pacote não confirmada")
                pacotes[tipo] = raiz / (tipo + ".tar.gz")
                baixar(ativo, pacotes[tipo])
            gerado = lote.gerar(
                arquivo_manifesto,
                nome,
                pacotes,
                raiz / "derivados",
                base_url=base_url,
                data_inicio=os.environ.get("RAIZ_CADT_INICIO_CENARIO", ""),
            )
            # Todos os derivados e as fichas passam pela validação local antes
            # do primeiro upload. Os cinco originais não são reenviados.
            fichas = {
                nome: metadados.ficha_arquivo(
                    nome,
                    base_url + nome,
                    digest,
                    arquivo_manifesto.stat().st_size,
                    escopo="privado",
                    formato="application/json",
                    repo=armazem.repo_codigo,
                )
            }
            for tipo, pacote in pacotes.items():
                ref = manifesto["arquivos"][tipo]
                fichas[ref["nome"]] = croissant_tar_csv(
                    pacote,
                    ref["nome"],
                    {
                        "url": base_url + ref["nome"],
                        "sha256": ref["sha256"],
                        "bytes": ref["bytes"],
                        "versao": manifesto["modelo_versao"],
                        "repo_codigo": armazem.repo_codigo,
                    },
                )
            for ficha in fichas.values():
                metadados.validar(ficha)
            referencias_lote = {}
            rel = armazem._release()
            for original, ficha in fichas.items():
                nome_ficha = f"croissant_{original}.json"
                dados = lote.json_bytes(ficha)
                armazem._subir(rel, nome_ficha, dados, "application/ld+json")
                referencias_lote[original] = {
                    "url": base_url + nome_ficha,
                    "sha256": hashlib.sha256(dados).hexdigest(),
                    "arquivo_sha256": ficha["distribution"][0]["sha256"],
                }
            formatos = {
                ".json": "application/json",
                ".md": "text/markdown",
                ".parquet": "application/vnd.apache.parquet",
                ".gz": "application/gzip",
            }
            for arquivo, caminho in sorted(gerado["arquivos"].items()):
                referencias_lote[arquivo] = armazem._publicar_auxiliar(
                    rel, arquivo, caminho.read_bytes(), formatos.get(caminho.suffix, "application/octet-stream")
                )
            armazem._gravar_indice({}, fichas_adicionais=referencias_lote)
            resultados.append({"manifesto_sha256": digest, "arquivos": len(referencias_lote)})
    return resultados


def checksums(*, privado: bool = False) -> dict[str, str]:
    caminho = Path(os.environ["RUNNER_TEMP"]) / ("atestar-privado.txt" if privado else "atestar.txt")
    if not caminho.exists():
        return {}
    return {nome: digest for digest, nome in (linha.split("  ", 1) for linha in caminho.read_text().splitlines())}


def conferir_arquivo(armazem, asset: dict, indice: dict) -> str:
    """Confere ficha e bytes sob a trava apropriada; retorna o digest verificado."""
    from raiz.atestacao import identificador

    nome = asset["name"]
    digest_api = (asset.get("digest") or "").removeprefix("sha256:").lower()
    digest_valido = bool(re.fullmatch(r"[a-f0-9]{64}", digest_api))
    # Sem digest da API, é necessário reler os bytes; o nome privado nunca é chave pública.
    assunto = (
        identificador(nome, privado=armazem.privado, digest=digest_api)
        if digest_valido or not armazem.privado
        else None
    )
    digest = checksums(privado=armazem.privado).get(assunto)
    dados = None
    if not digest or digest != digest_api:
        dados = armazem._baixar_asset(nome, fresco=True)
        if dados is None:
            raise RuntimeError("arquivo desapareceu durante a leitura")
        digest = hashlib.sha256(dados).hexdigest()
        if digest_api and re.fullmatch(r"[a-fA-F0-9]{64}", digest_api) and digest != digest_api.lower():
            raise RuntimeError("bytes divergentes do digest da API")
    if eh_ficha(nome):
        return digest
    if nome == "estados.json":
        referencia = {"url": armazem.url_metadados("croissant_estados.json")}
    else:
        referencia = referencias(indice).get(nome)
    ficha = None
    if referencia:
        url = referencia if isinstance(referencia, str) else referencia["url"]
        nome_ficha = url.rsplit("/", 1)[-1]
        bruto = armazem._baixar_asset(nome_ficha, fresco=True)
        if bruto:
            ficha = json.loads(bruto)
    corresponde = ficha and any(
        d.get("contentUrl") == armazem.url_metadados(nome) and d.get("sha256") == digest
        for d in ficha.get("distribution", [])
    )
    if not corresponde:
        # A ficha dos CSV precisa conservar os esquemas, não ser substituída
        # por uma ficha genérica em caso de erro ou publicação legada concorrente.
        if re.fullmatch(r"raiz_[A-Z]{2}\.tar\.gz", nome) or nome == "estados.json":
            raise RuntimeError("ficha desatualizada; refaça a catalogação da unidade")
        dados = dados if dados is not None else armazem._baixar_asset(nome, fresco=True)
        if dados is None:
            raise RuntimeError("arquivo não encontrado")
        armazem.catalogar_arquivo(nome, dados, asset.get("content_type") or "application/octet-stream")
    return digest


def salvar_relatorio(relatorio: dict) -> None:
    pasta = Path(os.environ["RUNNER_TEMP"])
    destino = pasta / "catalogo-metadados.json"
    novo = destino.with_suffix(".tmp")
    novo.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    novo.replace(destino)


def nome_no_relatorio(nome: str | None) -> str | None:
    """Nomes privados são dados: apenas artefatos de contrato aparecem em logs públicos."""
    if nome is None:
        return None
    basicos = {
        "estados.json",
        "croissant.json",
        "cartao_modelo.md",
        "modelos.json",
        "tasks.json",
        "model-metadata-schema.json",
        "cadt_lotes.json",
        "raiz_controle.json",
        "URTX.kml",
    }
    base = nome.removeprefix("croissant_").removesuffix(".json") if nome.startswith("croissant_") else nome
    if (
        nome in basicos
        or base in basicos
        or re.fullmatch(
            r"(?:raiz_(?:(?:geo_|camadas_)?[A-Z]{2}\.tar\.gz|controle_[A-Z]{2}\.json)|"
            r"(?:quantis|diagnosticos_quantis|cadt)_[A-Z]{2}\.(?:parquet|json)|[A-Z]{2})",
            base,
        )
    ):
        return nome
    # Identidade somente desta execução, sem um hash adivinhável do nome pessoal.
    if nome not in _NOMES_PRIVADOS_RELATORIO:
        _NOMES_PRIVADOS_RELATORIO[nome] = f"arquivo-{len(_NOMES_PRIVADOS_RELATORIO) + 1:06d}"
    return _NOMES_PRIVADOS_RELATORIO[nome]


def registrar_falha(relatorio: dict, unidade: str, etapa: str, arquivo: str | None, erro: Exception) -> None:
    """Guarda pontos do código, nunca str(erro), variáveis locais ou linhas de fonte."""
    arquivo = nome_no_relatorio(arquivo)
    rastro = [
        {"arquivo": Path(frame.f_code.co_filename).name, "linha": linha, "funcao": frame.f_code.co_name}
        for frame, linha in traceback.walk_tb(erro.__traceback__)
    ]
    relatorio["falhas"].append(
        {"unidade": unidade, "etapa": etapa, "arquivo": arquivo, "tipo": type(erro).__name__, "rastro": rastro}
    )
    print(f"Falha em {unidade}, etapa {etapa}, arquivo {arquivo or '-'}: {type(erro).__name__}.", flush=True)
    for ponto in rastro[-6:]:
        print(f"  {ponto['arquivo']}:{ponto['linha']} em {ponto['funcao']}", flush=True)


def publicar(
    limite_minutos: float = 280,
    ufs: list[str] | None = None,
    fabrica=None,
    *,
    incluir_globais: bool = True,
    unidade_reservada: str | None = None,
) -> dict:
    """Um estado por vez; ufs=None inclui todos, ufs=[] retoma somente os globais."""
    if unidade_reservada is None:
        confirmar_reserva()
    else:
        confirmar_reserva(unidade_reservada)
        if incluir_globais or ufs != [unidade_reservada.split("-", 1)[0]]:
            raise ValueError("o finalizador só pode publicar a UF da unidade reservada")
    if limite_minutos <= 0 or limite_minutos > 300:
        raise ValueError("o limite deve ficar entre zero e 300 minutos, com margem para atestar")
    inicio = time.monotonic()
    fim = inicio + limite_minutos * 60
    from raiz.catalogo_publico import catalogar_publico
    from raiz.executor.armazem import destino_privado

    repo = os.environ["GITHUB_REPOSITORY"]
    destino = destino_privado()
    if destino is None:
        raise PermissionError("catalogação completa exige arquivo privado configurado")
    pasta_temp = Path(os.environ["RUNNER_TEMP"])
    relatorio = {
        "concluidas": [],
        "pendentes": [],
        "falhas": [],
        "arquivos_conferidos": {},
        "global_concluido": False,
        "sem_pacote_tabular": [],
        "escopo": "catalogo" if incluir_globais else "uf_reservada",
    }
    conferir_processamento_seguro(relatorio)
    armazem_cls = fabrica or classe_armazem(fim)
    with tempfile.TemporaryDirectory(prefix="raiz-catalogo-", dir=pasta_temp) as temporaria:
        raiz_temp = Path(temporaria)
        geral = armazem_cls(
            *destino, raiz_temp / "geral", privado=True, token=os.environ.get("RAIZ_DADOS_PRIVADOS_TOKEN", "")
        )
        aberto = armazem_cls(repo, "dados", raiz_temp / "basico", privado=False)
        try:
            geral._exigir_privado()
            assets = arquivos_produto(geral)
            existentes = sorted({uf for a in assets if not eh_ficha(a["name"]) and (uf := uf_do_asset(a["name"]))})
            escolhidas = existentes if ufs is None else sorted(set(ufs))
            desconhecidas = set(escolhidas) - set(existentes)
            if desconhecidas:
                raise ValueError(f"estados sem arquivos no Release: {', '.join(sorted(desconhecidas))}")
            relatorio["pendentes"] = list(escolhidas)
            salvar_relatorio(relatorio)
            for uf in escolhidas:
                if time.monotonic() >= fim:
                    break
                etapa, arquivo_atual = "orcamento_api", None
                try:
                    if not conferir_orcamento(relatorio):
                        break
                    etapa = "espaco_em_disco"
                    if shutil.disk_usage(raiz_temp).free < 2 * 1024**3:
                        raise RuntimeError("menos de 2 GiB livres para o espelho temporário")
                    print(f"Catalogando {uf}, sem executar geoprocessamento.", flush=True)
                    with tempfile.TemporaryDirectory(prefix=f"{uf}-", dir=raiz_temp) as espelho:
                        armazem = armazem_cls(
                            *destino, Path(espelho), privado=True, token=os.environ.get("RAIZ_DADOS_PRIVADOS_TOKEN", "")
                        )
                        try:
                            etapa = "trava_uf"
                            with armazem._trava(f"trava-publicar-{uf}", 1800):
                                etapa = "seguranca_processamento"
                                conferir_processamento_seguro(relatorio)
                                etapa = "consultar_arquivos"
                                presentes = {a["name"] for a in arquivos_produto(armazem)}
                                if f"raiz_{uf}.tar.gz" in presentes:
                                    etapa, arquivo_atual = "publicar_uf", f"raiz_{uf}.tar.gz"
                                    armazem.publicar(uf)
                                else:
                                    # Controle/geo pode existir antes dos CSV.
                                    # Descreve seus bytes sem inventar previsões
                                    # nem sobrescrever o estado do motor.
                                    relatorio["sem_pacote_tabular"].append(uf)
                                etapa, arquivo_atual = "reler_indice", "estados.json"
                                indice = armazem.manifesto(fresco=True)
                                etapa, arquivo_atual = "consultar_arquivos", None
                                for asset in arquivos_produto(armazem):
                                    if uf_do_asset(asset["name"]) == uf:
                                        etapa, arquivo_atual = "conferir_arquivo", asset["name"]
                                        conferir_arquivo(armazem, asset, indice)
                                        relatorio["arquivos_conferidos"][
                                            "privado/" + nome_no_relatorio(asset["name"])
                                        ] = True
                                        etapa, arquivo_atual = "reler_indice", "estados.json"
                                        indice = armazem.manifesto(fresco=True)
                            etapa, arquivo_atual = "catalogar_basico", None
                            catalogar_publico(aberto, uf)
                            relatorio["concluidas"].append(uf)
                            relatorio["pendentes"].remove(uf)
                        finally:
                            armazem.cli.close()
                except Exception as erro:
                    registrar_falha(relatorio, uf, etapa, arquivo_atual, erro)
                    resposta = getattr(erro, "response", None)
                    relatorio["recuperacao_pendente"] = any((pasta_temp / "recuperacao-release").glob("*.json"))
                    if (
                        isinstance(erro, ProcessamentoInseguro)
                        or relatorio["recuperacao_pendente"]
                        or getattr(resposta, "status_code", None) in {403, 429}
                    ):
                        relatorio["adiado_por_cota"] = relatorio.get("adiado_por_cota", False) or resposta_de_cota(
                            resposta
                        )
                        relatorio["interrompido"] = True
                        salvar_relatorio(relatorio)
                        break
                relatorio["duracao_segundos"] = round(time.monotonic() - inicio, 1)
                salvar_relatorio(relatorio)
            if (
                incluir_globais
                and time.monotonic() < fim
                and relatorio["seguranca_processamento"]["seguro"]
                and not relatorio.get("adiado_por_cota")
                and not relatorio.get("interrompido")
            ):
                etapa, arquivo_atual = "orcamento_api", None
                try:
                    if not conferir_orcamento(relatorio):
                        raise ProcessamentoInseguro(
                            "Cota insuficiente para os arquivos globais; checkpoint preservado."
                        )
                    etapa = "trava_global"
                    with geral._trava():
                        etapa = "seguranca_processamento"
                        conferir_processamento_seguro(relatorio)
                        etapa, arquivo_atual = "catalogar_lotes", None
                        relatorio["lotes"] = catalogar_lotes(geral, raiz_temp)
                        etapa, arquivo_atual = "publicar_globais", "estados.json"
                        geral._gravar_indice({})  # cartão, CAD Trust agregado e ficha do índice
                        etapa = "reler_indice"
                        indice = geral.manifesto(fresco=True)
                        etapa, arquivo_atual = "consultar_arquivos", None
                        for asset in arquivos_produto(geral):
                            nome = asset["name"]
                            if uf_do_asset(nome) or eh_ficha(nome) or nome == "estados.json":
                                continue
                            etapa, arquivo_atual = "conferir_arquivo", nome
                            conferir_arquivo(geral, asset, indice)
                            relatorio["arquivos_conferidos"]["privado/" + nome_no_relatorio(nome)] = True
                            etapa, arquivo_atual = "reler_indice", "estados.json"
                            indice = geral.manifesto(fresco=True)
                        # O índice muda quando a ficha de um arquivo avulso entra;
                        # confira os bytes finais, incluindo todas as fichas globais.
                        etapa, arquivo_atual = "reler_indice", "estados.json"
                        indice = geral.manifesto(fresco=True)
                        etapa, arquivo_atual = "consultar_arquivos", None
                        for asset in arquivos_produto(geral):
                            if not uf_do_asset(asset["name"]):
                                etapa, arquivo_atual = "conferir_arquivo", asset["name"]
                                conferir_arquivo(geral, asset, indice)
                                relatorio["arquivos_conferidos"]["privado/" + nome_no_relatorio(asset["name"])] = True
                        etapa, arquivo_atual = "catalogar_basico", None
                        catalogar_publico(aberto)
                        relatorio["global_concluido"] = True
                except Exception as erro:
                    registrar_falha(relatorio, "global", etapa, arquivo_atual, erro)
                    relatorio["recuperacao_pendente"] = any((pasta_temp / "recuperacao-release").glob("*.json"))
            relatorio["duracao_segundos"] = round(time.monotonic() - inicio, 1)
            relatorio["disco_livre_bytes"] = shutil.disk_usage(raiz_temp).free
            salvar_relatorio(relatorio)
        finally:
            geral.cli.close()
            aberto.cli.close()
    situacao_global = "concluídos" if relatorio["global_concluido"] else "pendentes"
    if not incluir_globais:
        situacao_global = "fora desta finalização de UF"
    resumo = (
        "\n### Metadados do Release\n\n"
        f"UFs concluídas: {', '.join(relatorio['concluidas']) or 'nenhuma'}.\n\n"
        f"UFs pendentes: {', '.join(relatorio['pendentes']) or 'nenhuma'}.\n\n"
        f"Arquivos globais: {situacao_global}.\n\n"
        f"Arquivos conferidos: {len(relatorio['arquivos_conferidos'])}. "
        "A assinatura cobre os bytes publicados ou verificados por este job; não certifica créditos de carbono.\n\n"
        "Para retomar, execute o mesmo workflow com as UFs pendentes. As entregas anteriores permanecem no Release.\n"
        + (
            "\nSe faltam apenas os arquivos globais, marque somente_globais para evitar reprocessar as UFs.\n"
            if incluir_globais and not relatorio["pendentes"] and not relatorio["global_concluido"]
            else ""
        )
        + (
            "\nA cota da API adiou parte da entrega; consulte o relatório "
            "e os originais no arquivo privado de recuperação.\n"
            if relatorio.get("adiado_por_cota")
            else ""
        )
        + (
            "\nHá originais preservados como assets imutáveis no arquivo privado; "
            "confira os manifestos autenticados antes de retomar.\n"
            if relatorio.get("recuperacao_pendente")
            else ""
        )
    )
    print(resumo, flush=True)
    if caminho := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(caminho).open("a", encoding="utf-8") as arquivo:
            arquivo.write(resumo)
    return relatorio


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--reservar", action="store_true")
    grupo.add_argument("--publicar", action="store_true")
    grupo.add_argument(
        "--finalizar-unidade",
        action="store_true",
        help="Finaliza a UF no mesmo job do executor, usando sua reserva existente.",
    )
    parser.add_argument("--limite-minutos", type=float, default=280)
    parser.add_argument(
        "--somente-globais",
        action="store_true",
        default=os.environ.get("RAIZ_CATALOGO_SOMENTE_GLOBAIS", "").lower() in {"true", "1"},
        help="Retoma apenas os arquivos globais; não combina com uma lista de UFs.",
    )
    args = parser.parse_args()
    ufs = [u.upper() for u in re.split(r"[\s,;]+", os.environ.get("RAIZ_CATALOGO_UFS", "")) if u]
    if args.somente_globais and ufs:
        raise ValueError("somente_globais não pode ser combinado com UFs específicas")
    if args.finalizar_unidade:
        if args.somente_globais or ufs:
            raise ValueError("finalizar-unidade usa somente a UF da reserva, sem filtros adicionais")
        unidade = os.environ.get("UNIDADE", "")
        relatorio = publicar(
            minutos_para_finalizar(), [unidade.split("-", 1)[0]], incluir_globais=False, unidade_reservada=unidade
        )
        return int(bool(relatorio["pendentes"] or relatorio["falhas"]))
    if args.reservar:
        reservar_vaga()
        return 0
    relatorio = publicar(args.limite_minutos, [] if args.somente_globais else ufs or None)
    return int(bool(relatorio["pendentes"] or relatorio["falhas"] or not relatorio["global_concluido"]))


def executar_cli() -> int:
    try:
        return main()
    except Exception as erro:
        print(
            f"Não foi possível concluir a catalogação ({type(erro).__name__}); consulte o relatório seguro.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(executar_cli())
