"""Publica uma pasta de saídas ou pacotes legados pelo armazém privado e sua projeção aberta.

Nenhum pacote fornecido pelo operador é enviado diretamente ao Release aberto.
"""

from __future__ import annotations

import json
import re
import sys
import tarfile
from pathlib import Path

from raiz.executor.armazem import ArmazemRelease, do_config


def publicar_pasta(pasta: Path, ufs: list[str] | None = None) -> dict:
    arm = do_config()
    if not isinstance(arm, ArmazemRelease):
        raise ValueError("publicação dupla exige armazém Release configurado")
    arm.verificar_publicacao()
    ufs = ufs or sorted(p.name for p in pasta.iterdir() if p.is_dir() and re.fullmatch(r"[A-Z]{2}", p.name))
    for uf in ufs:
        if not re.fullmatch(r"[A-Z]{2}", uf):
            raise ValueError("UF inválida")
        arquivos = [f for f in (pasta / uf).iterdir() if f.is_file() and f.suffix in (".csv", ".parquet", ".pmtiles")]
        if not any(re.fullmatch(r"imoveis_\d{7}\.csv", f.name) for f in arquivos):
            raise ValueError(f"{uf}: faltam os dados completos; projeção pública não substitui o arquivo privado")
        for arquivo in arquivos:
            arm.por(f"saida/{uf}/{arquivo.name}", arquivo)
    return arm.publicar()


def publicar_pacotes(pasta: Path) -> dict:
    arm = do_config()
    if not isinstance(arm, ArmazemRelease):
        raise ValueError("publicação dupla exige armazém Release configurado")
    arm.verificar_publicacao()
    origem = pasta / "privado" if (pasta / "privado").is_dir() else pasta
    ufs = set()
    for pacote in sorted(origem.glob("*.tar.gz")):
        m = re.fullmatch(r"raiz_(?:geo_|camadas_)?([A-Z]{2})\.tar\.gz", pacote.name)
        if not m:
            raise ValueError(f"pacote desconhecido: {pacote.name}")
        uf = m.group(1)
        ufs.add(uf)
        with tarfile.open(pacote, "r:gz") as tar:
            vistos = set()
            for membro in tar:
                partes = membro.name.split("/")
                if not membro.isfile() or len(partes) != 2 or partes[0] != uf or membro.name in vistos:
                    raise ValueError(f"membro inválido: {membro.name}")
                vistos.add(membro.name)
                nome = partes[1]
                if nome == "_versoes.json":
                    continue  # o armazém gera novas marcas; nunca publica esse índice na parte aberta
                if nome.startswith("imoveis_basicos_"):
                    raise ValueError("projeção básica não substitui os dados completos no arquivo privado")
                if Path(nome).suffix not in (".csv", ".parquet", ".pmtiles"):
                    raise ValueError(f"arquivo inesperado: {nome}")
                arm.por_bytes(f"saida/{uf}/{nome}", tar.extractfile(membro).read())
    if not ufs:
        raise ValueError("nenhum pacote completo encontrado")
    for uf in ufs:
        if not any(re.fullmatch(rf"saida/{uf}/imoveis_\d{{7}}\.csv", k) for k in arm.local.listar(f"saida/{uf}/")):
            raise ValueError(f"{uf}: pacote sem dados completos do imóvel")
    return arm.publicar()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("uso: python -m raiz.executor.publicar_entrada <pasta-dos-pacotes>")
    print(json.dumps(publicar_pacotes(Path(sys.argv[1])), ensure_ascii=False))
