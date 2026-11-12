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
import os
import re
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
UNIDADE = "catalogo"
COMMIT_TRAVAS_UF = "1e6d6f61bd8564f0546dbb453339e102b5531f54"
_COMPATIBILIDADE: dict[tuple[str, str], bool] = {}
_CHECKOUT_HEAD: dict[tuple[str, str], bool] = {}


class ProcessamentoInseguro(RuntimeError):
    """O catálogo deve terminar sem alterar dados nem cancelar o processamento."""


def checkout_do_head(repo: str, sha: str, fila) -> bool:
    """Reconhece só o checkout padrão exato dos workflows anteriores à matriz.ref.

    Sem dependência YAML antes do uv sync: formatos alternativos, aliases e
    parâmetros no checkout são recusados. O conteúdo vem do commit imutável.
    """
    chave = (repo, sha)
    if chave not in _CHECKOUT_HEAD:
        objeto = fila.api(f"repos/{repo}/contents/.github/workflows/processar-estados.yml?ref={sha}")
        if objeto.get("encoding") != "base64":
            raise ValueError("workflow do checkout não confirmado")
        texto = base64.b64decode("".join(objeto["content"].split()), validate=True).decode("utf-8")
        blocos = re.findall(r"^  processar:\s*\n(.*?)(?=^  [^ #\n][^\n]*:|\Z)", texto, re.M | re.S)
        correto = False
        if len(blocos) == 1 and not re.search(r"(?:^|\s)[&*][A-Za-z_]|<<:", blocos[0]):
            passos = re.split(r"(?=^      - )", blocos[0], flags=re.M)
            checkouts = [p for p in passos if "actions/checkout@" in p]
            if len(checkouts) == 1:
                linhas = [
                    linha.strip()
                    for linha in checkouts[0].splitlines()
                    if linha.strip() and not linha.lstrip().startswith("#")
                ]
                correto = linhas == ["- uses: actions/checkout@v4"]
        _CHECKOUT_HEAD[chave] = correto
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
        "commit_minimo": COMMIT_TRAVAS_UF,
        "conferido_em": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seguro": False,
        "rodadas_legadas": [],
        "pedidos_legados": [],
        "checkouts_head_confirmados": [],
    }
    try:
        _, estado = fila.Repositorio().ler()
        reservas = [r for r in estado["reservas"] if rodar._e_unidade(r["unidade"])]
        runs = fila.rodadas(repo, "processar-estados.yml", {r["run_id"] for r in reservas})

        def compativel(sha):
            if not isinstance(sha, str) or not re.fullmatch(r"[a-fA-F0-9]{40}", sha):
                raise ValueError("referência do código não confirmada")
            chave = (repo, sha)
            if chave not in _COMPATIBILIDADE:
                comparacao = fila.api(f"repos/{repo}/compare/{COMMIT_TRAVAS_UF}...{sha}")
                status = comparacao.get("status")
                if status not in {"ahead", "identical", "behind", "diverged"}:
                    raise ValueError("ancestralidade do código não confirmada")
                _COMPATIBILIDADE[chave] = status in {"ahead", "identical"}
            return _COMPATIBILIDADE[chave]

        for run_id, run in sorted(runs.items()):
            if run["status"] == "completed":
                continue
            if not str(run_id).isdigit() or run["status"] not in fila.ESTADOS_ATIVOS:
                raise ValueError("situação da rodada não confirmada")
            unidades = sorted({j["name"] for j in run["jobs"] if rodar._e_unidade(j.get("name", ""))})
            if compativel(run.get("head_sha")):
                for job in run["jobs"]:
                    if rodar._e_unidade(job.get("name", "")) and job["status"] != "completed":
                        if not any(r["run_id"] == run_id and r["unidade"] == job["name"] for r in reservas):
                            # Um rerun pode repetir matrix.ref depois que a reserva
                            # original saiu da fila; head_sha não prova esse checkout.
                            if not checkout_do_head(repo, run["head_sha"], fila):
                                raise ValueError("referência efetiva da matriz não confirmada")
                            if run_id not in resultado["checkouts_head_confirmados"]:
                                resultado["checkouts_head_confirmados"].append(run_id)
            refs = {run.get("head_sha")}
            for reserva in reservas:
                if reserva["run_id"] != run_id:
                    continue
                jobs = [j for j in run["jobs"] if j.get("name") == reserva["unidade"]]
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
            "Catálogo bloqueado: processamento sem travas por UF ou segurança não confirmada"
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


def contexto_actions() -> str:
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_JOB") != UNIDADE:
        raise RuntimeError("execute pelo job catalogo do workflow Publicar metadados do Release")
    if not os.environ.get("GITHUB_RUN_ID") or not os.environ.get("GITHUB_REPOSITORY"):
        raise RuntimeError("identificação do Actions ausente; não inicio processamento")
    return os.environ["GITHUB_RUN_ID"]


def confirmar_reserva() -> None:
    run_id = contexto_actions()
    fila, _ = modulos_fila()
    _, estado = fila.Repositorio().ler()
    if not any(r["run_id"] == run_id and r["unidade"] == UNIDADE for r in estado["reservas"]):
        raise RuntimeError("job catalogo sem reserva global; nenhum arquivo será processado")


def reservar_vaga() -> None:
    run_id = contexto_actions()
    conferir_processamento_seguro()  # não ocupa uma vaga esperando os jobs legados
    fila, rodar = modulos_fila()
    _, estado = fila.Repositorio().ler()
    if any(r["run_id"] == run_id and r["unidade"] == UNIDADE for r in estado["reservas"]):
        return  # nova tentativa do mesmo run; a reserva ainda ocupa uma vaga
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
    )
    if [p["unidade"] for p in escolhidos] != [UNIDADE]:
        raise RuntimeError("sem vaga entre os 15 jobs de processamento; tente novamente após uma vaga ser liberada")
    print("Uma vaga global reservada para o catálogo; nenhum job existente foi interrompido.", flush=True)


def eh_ficha(nome: str) -> bool:
    return nome == "croissant.json" or nome.startswith("croissant_")


def uf_do_asset(nome: str) -> str | None:
    resultado = re.search(r"_([A-Z]{2})\.(?:tar\.gz|parquet|json)(?:\.json)?$", nome)
    return resultado[1] if resultado else None


def classe_armazem():
    from raiz.atestacao import registrar
    from raiz.executor.armazem import ArmazemRelease

    class ArmazemCatalogo(ArmazemRelease):
        def _baixar_asset(self, nome, fresco=False):
            dados = super()._baixar_asset(nome, fresco=True)
            if dados is not None:
                # Hash dos bytes efetivamente lidos. Upload posterior com o mesmo
                # nome substitui esse hash pelo dos bytes novos em atestar.txt.
                registrar(nome, dados)
            return dados

    return ArmazemCatalogo


def referencias(indice: dict) -> dict:
    fichas = dict(indice.get("fichas") or {})
    for uf, entrada in indice.get("estados", {}).items():
        fichas.update(entrada.get("fichas") or {})
        if entrada.get("croissant"):
            fichas[f"raiz_{uf}.tar.gz"] = entrada["croissant"]
    return fichas


def checksums() -> dict[str, str]:
    caminho = Path(os.environ["RUNNER_TEMP"]) / "atestar.txt"
    if not caminho.exists():
        return {}
    return {nome: digest for digest, nome in (linha.split("  ", 1) for linha in caminho.read_text().splitlines())}


def conferir_arquivo(armazem, asset: dict, indice: dict) -> str:
    """Confere ficha e bytes sob a trava apropriada; retorna o digest verificado."""
    nome = asset["name"]
    digest_api = (asset.get("digest") or "").removeprefix("sha256:")
    digest = checksums().get(nome)
    dados = None
    if not digest or digest != digest_api:
        dados = armazem._baixar_asset(nome, fresco=True)
        if dados is None:
            raise RuntimeError(f"arquivo desapareceu durante a leitura: {nome}")
        digest = hashlib.sha256(dados).hexdigest()
        if digest_api and re.fullmatch(r"[a-fA-F0-9]{64}", digest_api) and digest != digest_api.lower():
            raise RuntimeError(f"bytes divergentes do digest da API: {nome}")
    if eh_ficha(nome):
        return digest
    if nome == "estados.json":
        referencia = {"url": armazem.url("croissant_estados.json")}
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
        d.get("contentUrl") == armazem.url(nome) and d.get("sha256") == digest for d in ficha.get("distribution", [])
    )
    if not corresponde:
        # A ficha dos CSV precisa conservar os esquemas, não ser substituída
        # por uma ficha genérica em caso de erro ou publicação legada concorrente.
        if re.fullmatch(r"raiz_[A-Z]{2}\.tar\.gz", nome) or nome == "estados.json":
            raise RuntimeError(f"ficha desatualizada para {nome}; refaça a catalogação da unidade")
        dados = dados if dados is not None else armazem._baixar_asset(nome, fresco=True)
        if dados is None:
            raise RuntimeError(f"arquivo não encontrado: {nome}")
        armazem.catalogar_arquivo(nome, dados, asset.get("content_type") or "application/octet-stream")
    return digest


def salvar_relatorio(relatorio: dict) -> None:
    pasta = Path(os.environ["RUNNER_TEMP"])
    destino = pasta / "catalogo-metadados.json"
    novo = destino.with_suffix(".tmp")
    novo.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    novo.replace(destino)


def registrar_falha(relatorio: dict, unidade: str, etapa: str, arquivo: str | None, erro: Exception) -> None:
    """Guarda pontos do código, nunca str(erro), variáveis locais ou linhas de fonte."""
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


def publicar(limite_minutos: float = 280, ufs: list[str] | None = None, fabrica=None) -> dict:
    """Processa um estado por vez. Falhas preservam os estados já publicados."""
    confirmar_reserva()
    if limite_minutos <= 0 or limite_minutos > 300:
        raise ValueError("o limite deve ficar entre zero e 300 minutos, com margem para atestar")
    inicio = time.monotonic()
    fim = inicio + limite_minutos * 60
    repo = os.environ["GITHUB_REPOSITORY"]
    pasta_temp = Path(os.environ["RUNNER_TEMP"])
    relatorio = {
        "concluidas": [],
        "pendentes": [],
        "falhas": [],
        "arquivos_conferidos": {},
        "global_concluido": False,
        "sem_pacote_tabular": [],
    }
    conferir_processamento_seguro(relatorio)
    armazem_cls = fabrica or classe_armazem()
    with tempfile.TemporaryDirectory(prefix="raiz-catalogo-", dir=pasta_temp) as temporaria:
        raiz_temp = Path(temporaria)
        geral = armazem_cls(repo, "dados", raiz_temp / "geral")
        try:
            assets = geral._release()["assets"]
            existentes = sorted({uf for a in assets if not eh_ficha(a["name"]) and (uf := uf_do_asset(a["name"]))})
            escolhidas = existentes if not ufs else sorted(set(ufs))
            desconhecidas = set(escolhidas) - set(existentes)
            if desconhecidas:
                raise ValueError(f"estados sem arquivos no Release: {', '.join(sorted(desconhecidas))}")
            relatorio["pendentes"] = list(escolhidas)
            salvar_relatorio(relatorio)
            for uf in escolhidas:
                if time.monotonic() >= fim:
                    break
                etapa, arquivo_atual = "espaco_em_disco", None
                try:
                    if shutil.disk_usage(raiz_temp).free < 2 * 1024**3:
                        raise RuntimeError("menos de 2 GiB livres para o espelho temporário")
                    print(f"Catalogando {uf}, sem executar geoprocessamento.", flush=True)
                    with tempfile.TemporaryDirectory(prefix=f"{uf}-", dir=raiz_temp) as espelho:
                        armazem = armazem_cls(repo, "dados", Path(espelho))
                        try:
                            etapa = "trava_uf"
                            with armazem._trava(f"trava-publicar-{uf}", 1800):
                                etapa = "seguranca_processamento"
                                conferir_processamento_seguro(relatorio)
                                etapa = "consultar_arquivos"
                                presentes = {a["name"] for a in armazem._release()["assets"]}
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
                                for asset in armazem._release()["assets"]:
                                    if uf_do_asset(asset["name"]) == uf:
                                        etapa, arquivo_atual = "conferir_arquivo", asset["name"]
                                        relatorio["arquivos_conferidos"][asset["name"]] = conferir_arquivo(
                                            armazem, asset, indice
                                        )
                                        etapa, arquivo_atual = "reler_indice", "estados.json"
                                        indice = armazem.manifesto(fresco=True)
                            relatorio["concluidas"].append(uf)
                            relatorio["pendentes"].remove(uf)
                        finally:
                            armazem.cli.close()
                except Exception as erro:
                    registrar_falha(relatorio, uf, etapa, arquivo_atual, erro)
                    if isinstance(erro, ProcessamentoInseguro):
                        salvar_relatorio(relatorio)
                        break
                relatorio["duracao_segundos"] = round(time.monotonic() - inicio, 1)
                salvar_relatorio(relatorio)
            if time.monotonic() < fim and relatorio["seguranca_processamento"]["seguro"]:
                etapa, arquivo_atual = "trava_global", None
                try:
                    with geral._trava():
                        etapa = "seguranca_processamento"
                        conferir_processamento_seguro(relatorio)
                        etapa, arquivo_atual = "publicar_globais", "estados.json"
                        geral._gravar_indice({})  # cartão, CAD Trust agregado e ficha do índice
                        etapa = "reler_indice"
                        indice = geral.manifesto(fresco=True)
                        etapa, arquivo_atual = "consultar_arquivos", None
                        for asset in geral._release()["assets"]:
                            nome = asset["name"]
                            if uf_do_asset(nome) or eh_ficha(nome) or nome == "estados.json":
                                continue
                            etapa, arquivo_atual = "conferir_arquivo", nome
                            relatorio["arquivos_conferidos"][nome] = conferir_arquivo(geral, asset, indice)
                            etapa, arquivo_atual = "reler_indice", "estados.json"
                            indice = geral.manifesto(fresco=True)
                        # O índice muda quando a ficha de um arquivo avulso entra;
                        # confira os bytes finais, incluindo todas as fichas globais.
                        etapa, arquivo_atual = "reler_indice", "estados.json"
                        indice = geral.manifesto(fresco=True)
                        etapa, arquivo_atual = "consultar_arquivos", None
                        for asset in geral._release()["assets"]:
                            if not uf_do_asset(asset["name"]):
                                etapa, arquivo_atual = "conferir_arquivo", asset["name"]
                                relatorio["arquivos_conferidos"][asset["name"]] = conferir_arquivo(geral, asset, indice)
                        relatorio["global_concluido"] = True
                except Exception as erro:
                    registrar_falha(relatorio, "global", etapa, arquivo_atual, erro)
            relatorio["duracao_segundos"] = round(time.monotonic() - inicio, 1)
            relatorio["disco_livre_bytes"] = shutil.disk_usage(raiz_temp).free
            salvar_relatorio(relatorio)
        finally:
            geral.cli.close()
    resumo = (
        "\n### Metadados do Release\n\n"
        f"UFs concluídas: {', '.join(relatorio['concluidas']) or 'nenhuma'}.\n\n"
        f"UFs pendentes: {', '.join(relatorio['pendentes']) or 'nenhuma'}.\n\n"
        f"Arquivos conferidos: {len(relatorio['arquivos_conferidos'])}. "
        "A assinatura cobre os bytes publicados ou verificados por este job; não certifica créditos de carbono.\n\n"
        "Para retomar, execute o mesmo workflow com as UFs pendentes. As entregas anteriores permanecem no Release.\n"
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
    parser.add_argument("--limite-minutos", type=float, default=280)
    args = parser.parse_args()
    if args.reservar:
        reservar_vaga()
        return 0
    ufs = [u.upper() for u in re.split(r"[\s,;]+", os.environ.get("RAIZ_CATALOGO_UFS", "")) if u]
    relatorio = publicar(args.limite_minutos, ufs)
    return int(bool(relatorio["pendentes"] or relatorio["falhas"] or not relatorio["global_concluido"]))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError) as erro:
        print(f"Não foi possível concluir a catalogação: {erro}", file=sys.stderr)
        sys.exit(1)
