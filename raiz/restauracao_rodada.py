"""Rodada reproduzível do Pará: fontes congeladas, 144 municípios e lote no arquivo privado.

Executado por ``python -m raiz.restauracao_rodada`` no GitHub Actions. Entradas,
checkpoints, lotes e previsões usam somente a API autenticada do arquivo privado.
A rodada preserva as saídas canônicas do motor e publica seus próprios arquivos.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
from collections import Counter
from pathlib import Path

from raiz.executor.transferencia_privada import arquivo_privado, empacotar, enviar_arquivo

CENARIO = "central_r11"
OPCOES = ("barata", "segura", "compacta")
PACOTES = ("raiz_PA.tar.gz", "raiz_geo_PA.tar.gz")


def _json(arquivo: Path, dado) -> None:
    from raiz.lote import json_seguro

    arquivo.parent.mkdir(parents=True, exist_ok=True)
    temporario = arquivo.with_suffix(arquivo.suffix + ".tmp")
    temporario.write_text(json.dumps(json_seguro(dado), ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(arquivo)


def _ler(arquivo: Path) -> dict:
    return json.loads(arquivo.read_text(encoding="utf-8"))


def sha256(arquivo: Path) -> str:
    h = hashlib.sha256()
    with arquivo.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def municipios_pa() -> set[int]:
    with (Path(__file__).parent / "executor" / "municipios.csv").open(encoding="utf-8") as f:
        cods = {int(x["codigo_ibge"]) for x in csv.DictReader(f) if x["codigo_uf"] == "15"}
    if len(cods) != 144:
        raise ValueError("O catálogo do IBGE não contém os 144 municípios do Pará.")
    return cods


def extrair(pacote: Path, destino: Path, municipios: set[int] | None = None) -> None:
    """Extrai apenas arquivos regulares diretamente em PA; rejeita links e caminhos externos."""
    with tarfile.open(pacote, "r:gz") as tar:
        for membro in tar:
            partes = Path(membro.name).parts
            if membro.isdir():
                continue
            if not membro.isfile() or len(partes) != 2 or partes[0] != "PA" or ".." in partes:
                raise ValueError(f"Caminho inválido no pacote: {membro.name}")
            nome = partes[1]
            m = re.search(r"_(\d{7})\.(csv|parquet)$", nome)
            if municipios is not None and (m is None or int(m[1]) not in municipios):
                continue
            saida = destino / "PA" / nome
            saida.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(membro) as fonte, saida.open("wb") as f:
                shutil.copyfileobj(fonte, f)


def conferir_cobertura(pasta: Path, esperados: set[int] | None = None) -> dict:
    """Município vazio conta apenas com registro explícito; não confunde ausência com zero."""
    esperados = municipios_pa() if esperados is None else set(esperados)
    presentes = {int(f.stem.rsplit("_", 1)[1]) for f in pasta.glob("imoveis_*.csv")}
    vazios: set[int] = set()
    fv = pasta / "sem_imoveis_PA.csv"
    if fv.exists():
        with fv.open(encoding="utf-8") as f:
            for linha in csv.DictReader(f):
                codigo = (
                    linha.get("cod_ibge")
                    or linha.get("cod_municipio_ibge")
                    or linha.get("codigo_ibge")
                    or linha.get("cod_municipio")
                )
                if codigo:
                    vazios.add(int(codigo))
    if presentes & vazios:
        raise ValueError("Município aparece com imóveis e como vazio: conferir a fonte.")
    faltam = esperados - presentes - vazios
    extras = (presentes | vazios) - esperados
    if faltam or extras:
        raise ValueError(f"Cobertura incompleta: faltam {sorted(faltam)}; fora do catálogo {sorted(extras)}.")
    return {"total": len(esperados), "com_imoveis": sorted(presentes), "vazios": sorted(vazios)}


def planejar(pasta: Path, fatias: int = 15) -> list[dict]:
    """Balanceia por contagem de imóveis; toda fazenda, inclusive pequena, segue para cálculo."""
    if fatias < 1:
        raise ValueError("A quantidade de fatias deve ser positiva.")
    contagens = []
    for f in pasta.glob("imoveis_*.csv"):
        with f.open(encoding="utf-8", newline="") as csvfile:
            n = max(sum(1 for _ in csv.reader(csvfile)) - 1, 0)
        contagens.append((n, int(f.stem.rsplit("_", 1)[1])))
    saida = [{"fatia": f"{i:02d}", "municipios": [], "imoveis": 0} for i in range(fatias)]
    for n, cod in sorted(contagens, reverse=True):
        item = min(saida, key=lambda x: (x["imoveis"], x["fatia"]))
        item["municipios"].append(cod)
        item["imoveis"] += n
    return [x for x in saida if x["municipios"]]


def preparar(destino: Path, fatias: int = 15, cenario: str = CENARIO) -> dict:
    """Baixa IDs imutáveis dos assets, guarda SHA256 e congela a mesma entrada para todos os jobs."""
    from raiz import restauracao as R

    R.cenario(cenario)  # recusa cenário desconhecido antes de acessar dados
    if cenario != CENARIO:
        return preparar_referencia_r12(destino, cenario)
    destino.mkdir(parents=True, exist_ok=True)
    arm = arquivo_privado()
    rel = arm._release()
    assets = {a["name"]: a for a in arm._assets(rel)}
    fontes = {}
    for nome in (*PACOTES, "estados.json"):
        if nome not in assets:
            raise ValueError(f"Arquivo privado sem {nome}.")
        a = assets[nome]
        arquivo = destino / nome
        arquivo.write_bytes(arm._baixar_ativo(a))
        if arquivo.stat().st_size != a["size"]:
            raise ValueError(f"Tamanho divergente no download de {nome}.")
        fontes[nome] = {
            "asset_id": a["id"],
            "sha256": sha256(arquivo),
            "bytes": a["size"],
            "atualizado_em": a["updated_at"],
            "url": f"{arm.API}/repos/{arm.repo}/releases/assets/{a['id']}",
        }
    with tempfile.TemporaryDirectory() as td:
        pasta = Path(td)
        extrair(destino / PACOTES[0], pasta)
        cobertura = conferir_cobertura(pasta / "PA")
        plano = planejar(pasta / "PA", fatias)
    snapshot = {
        "repo": arm.repo,
        "release_id": rel["id"],
        "acesso": "privado",
        "cenario": CENARIO,
        "fontes": fontes,
        "cobertura": cobertura,
        "plano": plano,
    }
    _json(destino / "snapshot.json", snapshot)
    return snapshot


def preparar_referencia_r12(destino: Path, cenario: str) -> dict:
    """Mesmas entradas da R11: a comparação mede mudança do modelo, não da base."""
    from raiz import restauracao as R
    from raiz.executor.transferencia_privada import baixar_arquivo
    from raiz.executor.transferencia_privada import extrair as extrair_privado

    if R.cenario(cenario).get("rodada") != 12:
        raise ValueError("rodada alternativa exige cenário R12")
    nome = "retomada_PA_43285608189_entradas_42a37d06c245092d.tar.gz"
    digest = "42a37d06c245092dbab4f464ab9915a2553af485037a8ba82cce42e67ce4fbe0"
    destino.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        pacote = Path(td) / "entradas.tar.gz"
        baixar_arquivo(nome, pacote)
        if sha256(pacote) != digest:
            raise ValueError("entrada histórica divergente; não comparar bases diferentes")
        extrair_privado(pacote, destino)
    if {f.name for f in destino.iterdir()} != {*PACOTES, "estados.json", "snapshot.json"}:
        raise ValueError("conteúdo inesperado na entrada histórica")
    snapshot = _ler(destino / "snapshot.json")
    if snapshot["cenario"] != CENARIO:
        raise ValueError("referência não é a rodada 11")
    for arquivo, fonte in snapshot["fontes"].items():
        if sha256(destino / arquivo) != fonte["sha256"]:
            raise ValueError("fonte histórica alterada")
    snapshot["referencia_r11"] = {
        "arquivo": nome,
        "sha256": digest,
        "snapshot_sha256": sha256(destino / "snapshot.json"),
    }
    snapshot.update(cenario=cenario, acesso="privado")
    _json(destino / "snapshot.json", snapshot)
    return snapshot


def _hash_entradas(snapshot: dict, cod: int) -> str:
    # O recorte identifica a previsão dentro da fonte estadual congelada; arquivos derivados nunca entram no hash.
    entrada = {"municipio": cod, "fontes": {n: snapshot["fontes"][n]["sha256"] for n in PACOTES}}
    return hashlib.sha256(json.dumps(entrada, sort_keys=True).encode()).hexdigest()


def terra_dos_dados_publicados(pasta: Path, cod: int, im):
    """Preserva a classificação fundiária publicada e suas áreas; completa somente registros sem classificação."""
    import pandas as pd

    from raiz import terra as T
    from raiz.privacidade import remover_colunas_pessoais

    f = pasta / f"terra_{cod}.csv"
    anteriores = {}
    if f.exists():
        tabela, _ = remover_colunas_pessoais(pd.read_csv(f, low_memory=False, dtype={"cod_imovel": str}))
        anteriores = tabela.set_index("cod_imovel").to_dict("index")
    registros, reusadas = [], 0
    for li in im.to_dict("records"):
        cd = str(li["cod_imovel"])
        anterior = anteriores.get(cd, {})
        if anterior.get("caminho_terra") in T.CAMINHOS and anterior.get("risco_terra") in T.RISCOS:
            calc = anterior
            reusadas += 1
        else:
            calc = {**anterior, **T.caminho({**li, **anterior})}
        registros.append({"cod_imovel": cd, **calc})
    return pd.DataFrame(registros), reusadas


def calcular(entradas: Path, destino: Path, fatia: str) -> dict:
    """Calcula uma fatia sem baixar camadas geográficas; retoma município já concluído na mesma versão."""
    import pandas as pd

    from raiz import restauracao as R
    from raiz.restauracao_validacao import registrar_previsoes, validar_area

    snapshot = _ler(entradas / "snapshot.json")
    cenario = snapshot.get("cenario", CENARIO)
    R.cenario(cenario)
    plano = next(x for x in snapshot["plano"] if x["fatia"] == fatia)
    cods = set(plano["municipios"])
    destino.mkdir(parents=True, exist_ok=True)
    pasta = destino / "trabalho" / "PA"
    for nome in PACOTES:
        if sha256(entradas / nome) != snapshot["fontes"][nome]["sha256"]:
            raise ValueError(f"A entrada {nome} mudou depois do congelamento.")
        extrair(entradas / nome, pasta.parent, cods)
    resultado = destino / "resultado" / "PA"
    resultado.mkdir(parents=True, exist_ok=True)
    marcas = []
    for cod in sorted(cods):
        marca = resultado / f"rodada_{cod}.json"
        hash_entrada = _hash_entradas(snapshot, cod)
        modelo = R.versao()
        if marca.exists():
            anterior = _ler(marca)
            if (
                anterior["modelo_versao"] == modelo
                and anterior.get("cenario") == cenario
                and anterior["entradas_versao"] == hash_entrada
                and anterior.get("previsoes", {}).get("arquivo") in anterior["arquivos"]
                and all(
                    (resultado / nome).exists() and sha256(resultado / nome) == sha
                    for nome, sha in anterior["arquivos"].items()
                )
            ):
                marcas.append(anterior)
                continue
        print(f"Calculando PA/{cod}, fatia {fatia}", flush=True)
        # Consome o classificador existente com as sobreposições já publicadas. Não baixa camadas nem presume título.
        im = R.linhas_do_municipio(pasta, cod)
        validacoes = [
            {
                "cod_imovel": str(li["cod_imovel"]),
                "modelo_versao": modelo,
                "entradas_versao": hash_entrada,
                **validar_area(li),
            }
            for li in im.to_dict("records")
        ]
        validacao_nome = f"validacao_entradas_{cod}.jsonl"
        with (resultado / validacao_nome).open("w", encoding="utf-8") as f:
            for validacao in validacoes:
                f.write(json.dumps(validacao, ensure_ascii=False, allow_nan=False) + "\n")
        terra, reusadas = terra_dos_dados_publicados(pasta, cod, im)
        terra.to_csv(pasta / f"terra_{cod}.csv", index=False)
        df = R.calcular_municipio(pasta, cod, nome_cenario=cenario, fontes_geo=())
        if len(df) != len(im) or not df.cod_imovel.is_unique:
            raise ValueError(f"O cálculo perdeu ou duplicou imóveis em {cod}.")
        df["entradas_versao"] = hash_entrada
        for nome, tabela in ((f"desenvolvedor_{cod}.csv", df), (f"terra_{cod}.csv", terra)):
            tabela.to_csv(resultado / nome, index=False)
        registro = registrar_previsoes(resultado / "previsoes", df, modelo, hash_entrada)
        registro["arquivo"] = str(Path(registro["arquivo"]).relative_to(resultado))
        arquivos = {
            nome: sha256(resultado / nome)
            for nome in (f"desenvolvedor_{cod}.csv", f"terra_{cod}.csv", validacao_nome, registro["arquivo"])
        }
        metadados = {
            "cod_municipio": cod,
            "imoveis": len(df),
            "modelo_versao": modelo,
            "entradas_versao": hash_entrada,
            "cenario": cenario,
            "arquivos": arquivos,
            "previsoes": registro,
            "imoveis_com_pendencia_area": sum(bool(x["pendencias"]) for x in validacoes),
            "pendencias_area": dict(Counter(p for x in validacoes for p in x["pendencias"])),
            "terra_classificacoes_publicadas_preservadas": reusadas,
            "terra_classificacoes_por_colunas_motor": len(im) - reusadas,
            "dados_faltantes": {
                coluna: int(pd.to_numeric(im[coluna], errors="coerce").isna().sum()) if coluna in im else len(im)
                for coluna in ("pasto_ha", "pasto_ate1km_ha", "app_recompor_ha", "app_desmatada_ha")
            },
            "premissas_substitutas": dict(
                Counter(
                    nome for texto in df.restauracao_faltou.fillna("").astype(str) for nome in texto.split(",") if nome
                )
            ),
        }
        _json(marca, metadados)
        marcas.append(metadados)
    resumo = {
        "fatia": fatia,
        "municipios": len(marcas),
        "imoveis": sum(x["imoveis"] for x in marcas),
        "modelo_versao": R.versao(),
        "cenario": cenario,
    }
    _json(destino / f"fatia_{fatia}.json", resumo)
    with tarfile.open(destino / f"calculado_{fatia}.tar.gz", "w:gz") as tar:
        tar.add(resultado, arcname="PA")
    return resumo


def conferir_calculos(pasta: Path, cobertura: dict, modelo: str, cenario: str = CENARIO) -> list[dict]:
    import pandas as pd

    esperados = set(cobertura["com_imoveis"])
    presentes = {int(f.stem.rsplit("_", 1)[1]) for f in pasta.glob("desenvolvedor_*.csv")}
    if presentes != esperados:
        raise ValueError(f"Cálculo incompleto: faltam {sorted(esperados - presentes)}.")
    marcas = []
    for cod in sorted(esperados):
        m = _ler(pasta / f"rodada_{cod}.json")
        if m["modelo_versao"] != modelo or m["cenario"] != cenario:
            raise ValueError(f"Versão ou cenário divergente em {cod}.")
        previsoes = m.get("previsoes", {})
        if (
            previsoes.get("arquivo") not in m["arquivos"]
            or m["arquivos"][previsoes["arquivo"]] != previsoes.get("sha256")
            or previsoes.get("quantidade") != m["imoveis"]
        ):
            raise ValueError(f"Registro imutável de previsões ausente ou divergente em {cod}.")
        for nome, h in m["arquivos"].items():
            if not (pasta / nome).is_file() or sha256(pasta / nome) != h:
                raise ValueError(f"Arquivo alterado depois do cálculo: {nome}.")
        df = pd.read_csv(pasta / f"desenvolvedor_{cod}.csv", usecols=["cod_imovel", "restauracao_versao"])
        if len(df) != m["imoveis"] or not df.cod_imovel.is_unique or set(df.restauracao_versao) != {modelo}:
            raise ValueError(f"Contagem, identidade ou versão inválida em {cod}.")
        marcas.append(m)
    return marcas


def reunir(entradas: Path, calculados: Path, destino: Path) -> dict:
    from raiz import lote as L
    from raiz import lote_relatorio as LR
    from raiz import restauracao as R
    from raiz.restauracao_validacao import comparar_pastas, confrontar_referencia

    snapshot = _ler(entradas / "snapshot.json")
    cenario = snapshot.get("cenario", CENARIO)
    R.cenario(cenario)
    trabalho = destino / "trabalho"
    for nome in PACOTES:
        if sha256(entradas / nome) != snapshot["fontes"][nome]["sha256"]:
            raise ValueError(f"A entrada {nome} mudou depois do congelamento.")
        extrair(entradas / nome, trabalho)
    # Os pacotes calculados são nossos, com previsões em subpasta; filter=data impede caminhos/links externos.
    for pacote in sorted(calculados.glob("calculado_*.tar.gz")):
        with tarfile.open(pacote) as tar:
            tar.extractall(trabalho, filter="data")
    pasta = trabalho / "PA"
    cobertura = conferir_cobertura(pasta)
    marcas = conferir_calculos(pasta, cobertura, R.versao(), cenario)
    produto = destino / "produto"
    produto.mkdir(parents=True, exist_ok=True)
    _json(produto / "fontes.json", snapshot)
    _json(produto / "municipios.json", marcas)
    amostra = Path(__file__).resolve().parents[1] / "dados" / "amostra"
    comparacao = comparar_pastas(amostra, pasta, 1504950)
    comparacao["referencia_documentada"] = confrontar_referencia(R.linhas_do_municipio(pasta, 1504950), 1504950)
    _json(produto / "comparacao_real_1504950.json", comparacao)
    dados = L.ler_pasta(pasta, "PA")
    decisoes = dados.pop("decisoes_entrada", [])
    with (produto / "decisoes_entrada.jsonl").open("w", encoding="utf-8") as f:
        for decisao in decisoes:
            f.write(json.dumps(L.json_seguro(decisao), ensure_ascii=False) + "\n")
    del decisoes
    r, c = R.regra(), R.cenario(cenario)
    resumos = {}
    for nome in OPCOES:
        print(f"Montando a opção {nome}", flush=True)
        # Reexecução do retrato científico congelado. Novos lotes passam por L.montar com WFS atual.
        lote = L.montar(dados, opcao=nome, c=c, r=r, sensibilidade_ligada=False, conferir_car=False)
        lote["resumo"]["trilha_decisoes_entrada"] = "decisoes_entrada.jsonl, no pacote de previsões da rodada"
        LR.gravar_lote(lote, produto / nome, c=c, r=r)
        resumos[nome] = lote["resumo"]
        del lote
    _json(produto / "tres_lotes_PA.json", resumos)
    pesquisa, sensibilidade = None, None
    if c.get("rodada") == 12:
        from raiz import restauracao_pesquisa as P12
        from raiz import restauracao_sensibilidade as S12

        pesquisa = P12.gravar(produto / "pesquisa")
        print("Reavaliando a oferta para a sensibilidade dos três lotes", flush=True)
        sensibilidade = S12.executar(dados, produto / "sensibilidade")
    previsoes = produto / "previsoes"
    previsoes.mkdir(exist_ok=True)
    for padrao in ("desenvolvedor_*.csv", "terra_*.csv", "validacao_entradas_*.jsonl"):
        for f in pasta.glob(padrao):
            shutil.copy2(f, previsoes / f.name)
    if (pasta / "previsoes").exists():
        shutil.copytree(pasta / "previsoes", previsoes / "registros", dirs_exist_ok=True)
    manifesto = {
        "cenario": cenario,
        "uf": "PA",
        "municipios": cobertura["total"],
        "municipios_calculados": len(marcas),
        "municipios_vazios": cobertura["vazios"],
        "imoveis_calculados": sum(x["imoveis"] for x in marcas),
        "modelo_versao": R.versao(),
        "commit": os.environ.get("GITHUB_SHA"),
        "execucao": os.environ.get("GITHUB_RUN_ID"),
        "opcoes": list(OPCOES),
        "fontes": snapshot["fontes"],
        "resumos": resumos,
        "pesquisa_rodada12": pesquisa,
        "sensibilidade_rodada12": sensibilidade,
        "qualidade_dados": {
            "imoveis_com_pendencia_area": sum(m.get("imoveis_com_pendencia_area", 0) for m in marcas),
            "pendencias_area": dict(sum((Counter(m.get("pendencias_area", {})) for m in marcas), Counter())),
            "terra_classificacoes_publicadas_preservadas": sum(
                m.get("terra_classificacoes_publicadas_preservadas", 0) for m in marcas
            ),
            "terra_classificacoes_por_colunas_motor": sum(
                m.get("terra_classificacoes_por_colunas_motor", 0) for m in marcas
            ),
            "faltas_por_coluna": dict(sum((Counter(m.get("dados_faltantes", {})) for m in marcas), Counter())),
            "premissas_substitutas": dict(
                sum((Counter(m.get("premissas_substitutas", {})) for m in marcas), Counter())
            ),
            "municipios_sem_app_recompor": [
                m["cod_municipio"] for m in marcas if m.get("dados_faltantes", {}).get("app_recompor_ha", 0)
            ],
            "tratamento": "Sem app_recompor_ha usa app_desmatada_ha como desconto conservador. "
            "Sem pasto medido a área fica pendente, sem supor que toda área livre é pasto. "
            "Classificações fundiárias existentes foram preservadas com suas medidas; onde faltavam, "
            "a classificação usa apenas as colunas do motor publicadas e não comprova terra pronta. "
            "Camadas fundiárias e entradas geográficas remotas não foram baixadas nesta rodada; "
            "premissas substitutas são explícitas.",
        },
        "limite": "Estimativas de triagem: não constituem crédito emitido nem liberação de venda. "
        "As pendências jurídicas e de dados constam de cada opção.",
    }
    _json(produto / "manifesto.json", manifesto)
    return manifesto


def publicar(destino: Path) -> dict:
    """Assets por execução são imutáveis; o ponteiro mais recente só muda após todos os uploads."""
    arm = arquivo_privado()
    produto = destino / "produto"
    manifesto = _ler(produto / "manifesto.json")
    run_id = os.environ.get("GITHUB_RUN_ID")
    tentativa = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    if not run_id or not run_id.isdigit() or not tentativa.isdigit():
        raise ValueError("A publicação exige uma execução identificada do GitHub Actions.")
    from raiz import restauracao as R

    cenario = manifesto["cenario"]
    R.cenario(cenario)
    base = f"lote_PA_{cenario}_{run_id}_{tentativa}"
    arquivos = []
    for nome in OPCOES:
        arquivo = destino / f"{base}_{nome}.tar.gz"
        empacotar(produto / nome, arquivo, prefixo=nome)
        arquivos.append(arquivo)
    completo = destino / f"{base}_previsoes.tar.gz"
    empacotar(produto, completo, excluir=OPCOES)
    arquivos.append(completo)
    manifesto["arquivos"] = {
        f.name: {
            "sha256": sha256(f),
            "bytes": f.stat().st_size,
            "local": f"release-github://{arm.repo}/{arm.tag}/{f.name}",
            "acesso": "privado",
        }
        for f in arquivos
    }
    imutavel = destino / f"{base}.json"
    _json(imutavel, manifesto)
    for f in [*arquivos, imutavel]:
        enviar_arquivo(f.name, f, imutavel=True, arm=arm)
    atual = destino / f"lote_PA_{cenario}.json"
    _json(atual, manifesto)
    enviar_arquivo(atual.name, atual, arm=arm)
    return manifesto


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("etapa", choices=("preparar", "calcular", "reunir", "publicar"))
    parser.add_argument("--destino", type=Path, required=True)
    parser.add_argument("--entradas", type=Path)
    parser.add_argument("--calculados", type=Path)
    parser.add_argument("--fatia")
    parser.add_argument("--cenario", default=CENARIO)
    args = parser.parse_args()
    if args.etapa == "preparar":
        resultado = preparar(args.destino, cenario=args.cenario)
        print(json.dumps({"fatias": len(resultado["plano"]), "cobertura": resultado["cobertura"]}))
    elif args.etapa == "calcular":
        print(json.dumps(calcular(args.entradas, args.destino, args.fatia)))
    elif args.etapa == "reunir":
        resultado = reunir(args.entradas, args.calculados, args.destino)
        print(json.dumps({k: resultado[k] for k in ("municipios", "imoveis_calculados", "modelo_versao")}))
    else:
        resultado = publicar(args.destino)
        print(json.dumps({"arquivos": list(resultado["arquivos"])}))


if __name__ == "__main__":
    main()
