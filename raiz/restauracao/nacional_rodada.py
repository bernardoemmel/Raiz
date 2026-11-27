"""Atualização incremental dos lotes privados a partir dos estados publicados.

As previsões incompatíveis permanecem identificadas. A manutenção do motor usa
sua fila existente; não reetiqueta previsões nem recalcula o Pará congelado.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pandas as pd

from raiz import restauracao as R
from raiz.comprometida import status as ST
from raiz.executor.transferencia_privada import arquivo_privado, empacotar, enviar_arquivo, extrair
from raiz.pedidos.campos import CamposPedido
from raiz.restauracao import catalogo as C
from raiz.restauracao import desbloqueio as D
from raiz.restauracao import nacional as N
from raiz.restauracao import nacional_fontes as F
from raiz.restauracao import nacional_pa as PA
from raiz.restricoes import status as RS

PONTEIRO = "lote_nacional_atual.json"


def versao_publicador():
    return hashlib.sha256(
        Path(__file__).read_bytes() + Path(PA.__file__).read_bytes() + D.regra()["versao_completa"].encode()
    ).hexdigest()


def municipios() -> dict[str, list[int]]:
    prefixos = dict(
        zip(
            (
                "12",
                "27",
                "16",
                "13",
                "29",
                "23",
                "53",
                "32",
                "52",
                "21",
                "51",
                "50",
                "31",
                "15",
                "25",
                "41",
                "26",
                "22",
                "33",
                "24",
                "43",
                "11",
                "14",
                "42",
                "35",
                "28",
                "17",
            ),
            N.UFS,
            strict=True,
        )
    )
    saida = {u: [] for u in N.UFS}
    with (Path(__file__).parents[1] / "executor/municipios.csv").open() as f:
        for linha in csv.DictReader(f):
            saida[prefixos[linha["codigo_uf"]]].append(int(linha["codigo_ibge"]))
    return saida


def _ler_atual(arm) -> dict:
    arm._exigir_privado()
    dados = arm._baixar_asset(PONTEIRO, fresco=True)
    atual = json.loads(dados) if dados else {"acesso": "privado", "ufs": {}, "manutencao_solicitada": {}}
    if atual.get("acesso") != "privado" or not isinstance(atual.get("ufs"), dict):
        raise ValueError("Ponteiro do catálogo não obedece ao contrato privado.")
    return atual


def _gravar_atual(arm, atual: dict, pasta: Path) -> dict:
    arquivo = pasta / "atual.json"
    C.gravar_json(arquivo, atual)
    ref = F.publicar(arm, arquivo, "lote_nacional_snapshot", ".json")
    enviar_arquivo(PONTEIRO, arquivo, arm=arm)
    arm._exigir_privado()
    if arm._baixar_asset(PONTEIRO, fresco=True) != arquivo.read_bytes():
        raise ValueError("Ponteiro do lote não conferiu após a publicação.")
    return ref


def _restaurar_indice(arm, ref: dict, indice: Path, trabalho: Path) -> list[dict]:
    arquivo = trabalho / ref["nome"]
    F.baixar(arm, ref, arquivo)
    extrair(arquivo, indice)
    return [json.loads(p.read_text()) for p in indice.glob("particoes/*/*/*/particao.json")]


def _importar_pa_historico(arm, pasta: Path) -> tuple[Path, dict]:
    # Validador do snapshot original, sem chamar o cliente/fluxo privilegiado do CI.
    # O transporte aqui é o arquivo privado e todas as referências são ancoradas.
    from scripts import testar_para_privado as T

    pasta.mkdir(mode=0o700, parents=True, exist_ok=True)
    pasta.chmod(0o700)
    iniciais = {
        "manifesto.json": ("lote_PA_central_r11_retomada_43299409156_1_b29eb3fe8887a676.json", T.MANIFESTO),
        "plano.json": ("retomada_PA_43285608189_plano_c4ebf38619d68fa3.json", T.PLANO),
    }
    for nome, (ativo, ref) in iniciais.items():
        F.baixar(arm, {"nome": ativo, "sha256": ref.sha256, "bytes": ref.tamanho}, pasta / nome)
    manifesto, plano, _ = T._contrato(pasta)
    F.baixar(arm, plano["entradas"], pasta / "entradas.tar.gz")
    F.baixar(arm, manifesto["arquivos"]["previsoes"], pasta / "previsoes.tar.gz")
    T._layout(pasta)
    fonte = T.conferir_preparado(pasta)
    pacote = pasta / "fonte_completa.tar.gz"
    empacotar(fonte, pacote, prefixo="PA")
    ref = F.publicar(arm, pacote, "lote_fonte_PA_historica", ".tar.gz")
    return fonte, {
        "tipo": "historico_PA144_preservado",
        "fontes": {"completa": {"copia_imutavel": ref}},
        "manifesto_origem_sha256": T.MANIFESTO.sha256,
    }


def completar_comprometida(fonte: Path, *, limites=None, cobertura=None, hoje: str | None = None) -> dict:
    """Garante comprometida_<mun>.csv atual em cada município da UF antes de indexar.

    O pacote do estado pode não trazer o arquivo (estados processados antes da coleta, o Pará histórico) ou trazer
    uma versão de coleta antiga. Aqui ele é refeito só com geo_<mun>.parquet e os limites do Release insumos, sem
    refazer o funil. Sem limites coletados, nada é escrito: o imóvel fica não verificado (nunca livre).
    """
    from raiz.comprometida import status as ST

    if limites is None and cobertura is None:
        limites, cobertura = ST.carregar_limites()
    assinatura = ST.assinatura()
    if limites is None or not assinatura:
        return {"situacao": "sem_limites", "refeitos": 0, "em_dia": 0, "sem_geometria": 0}
    versao = f"{ST.versao()}+{assinatura}"
    refeitos = em_dia = sem_geo = 0
    for arquivo in sorted(fonte.glob("imoveis_*.csv")):
        cod = int(arquivo.stem.rsplit("_", 1)[1])
        atual = fonte / f"comprometida_{cod}.csv"
        if atual.exists():
            try:
                vs = set(pd.read_csv(atual, usecols=["comprometida_versao"]).comprometida_versao.dropna())
            except ValueError:
                vs = set()
            if vs == {versao}:
                em_dia += 1
                continue
        if not (fonte / f"geo_{cod}.parquet").exists():
            sem_geo += 1  # sem polígono: o índice deixa a fazenda não verificada
            continue
        ST.escrever_municipio(fonte, cod, limites=limites, cobertura=cobertura, hoje=hoje)
        refeitos += 1
    return {"situacao": "ok", "versao": versao, "refeitos": refeitos, "em_dia": em_dia, "sem_geometria": sem_geo}


def completar_restricoes(fonte: Path, *, camadas=None) -> dict:
    """Garante restricoes_<mun>.csv atual em cada município da UF antes de indexar (SICAR completo, SIGMINE, autos
    do Ibama e Lista Suja, raiz/restricoes/status.py).

    Mesma lógica da terra já comprometida: refaz só o que falta ou está velho, a partir de geo_<mun>.parquet e da coleta
    do Release insumos, sem refazer o funil. Sem coleta, nada é escrito: a fazenda fica não verificada (nunca livre).
    """
    camadas = camadas if camadas is not None else RS.Camadas()
    assinatura = RS.assinatura(camadas.pasta)
    if not assinatura:
        return {"situacao": "sem_coleta", "refeitos": 0, "em_dia": 0, "sem_geometria": 0}
    versao = f"{RS.versao()}+{assinatura}"
    refeitos = em_dia = sem_geo = 0
    for arquivo in sorted(fonte.glob("imoveis_*.csv")):
        cod = int(arquivo.stem.rsplit("_", 1)[1])
        atual = fonte / f"restricoes_{cod}.csv"
        if atual.exists():
            try:
                vs = set(pd.read_csv(atual, usecols=["restricoes_versao"]).restricoes_versao.dropna())
            except ValueError:
                vs = set()
            if vs == {versao}:
                em_dia += 1
                continue
        if not (fonte / f"geo_{cod}.parquet").exists():
            sem_geo += 1  # sem polígono: o índice deixa a fazenda não verificada
            continue
        RS.escrever_municipio(fonte, cod, camadas=camadas)
        refeitos += 1
    return {"situacao": "ok", "versao": versao, "refeitos": refeitos, "em_dia": em_dia, "sem_geometria": sem_geo}


def _vazios(pasta: Path, uf: str) -> list[int]:
    arquivo = pasta / f"sem_imoveis_{uf}.csv"
    if not arquivo.exists():
        return []
    with arquivo.open() as f:
        linhas = list(csv.DictReader(f))
    campos = ("cod_ibge", "cod_municipio_ibge", "codigo_ibge", "cod_municipio")
    return sorted({int(next(li[c] for c in campos if li.get(c))) for li in linhas})


def atualizar(arm, trabalho: Path, *, max_ufs: int = 27, limite_minutos: float = 90) -> dict:
    """Uma rodada retoma partições por conteúdo e promove somente pacotes recuperáveis."""
    if not 1 <= max_ufs <= 27 or not 1 <= limite_minutos <= 240:
        raise ValueError("Orçamento da atualização inválido.")
    trabalho.mkdir(mode=0o700, parents=True, exist_ok=True)
    atual, esperados = _ler_atual(arm), municipios()
    arm._exigir_privado()
    ativos = {a["name"]: a for a in arm._assets()}
    rodada_pa = PA.referencia(arm, ativos)
    estado = arm.manifesto(fresco=True)
    novas, inicio = [], time.monotonic()
    limites, cobertura = ST.carregar_limites()  # uma leitura para todas as UFs
    restricoes = RS.Camadas()  # idem para as restrições nacionais
    for uf in N.UFS:
        rodada = rodada_pa if uf == "PA" else None
        nomes = (f"raiz_{uf}.tar.gz", f"raiz_geo_{uf}.tar.gz")
        historico = (
            uf == "PA"
            and R.versao() == "restauracao-2026d+a84f9789"
            and (estado.get("estados", {}).get(uf, {}).get("tabelas", {}).get("desenvolvedor", 0) < 144)
        )
        if not historico and not rodada and any(nome not in ativos for nome in nomes):
            continue
        identidade = {
            "ativos": rodada["manifesto_sha256"]
            if rodada
            else ("PA144_historico" if historico else {n: ativos[n]["id"] for n in nomes}),
            "modelo": R.versao(),
            "cenario": R.cenario()["cenario"],
            "indice": C.versao_indice(),
            "importador_pa": hashlib.sha256(Path(PA.__file__).read_bytes()).hexdigest() if rodada else None,
            # coleta nova da terra já comprometida reindexa a UF (só a camada muda; previsões ficam)
            "comprometida": f"{ST.versao()}+{ST.assinatura() or 'sem_limites'}",
            # idem para as restrições nacionais (SICAR completo, SIGMINE, autos do Ibama, Lista Suja)
            "restricoes": f"{RS.versao()}+{RS.assinatura(restricoes.pasta) or 'sem_coleta'}",
        }
        chave = hashlib.sha256(C._json(identidade)).hexdigest()
        anterior = atual["ufs"].get(uf)
        if anterior and anterior.get("entrada_id") == chave:
            continue
        if len(novas) >= max_ufs or time.monotonic() - inicio > limite_minutos * 60:
            break  # o próximo evento/cron continua por conteúdo, sem apagar as partições publicadas
        pasta = trabalho / uf
        indice = pasta / "indice"
        if anterior:
            _restaurar_indice(arm, anterior["indice"], indice, trabalho)
        if rodada:
            fonte, captura = PA.importar(arm, rodada, pasta / "rodada")
        elif historico:
            fonte, captura = _importar_pa_historico(arm, pasta / "historico")
        else:
            captura = F.capturar_uf(arm, uf, pasta / "captura")
            fonte = pasta / "captura/saida" / uf
        captura = {
            **captura,
            "comprometida": completar_comprometida(fonte, limites=limites, cobertura=cobertura),
            "restricoes": completar_restricoes(fonte, camadas=restricoes),
        }
        partes = []
        for arquivo in sorted(fonte.glob("imoveis_*.csv")):
            cod = int(arquivo.stem.rsplit("_", 1)[1])
            partes.append(
                C.indexar_municipio(fonte, uf, cod, indice, modelo=R.versao(), cenario=R.cenario()["cenario"])
            )
        vazios = _vazios(fonte, uf)
        catalogo = C.consolidar_catalogo(
            partes, indice, municipios_esperados={uf: esperados[uf]}, sem_imoveis={uf: vazios}, proveniencia=captura
        )
        # O pacote contém somente a versão ativa de cada partição, não todos os históricos do cache.
        selecao = [catalogo.name]
        for p in partes:
            selecao.extend(a["caminho"] for a in p["arquivos"].values())
            selecao.append(str(Path(p["arquivos"]["oferta"]["caminho"]).parent / "particao.json"))
        pacote = pasta / "indice.tar.gz"
        empacotar(indice, pacote, incluir=tuple(selecao))
        ref = F.publicar(arm, pacote, f"lote_indice_{uf}", ".tar.gz")
        contagens = {
            k: sum(p["contagens"].get(k, 0) for p in partes)
            for k in ("imoveis", "compativel", "modelo_incompativel", "previsao_ausente", "pequenas")
        }
        atual["ufs"][uf] = {
            "entrada_id": chave,
            "identidade": identidade,
            "indice": ref,
            "catalogo": catalogo.name,
            "fontes": captura,
            "contagens": contagens,
            "sem_imoveis": vazios,
        }
        atual.update(
            modelo_versao=R.versao(),
            indice_versao=C.versao_indice(),
            execucao=os.environ.get("GITHUB_RUN_ID"),
            commit=os.environ.get("GITHUB_SHA"),
        )
        _gravar_atual(arm, atual, trabalho)  # progresso por UF sobrevive a interrupção posterior
        novas.append(uf)
        print(json.dumps({"uf_indexada": uf, "municipios": len(partes), "contagens": contagens}), flush=True)
        shutil.rmtree(pasta)
    return {"atual": atual, "ufs_atualizadas": novas, "segundos": time.monotonic() - inicio}


def reunir_catalogo(arm, atual: dict, trabalho: Path) -> Path:
    """Reúne índices imutáveis. Uma UF antiga permanece declarada, nunca vira cobertura atual."""
    indice = trabalho / "catalogo"
    partes, vazios = [], {}
    for uf, entrada in sorted(atual["ufs"].items()):
        _restaurar_indice(arm, entrada["indice"], indice, trabalho)
        cat, _ = C.abrir_catalogo(indice / entrada["catalogo"])
        if {p["uf"] for p in cat["particoes"]} - {uf}:
            raise ValueError("Índice estadual contém outra UF.")
        partes.extend(cat["particoes"])
        vazios[uf] = entrada["sem_imoveis"]
    return C.consolidar_catalogo(
        partes,
        indice,
        municipios_esperados=municipios(),
        sem_imoveis=vazios,
        proveniencia={"indices": {u: x["indice"] for u, x in atual["ufs"].items()}},
    )


def fontes_selecionadas(arm, atual, resultado, trabalho, cache):
    """Baixa as fontes congeladas só das UFs selecionadas e extrai seus municípios."""
    selecionadas = pd.concat(
        [pd.read_parquet(x["tabela"]["caminho"], columns=["uf", "cod_ibge"]) for x in resultado["opcoes"].values()]
    ).drop_duplicates()
    for uf, grupo in selecionadas.groupby("uf"):
        codigos = set(map(int, grupo.cod_ibge)) - set(cache)
        if not codigos:
            continue
        for nome, ref in atual["ufs"][uf]["fontes"]["fontes"].items():
            ref = ref["copia_imutavel"]
            pacote = trabalho / ref["nome"]
            if not pacote.exists():
                F.baixar(arm, ref, pacote)
            F.extrair_uf(pacote, uf, trabalho / "fontes", geo=nome.startswith("raiz_geo_"), municipios=codigos)
        cache.update({c: trabalho / "fontes" / uf for c in codigos})
    return {int(c): cache[int(c)] for c in selecionadas.cod_ibge}


def resumo_consulta(resultado: dict) -> dict:
    """O que cabe no ponteiro (sem fazenda nem CAR): as três opções, a terra em espera e a sobreposição."""
    espera = resultado.get("terra_em_espera") or {}
    return {
        "opcoes": {
            nome: {
                "fazendas": op["fazendas"],
                "pequenas": op["pequenas"],
                "hectares": op["area_ha"],
                "creditos": op["creditos"],
                "fecha_meta": op.get("fecha_meta"),
                "sobreposicao": op.get("sobreposicao_situacao"),
                "marcadas_risco_sobreposicao": op.get("marcadas_risco_sobreposicao"),
                "sobreposicao_nao_verificadas": op.get("sobreposicao_nao_verificadas"),
                "marcadas_gleba_federal": op.get("marcadas_gleba_federal"),
                "marcadas_restricao_ressalva": op.get("marcadas_restricao_ressalva"),
                "restricao_nao_verificadas": op.get("restricao_nao_verificadas"),
            }
            for nome, op in resultado["opcoes"].items()
        },
        "terra_em_espera": {
            k: espera.get(k) for k in ("incluida_no_pedido", "fazendas", "pequenas", "hectares", "soma_creditos_p50")
        },
        "sobreposicao": (resultado.get("sobreposicao") or {}).get("situacao"),
        "excluidas_ja_comprometidas": (resultado.get("sobreposicao") or {}).get("excluidas_ja_comprometidas"),
        "restricoes_nacionais": {
            k: (resultado.get("restricoes_nacionais") or {}).get(k)
            for k in ("situacao", "excluidas", "ressalvas", "nao_verificadas", "motivos")
        },
        "gleba_federal": {
            k: (resultado.get("gleba_federal") or {}).get(k)
            for k in ("situacao", "modo", "acima_do_limiar", "nao_medidas")
        },
    }


def publicar_pacotes_lote(arm, resultado: dict, trabalho: Path) -> dict:
    """Um ZIP "lote pronto" por opção com fazendas, no arquivo privado (raiz/lote/pronto.py)."""
    from raiz.lote import pronto as LP

    refs = {}
    for opcao, item in resultado["opcoes"].items():
        if not item["fazendas"]:
            continue
        zip_local = trabalho / "lote_pronto" / f"{resultado['id']}_{opcao}.zip"
        info = LP.montar_pacote(resultado, opcao, zip_local)
        refs[opcao] = {**F.publicar(arm, zip_local, f"lote_pronto_{opcao}", ".zip"), "fazendas": info["fazendas"]}
        zip_local.unlink(missing_ok=True)  # o arquivo privado guarda a cópia; o runner não fica com ela
    return refs


def conferir_consultas(atual: dict, *, brasil: bool = True) -> dict:
    """Confere o que foi publicado no ponteiro: toda UF com dados, cada bioma e o Brasil têm as três opções.

    Devolve a lista de faltas e de lotes vazios (com a terra em espera que explica o vazio); não calcula nada.
    """
    consultas = atual.get("consultas", {})
    esperados = [*atual.get("ufs", {}), *(N.BIOMAS if brasil else ()), *(["Brasil"] if brasil else ())]
    faltam = [n for n in esperados if n not in consultas]
    sem_opcoes, sem_resumo, sem_pacote, vazios = [], [], [], []
    for nome in N.ordem_recortes(consultas):
        item = consultas[nome]
        ops = (item.get("resumo") or {}).get("opcoes") or {}
        if item.get("pacote") and not ops:
            sem_resumo.append(nome)  # publicada antes do resumo no ponteiro: refeita na próxima atualização
            continue
        if not item.get("pacote") or set(ops) != set(N.OPCOES):
            sem_opcoes.append(nome)
            continue
        if all(not op["fazendas"] for op in ops.values()):
            espera = item["resumo"].get("terra_em_espera") or {}
            vazios.append({"recorte": nome, "terra_em_espera_fazendas": espera.get("fazendas") or 0})
        elif set(item.get("lote_pronto") or {}) != {o for o, op in ops.items() if op["fazendas"]}:
            sem_pacote.append(nome)
    return {"esperados": len(esperados), "publicados": len(consultas), "faltam": faltam, "sem_tres_opcoes": sem_opcoes,
            "sem_resumo": sem_resumo, "sem_lote_pronto": sem_pacote, "lotes_vazios": vazios}  # fmt: skip


def publicar_consulta(arm, resultado: dict, trabalho: Path) -> dict:
    """Pacote portátil com previsões, decisões revisáveis e resultado financeiro agregado."""
    pasta = Path(resultado["auditoria"]["caminho"]).parent
    portatil = json.loads(json.dumps(resultado))
    for item in [portatil["auditoria"], *[x["tabela"] for x in portatil["opcoes"].values()]]:
        item["caminho"] = Path(item["caminho"]).name
    C.gravar_json(pasta / "lote.json", portatil)
    for opcao, item in resultado["opcoes"].items():
        t = pd.read_parquet(item["tabela"]["caminho"])
        t.to_csv(pasta / f"{opcao}.csv", index=False)
        if resultado["pedido"]["meta"]["tipo"] == "creditos":
            t = t.rename(columns={"pendencias": "salvaguardas_pendencias"})
            resumo = {
                "opcao": opcao,
                "uf": resultado["recorte"]["ufs"][0]
                if len(resultado["recorte"]["ufs"]) == 1
                else "Brasil"
                if resultado["recorte"]["brasil"]
                else "recorte_" + resultado["id"][:12],
                "modelo_versao": resultado["modelo"],
                "versao_modelo_lote": resultado["versao"],
                "volume_creditos": resultado["pedido"]["meta"]["valor"],
                "preco_contrato_usd": resultado["pedido"]["dinheiro"]["preco_venda_usd"],
                "economia": item.get("economia", {}),
            }
            D.gravar(D.relatorio(t, resumo), pasta / "diagnostico" / opcao)
    # resultado.json local pode apontar para o cache do runner; não segue no pacote portátil.
    nomes = (
        "lote.json",
        "decisoes.parquet",
        "diagnostico",
        *(f"{o}.{ext}" for o in N.OPCOES for ext in ("csv", "parquet")),
    )
    pacote = trabalho / f"consulta_{resultado['id']}.tar.gz"
    empacotar(pasta, pacote, incluir=nomes)
    ref = F.publicar(arm, pacote, "lote_nacional_consulta", ".tar.gz")
    return {
        "consulta_id": resultado["id"],
        "catalogo_id": resultado["catalogo_id"],
        "modelo_versao": resultado["modelo"],
        "otimizador_versao": resultado["versao"],
        "publicador_versao": versao_publicador(),
        "recorte": resultado["recorte"],
        "pedido": resultado["pedido"],
        "pacote": ref,
        "tempos": resultado["tempos"],
        "cobertura": resultado["cobertura"],
        "resumo": resumo_consulta(resultado),
    }


def consultar(arm, atual, trabalho, *, recortes=None, pedido=None) -> dict:
    """Atualiza três opções por UF, por bioma e Brasil; cada pedido conserva sua versão."""
    catalogo = reunir_catalogo(arm, atual, trabalho)
    if not atual["ufs"]:
        return {"consultas_publicadas": 0}
    cenario = R.cenario()
    pedido = pedido or CamposPedido(
        dinheiro={"preco_venda_usd": cenario["preco_usd_t"], "fracao_financiada": cenario["fracao_financiada"]}
    )
    pedido = N.pedido_no_cenario(pedido, R.versao(), cenario["cenario"])
    recortes = recortes or {
        **{u: N.normalizar_recorte(ufs=[u]) for u in atual["ufs"]},
        **{b: N.normalizar_recorte(biomas=[b]) for b in N.BIOMAS},
        "Brasil": N.normalizar_recorte(brasil=True),
    }
    cache, publicadas = {}, 0
    id_catalogo = json.loads(catalogo.read_text())["id"]
    for nome in N.ordem_recortes(recortes):  # Amazônia primeiro
        recorte = recortes[nome]
        normalizado = pedido.model_copy(deep=True)
        normalizado.onde.ufs, normalizado.onde.biomas = list(recorte.ufs), list(recorte.biomas)
        normalizado.onde.municipios = [str(m) for m in recorte.municipios]
        anterior = atual.setdefault("consultas", {}).get(nome, {})
        if (
            anterior.get("catalogo_id") == id_catalogo
            and anterior.get("otimizador_versao") == N.versao_nacional()
            and anterior.get("publicador_versao") == versao_publicador()
            and anterior.get("pedido") == normalizado.model_dump()
            and anterior.get("resumo")
            and anterior.get("lote_pronto") is not None
        ):
            continue
        argumentos = dict(modelo=R.versao(), cenario=cenario["cenario"], destino=trabalho / "consultas")
        selecionado = N.montar_tres_opcoes(catalogo, pedido, recorte, **argumentos)
        origens = fontes_selecionadas(arm, atual, selecionado, trabalho, cache)
        completo = (
            N.montar_tres_opcoes(catalogo, pedido, recorte, origens=origens, **argumentos) if origens else selecionado
        )
        atual["consultas"][nome] = publicar_consulta(arm, completo, trabalho)
        atual["consultas"][nome]["lote_pronto"] = publicar_pacotes_lote(arm, completo, trabalho)
        _gravar_atual(arm, atual, trabalho)
        publicadas += 1
        print(json.dumps({"consulta_publicada": nome, "segundos": completo["tempos"]["total_s"]}), flush=True)
    return {"consultas_publicadas": publicadas}


def pedir_manutencao(arm, atual, trabalho):
    """Um pedido por versão da fonte, sem apagar tabelas nem iniciar cálculo fora da fila global."""
    pendentes = []
    for uf, x in atual["ufs"].items():
        if x["contagens"].get("modelo_incompativel", 0) or x["contagens"].get("previsao_ausente", 0):
            if atual.setdefault("manutencao_solicitada", {}).get(uf) != x["entrada_id"]:
                pendentes.append(uf)
    if pendentes:
        repo = os.environ.get("GITHUB_REPOSITORY", "bernardoemmel/Raiz")
        retorno = subprocess.run(
            [
                "gh",
                "workflow",
                "run",
                "processar-estados.yml",
                "--repo",
                repo,
                "--ref",
                "main",
                "-f",
                "ufs=" + " ".join(pendentes),
                "-f",
                "refazer=",
                "-f",
                "continuacao=0",
            ],
            capture_output=True,
            check=False,
        )
        if retorno.returncode:
            raise RuntimeError("Pedido de manutenção não confirmado; nenhuma fonte foi reetiquetada.")
        atual["manutencao_solicitada"].update({u: atual["ufs"][u]["entrada_id"] for u in pendentes})
        _gravar_atual(arm, atual, trabalho)
    return pendentes


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--trabalho", type=Path)
    p.add_argument("--max-ufs", type=int, default=27)
    p.add_argument("--limite-minutos", type=float, default=90)
    p.add_argument("--consultar", action="store_true")
    p.add_argument("--manutencao", action="store_true")
    p.add_argument("--uf", action="append")
    p.add_argument("--bioma", action="append")
    p.add_argument("--brasil", action="store_true")
    p.add_argument("--conferir", action="store_true", help="só confere o que está publicado no ponteiro")
    p.add_argument("--pedido", type=Path, help="JSON CamposPedido; o recorte vem de --uf/--bioma/--brasil")
    args = p.parse_args()
    if args.conferir:
        laudo = conferir_consultas(_ler_atual(arquivo_privado()))
        print(json.dumps(laudo, ensure_ascii=False, indent=2))
        if laudo["sem_tres_opcoes"]:
            raise SystemExit("Há consultas publicadas sem as três opções.")
        return
    with tempfile.TemporaryDirectory(prefix="lote-nacional-") as td:
        arm, trabalho = arquivo_privado(), args.trabalho or Path(td)
        # Serializa ponteiro, manutenção e consultas também entre execuções fora do workflow.
        with arm._trava("trava-lote-nacional", 1800):
            resultado = atualizar(arm, trabalho, max_ufs=args.max_ufs, limite_minutos=args.limite_minutos)
            if args.manutencao:
                pedir_manutencao(arm, resultado["atual"], trabalho)
            if args.consultar:
                recortes = None
                if args.uf or args.bioma or args.brasil:
                    recorte = N.normalizar_recorte(ufs=args.uf, biomas=args.bioma, brasil=args.brasil)
                    recortes = {"pedido_" + hashlib.sha256(C._json(recorte.__dict__)).hexdigest()[:16]: recorte}
                consultar(
                    arm,
                    resultado["atual"],
                    trabalho,
                    recortes=recortes,
                    pedido=CamposPedido.model_validate_json(args.pedido.read_text()) if args.pedido else None,
                )
        print(json.dumps({"ufs_atualizadas": resultado["ufs_atualizadas"], "segundos": resultado["segundos"]}))


if __name__ == "__main__":
    main()
