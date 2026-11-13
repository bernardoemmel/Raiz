"""Complementa lotes publicados sem alterar suas previsões ou executar o otimizador.

Entrada, relatórios e manifesto derivado ficam no arquivo privado autenticado.
Cada complemento conserva o hash do manifesto original e a versão do cálculo.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import tarfile
from pathlib import Path

import pandas as pd

from raiz.executor.transferencia_privada import arquivo_privado, empacotar, enviar_arquivo

OPCOES = ("barata", "segura", "compacta")


def _sha(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def _json(caminho: Path, dado: dict) -> None:
    caminho.write_text(json.dumps(dado, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n")


def _baixar(arm, nome: str, sha: str, tamanho: int | None = None) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", nome) or not re.fullmatch(r"[a-f0-9]{64}", sha):
        raise ValueError("Nome ou SHA256 inválido para o arquivo privado.")
    arm._exigir_privado()
    dados = arm._baixar_asset(nome, fresco=True)
    if dados is None or _sha(dados) != sha or (tamanho is not None and len(dados) != tamanho):
        raise ValueError("Arquivo privado ausente ou divergente do manifesto.")
    return dados


def referencias(manifesto: dict) -> dict:
    """Aceita o manifesto histórico da retomada e o formato privado estadual atual."""
    arquivos, saida = manifesto["arquivos"], {}
    for opcao in OPCOES:
        candidatos = []
        for chave, ref in arquivos.items():
            nome = ref.get("nome", chave)
            if chave == opcao or re.search(rf"_{opcao}(?:_[a-f0-9]{{16}})?\.tar\.gz$", nome):
                candidatos.append({**ref, "nome": nome})
        if len(candidatos) != 1:
            raise ValueError("O manifesto precisa de exatamente um pacote por opção.")
        saida[opcao] = candidatos[0]
    return saida


def ler_lote(dados: bytes, opcao: str, uf: str) -> tuple[pd.DataFrame, dict]:
    """Lê somente dois membros exatos, sem extrair caminhos ou seguir links do pacote."""
    if opcao not in OPCOES or not re.fullmatch(r"[A-Z]{2}", uf):
        raise ValueError("Opção ou UF inválida.")
    nomes = {f"{opcao}/lote_{uf}.csv", f"{opcao}/lote_{uf}.json"}
    with tarfile.open(fileobj=io.BytesIO(dados), mode="r:gz") as tar:
        encontrados = [m for m in tar.getmembers() if m.name in nomes]
        if len(encontrados) != 2 or {m.name for m in encontrados} != nomes or not all(m.isfile() for m in encontrados):
            raise ValueError("Pacote sem resumo/CSV único e regular da opção.")
        resumo = json.load(tar.extractfile(f"{opcao}/lote_{uf}.json"))
        tabela = pd.read_csv(
            tar.extractfile(f"{opcao}/lote_{uf}.csv"), dtype={"cod_imovel": "string"}, low_memory=False
        )
    return tabela, resumo


def gerar(arm, nome: str, sha: str, destino: Path) -> dict:
    from raiz.restauracao_desbloqueio import gravar, relatorio

    original = _baixar(arm, nome, sha)
    manifesto = json.loads(original)
    refs = referencias(manifesto)
    destino.mkdir(parents=True, exist_ok=True)
    produto = destino / "produto"
    if produto.exists() and any(produto.iterdir()):
        raise ValueError("Use uma pasta de produto vazia para não misturar complementos de rodadas diferentes.")
    produto.mkdir(exist_ok=True)
    resultados = {}
    for opcao, ref in refs.items():
        tabela, resumo = ler_lote(_baixar(arm, ref["nome"], ref["sha256"], ref["bytes"]), opcao, manifesto["uf"])
        if (
            resumo != manifesto["resumos"][opcao]
            or resumo["versao_premissas"] != manifesto["modelo_versao"]
            or resumo["cenario"] != manifesto["cenario"]
            or resumo["opcao"] != opcao
        ):
            raise ValueError("Resumo do pacote diverge do manifesto original.")
        resultado = relatorio(tabela, resumo)
        gravar(resultado, produto / opcao)
        resultados[opcao] = resultado
    derivado = {
        "tipo": "desbloqueio_lote",
        "origem": {
            "nome": nome,
            "sha256": sha,
            "pacotes": refs,
            "execucao": manifesto.get("execucao"),
            "commit": manifesto.get("commit"),
            "retomada": manifesto.get("retomada"),
        },
        "modelo_versao": manifesto["modelo_versao"],
        "cenario": manifesto["cenario"],
        "uf": manifesto["uf"],
        "execucao": os.environ.get("GITHUB_RUN_ID"),
        "commit": os.environ.get("GITHUB_SHA"),
        "calculo_original_preservado": True,
        "resultados": resultados,
    }
    _json(produto / "manifesto_complemento.json", derivado)
    return derivado


def publicar(arm, destino: Path, manifesto: dict) -> dict:
    pacote = destino / "desbloqueio.tar.gz"
    empacotar(destino / "produto", pacote)
    sha = _sha(pacote.read_bytes())
    base = f"desbloqueio_lote_{manifesto['uf']}_{manifesto['origem']['sha256'][:16]}_{sha[:16]}"
    ref = {"nome": base + ".tar.gz", "sha256": sha, "bytes": pacote.stat().st_size, "acesso": "privado"}
    enviar_arquivo(ref["nome"], pacote, imutavel=True, arm=arm)
    _baixar(arm, ref["nome"], sha, ref["bytes"])
    resultado = {**manifesto, "arquivo": ref}
    arquivo = destino / "manifesto_publicado.json"
    _json(arquivo, resultado)
    nome = base + ".json"
    enviar_arquivo(nome, arquivo, imutavel=True, arm=arm)
    sha_manifesto = _sha(arquivo.read_bytes())
    _baixar(arm, nome, sha_manifesto)
    return {"manifesto": nome, "sha256": sha_manifesto, "arquivo": ref}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifesto", required=True)
    p.add_argument("--sha256", required=True)
    p.add_argument("--destino", type=Path, required=True)
    args = p.parse_args()
    arm = arquivo_privado()
    resultado = gerar(arm, args.manifesto, args.sha256, args.destino)
    print(json.dumps(publicar(arm, args.destino, resultado), ensure_ascii=False))


if __name__ == "__main__":
    main()
