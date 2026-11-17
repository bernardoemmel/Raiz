"""Junta os JUnit das partes paralelas de `testes_python` num só `resultado-pytest.xml`.

Recusa (saída 1) quando falta parte, quando uma parte aparece duas vezes, quando as partes discordam do
tamanho da suíte ou quando a soma dos testes executados não é a suíte inteira. Assim, dividir a suíte não
abre espaço para teste esquecido; falhas e testes pulados continuam sendo julgados em `checagens`.

Uso: python3 scripts/juntar_partes_pytest.py --partes 4 --saida resultado-pytest.xml parte1.xml parte2.xml ...
"""

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _propriedades(suite: ET.Element) -> dict[str, str]:
    return {p.get("name"): p.get("value") for p in suite.findall("./properties/property")}


def juntar(arquivos: list[Path], partes: int, saida: Path) -> int:
    suites, vistas, tamanhos, executados = [], set(), set(), 0
    try:
        for arquivo in arquivos:
            raiz = ET.parse(arquivo).getroot()
            achadas = [raiz] if raiz.tag == "testsuite" else raiz.findall("testsuite")
            if raiz.tag not in {"testsuite", "testsuites"} or len(achadas) != 1:
                raise ValueError(f"{arquivo}: JUnit sem exatamente uma suíte")
            suite = achadas[0]
            props = _propriedades(suite)
            parte = props.get("raiz_parte", "")
            if parte in vistas or parte.split("/")[-1] != str(partes):
                raise ValueError(f"{arquivo}: parte {parte or 'ausente'} repetida ou de outra divisão")
            vistas.add(parte)
            tamanhos.add(props.get("raiz_testes_na_suite"))
            executados += len(suite.findall(".//testcase"))
            suites.append(suite)
    except (OSError, ET.ParseError, ValueError) as erro:
        print(f"FALHA: {erro}")
        return 1
    esperadas = {f"{k}/{partes}" for k in range(1, partes + 1)}
    if vistas != esperadas:
        print(f"FALHA: partes recebidas {sorted(vistas)}; esperadas {sorted(esperadas)}")
        return 1
    if len(tamanhos) != 1 or not next(iter(tamanhos)) or not next(iter(tamanhos)).isdigit():
        print(f"FALHA: as partes discordam do tamanho da suíte: {sorted(map(str, tamanhos))}")
        return 1
    tamanho = int(next(iter(tamanhos)))
    if executados != tamanho:
        print(f"FALHA: as partes executaram {executados} testes; a suíte tem {tamanho}")
        return 1
    junto = ET.Element("testsuites")
    junto.extend(suites)
    ET.ElementTree(junto).write(saida, encoding="utf-8", xml_declaration=True)
    print(f"OK: {partes} partes, {executados} testes juntados em {saida}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--partes", type=int, required=True)
    args.add_argument("--saida", type=Path, required=True)
    args.add_argument("arquivos", type=Path, nargs="+")
    opcoes = args.parse_args(argv)
    return juntar(opcoes.arquivos, opcoes.partes, opcoes.saida)


if __name__ == "__main__":
    sys.exit(main())
