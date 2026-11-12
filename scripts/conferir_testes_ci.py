"""Impede que dependência ausente transforme testes do CI em sucesso silencioso.

A única pendência herdada é o conjunto real do Pará, documentado na passagem.
Retirar essa exceção quando Dados publicar as 144 tabelas desenvolvedor versionadas.
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

PENDENTE = ("testes.test_lote", "test_lote_do_para_inteiro_fecha_ou_diz_o_que_falta")


def conferir(arquivo: Path) -> int:
    casos = ET.parse(arquivo).getroot().findall(".//testcase")
    problemas = []
    if not casos:
        problemas.append("nenhum teste foi registrado")
    for caso in casos:
        chave = (caso.get("classname"), caso.get("name"))
        if caso.find("skipped") is not None:
            if chave == PENDENTE:
                print("PENDENTE: conjunto real do Pará; veja docs/passagem/qualidade-e-seguranca.md")
            else:
                problemas.append(f"teste pulado: {chave[0]}::{chave[1]}")
        if caso.find("failure") is not None or caso.find("error") is not None:
            problemas.append(f"teste falhou: {chave[0]}::{chave[1]}")
    for problema in problemas:
        print(f"FALHA: {problema}")
    return int(bool(problemas))


if __name__ == "__main__":
    sys.exit(conferir(Path(sys.argv[1])))
