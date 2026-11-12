"""Impede que dependência ausente transforme testes do CI em sucesso silencioso.

Aceita um JUnit da suíte completa ou os relatórios dos jobs que a dividem.
Pular o teste estadual sempre falha; múltiplos arquivos ou
RAIZ_TESTE_PA_OBRIGATORIO=1 também exigem sua presença exatamente uma vez.
"""

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

TESTE_ESTADUAL = ("testes.test_lote", "test_lote_do_para_inteiro_fecha_ou_diz_o_que_falta")
FALHA_ESPERADA = ("testes.test_restauracao", "test_plantio_da_7_a_9_pct_no_central_r11")


def conferir(*arquivos: Path, pa_obrigatorio: bool | None = None) -> int:
    if pa_obrigatorio is None:
        pa_obrigatorio = os.environ.get("RAIZ_TESTE_PA_OBRIGATORIO") == "1"
    pa_obrigatorio = pa_obrigatorio or len(arquivos) > 1
    casos = []
    try:
        if not arquivos:
            raise ValueError
        for arquivo in arquivos:
            raiz = ET.parse(arquivo).getroot()
            novos = raiz.findall(".//testcase")
            if raiz.tag not in {"testsuite", "testsuites"} or not novos:
                raise ValueError
            if any(not caso.get("classname") or not caso.get("name") for caso in novos):
                raise ValueError
            casos.extend(novos)
    except (OSError, ET.ParseError, ValueError):
        print("FALHA: resultado de testes ausente ou inválido.")
        return 1
    problemas = []
    if pa_obrigatorio:
        quantidade_pa = sum((caso.get("classname"), caso.get("name")) == TESTE_ESTADUAL for caso in casos)
        if quantidade_pa != 1:
            problemas.append("o teste estadual do Pará deve aparecer exatamente uma vez")
    encontrados = set()
    for caso in casos:
        chave = (caso.get("classname"), caso.get("name"))
        if chave in encontrados:
            problemas.append(f"teste duplicado: {chave[0]}::{chave[1]}")
        encontrados.add(chave)
        for pulado in caso.findall("skipped"):
            if (
                chave == FALHA_ESPERADA
                and pulado.get("type") == "pytest.xfail"
                and "[NOTRUN]" not in pulado.get("message", "")
            ):
                print("PENDENTE: divergência conhecida da TIR; teste executado, ver docs/restauracao-rodada11.md")
            else:
                problemas.append(f"teste pulado: {chave[0]}::{chave[1]}")
        if caso.find("failure") is not None or caso.find("error") is not None:
            problemas.append(f"teste falhou: {chave[0]}::{chave[1]}")
    for problema in problemas:
        print(f"FALHA: {problema}")
    return int(bool(problemas))


if __name__ == "__main__":
    sys.exit(conferir(*(Path(arquivo) for arquivo in sys.argv[1:])))
