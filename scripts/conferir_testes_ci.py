"""Impede que dependência ausente transforme testes do CI em sucesso silencioso.

O teste do snapshot privado completo do Pará já foi integrado e executado.
Pular esse teste sempre falha; RAIZ_TESTE_PA_OBRIGATORIO=1 também exige sua presença.
"""

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

TESTE_ESTADUAL = ("testes.test_lote", "test_lote_do_para_inteiro_fecha_ou_diz_o_que_falta")
FALHA_ESPERADA = ("testes.test_restauracao", "test_plantio_da_7_a_9_pct_no_central_r11")


def conferir(arquivo: Path, *, pa_obrigatorio: bool | None = None) -> int:
    if pa_obrigatorio is None:
        pa_obrigatorio = os.environ.get("RAIZ_TESTE_PA_OBRIGATORIO") == "1"
    try:
        casos = ET.parse(arquivo).getroot().findall(".//testcase")
    except (OSError, ET.ParseError):
        print("FALHA: resultado de testes ausente ou inválido.")
        return 1
    problemas = []
    if not casos:
        problemas.append("nenhum teste foi registrado")
    if pa_obrigatorio:
        quantidade_pa = sum((caso.get("classname"), caso.get("name")) == TESTE_ESTADUAL for caso in casos)
        if quantidade_pa != 1:
            problemas.append("o teste estadual do Pará deve aparecer exatamente uma vez")
    for caso in casos:
        chave = (caso.get("classname"), caso.get("name"))
        pulado = caso.find("skipped")
        if pulado is not None:
            if chave == FALHA_ESPERADA and pulado.get("type") == "pytest.xfail":
                print("PENDENTE: divergência conhecida da TIR; teste executado, ver docs/restauracao-rodada11.md")
            else:
                problemas.append(f"teste pulado: {chave[0]}::{chave[1]}")
        if caso.find("failure") is not None or caso.find("error") is not None:
            problemas.append(f"teste falhou: {chave[0]}::{chave[1]}")
    for problema in problemas:
        print(f"FALHA: {problema}")
    return int(bool(problemas))


if __name__ == "__main__":
    sys.exit(conferir(Path(sys.argv[1])))
