"""Medidor de legibilidade dos textos que a Raíz manda (E9, passo 1).

A contagem de letras, palavras, sílabas e frases é a do ALT (Análise de Legibilidade Textual, legibilidade.com),
copiada do alt-python (MIT, Copyright (c) 2025 Marco Polo Moreno de Souza; ver NOTICE.md), sem o PyMuPDF e sem a
leitura de arquivos. A lógica das quatro contagens ficou igual à do original, inclusive nas esquisitices (a primeira
sequência de ditongo do texto sempre desconta uma sílaba; ":" e ";" fecham frase), para a nota bater com a do site.

Com a mesma contagem saem as três versões do Flesch para o português, todas guardadas:

  flesch_alt           226 − 1,04 × palavras/frase − 72 × sílabas/palavra             (ALT: código do alt-python)
  flesch_martins       248,835 − 1,015 × palavras/frase − 84,6 × sílabas/palavra      (Martins et al. 1996, NILC-USP)
  flesch_languagetool  206,84 − 1,02 × palavras/frase − 60 × sílabas/palavra          (regra do LanguageTool para o
                                                                                       português; reimplementada, o
                                                                                       código dele é LGPL)

e os índices do ALT: Flesch-Kincaid, Gunning Fog, ARI, Coleman-Liau, Gulpease e o resultado do ALT (média de
Flesch-Kincaid, Gunning Fog, ARI e Coleman-Liau: menos de 13 é legibilidade alta, de 13 a menos de 17 média, 17 ou
mais baixa). Flesch alto é fácil; os outros quatro são anos de estudo, e menor é mais fácil.

Antes de contar, o texto é preparado para ser lido como se fala (`preparar`): número, data, real, por cento e
unidade viram palavras ("R$ 1.200" vira "mil e duzentos reais"). Sem isso o ALT conta "1.200" como palavra sem
sílaba e o ponto do milhar como fim de frase. `medir(texto, preparar=False)` dá a contagem crua do ALT.

Palavra complexa (Gunning Fog): o ALT usa as 5.000 palavras mais comuns de uma lista da Linguateca, que não traz
licença clara, então não foi copiada. Com RAIZ_PALAVRAS_COMUNS apontando um arquivo (uma palavra por linha, da mais
comum para a menos comum), a regra é a do ALT; sem ele, é complexa a palavra com 4 sílabas ou mais. O critério usado
vai junto na medida (`complexas_criterio`). Nome próprio (maiúscula fora do começo da frase) e sigla nunca contam.

`VERSAO` muda quando a contagem, a preparação ou as fórmulas mudarem: toda nota é guardada com ela, para comparar
depois com o que o dono entendeu (o teach-back do aceite).
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

VERSAO = "legibilidade-1"

# --- contagem do ALT (alt-python, MIT) -------------------------------------------------------------------------------


def _e_letra(c: str) -> bool:
    return c.lower() != c.upper()


def contar_letras(texto: str) -> int:
    return sum(1 for c in texto if _e_letra(c))


def contar_palavras(texto: str) -> int:
    """Fecha palavra no espaço, na quebra de linha ou no fim do texto, se o caractere anterior não for espaço,
    quebra ou hífen."""
    palavras = 0
    for k, caractere in enumerate(texto):
        anterior1 = texto[k - 1] if k > 0 else ""
        if (caractere in (" ", "\n") or k == len(texto) - 1) and anterior1 not in (" ", "\n", "-"):
            palavras += 1
    return palavras


_VOGAL = ("a", "ã", "â", "á", "à", "e", "é", "ê", "i", "í", "o", "õ", "ô", "ó", "u", "ú")
_DITONGO = ("ãe", "ai", "ão", "au", "ei", "eu", "éu", "ia", "ie", "io", "iu", "õe", "oi", "ói", "ou", "ua", "ue", "uê",
            "ui")  # fmt: skip
_TRITONGO = ("uai", "uei", "uão", "uõe", "uiu", "uou")
_CONSOANTE = frozenset("bcdfghjklmnpqrstvwxyz")


def contar_silabas(texto: str) -> int:
    """Cada vogal é uma sílaba; ditongo e tritongo descontam. Mínimo de 1."""
    silabas = 0
    silaba_anterior = ""
    cont_silabas = -1
    for k, caractere in enumerate(texto):
        anterior1 = texto[k - 1] if k > 0 else ""
        anterior2 = texto[k - 2] if k > 1 else ""
        for v in _VOGAL:
            if caractere == v or caractere == v.upper():
                silabas += 1
        par = anterior1 + caractere
        for j, d in enumerate(_DITONGO):
            if (par == d or par == d.upper()) and (
                cont_silabas < 0
                or cont_silabas >= len(_DITONGO)
                or silaba_anterior != _DITONGO[cont_silabas]
                or anterior2.lower() in _CONSOANTE
            ):
                silabas -= 1
                cont_silabas = j
                silaba_anterior = _DITONGO[cont_silabas]
        trio = anterior2 + anterior1 + caractere
        for t in _TRITONGO:
            if trio == t:
                silabas -= 1
    return max(silabas, 1)


def contar_frases(texto: str, ponto_e_virgula: bool = True, dois_pontos: bool = True) -> int:
    """Fecha frase em . ! ? (e ; e : quando ligados, como no ALT) e no fim do texto; "..." conta uma vez."""
    fins = {".", "!", "?"} | ({";"} if ponto_e_virgula else set()) | ({":"} if dois_pontos else set())
    quebra = fins - {".", "!", "?"}
    sentencas = 0
    for k, caractere in enumerate(texto):
        anterior1 = texto[k - 1] if k > 0 else ""
        if caractere in fins or k == len(texto) - 1 or (caractere == "\n" and anterior1 in quebra):
            sentencas += 1
        if caractere == "." and anterior1 == ".":
            sentencas -= 1
    return max(sentencas, 1)


# --- palavras complexas ----------------------------------------------------------------------------------------------


@lru_cache(maxsize=4)
def _palavras_comuns(caminho: str, limite: int = 5000) -> frozenset[str]:
    with open(caminho, encoding="utf-8") as f:
        return frozenset(linha.strip() for _, linha in zip(range(limite), f, strict=False) if linha.strip())


def _lista_comuns() -> frozenset[str] | None:
    caminho = os.environ.get("RAIZ_PALAVRAS_COMUNS")
    if caminho and Path(caminho).is_file():
        return _palavras_comuns(caminho)
    return None


_PALAVRA = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")


def contar_complexas(texto: str, comuns: frozenset[str] | None = None) -> tuple[int, str]:
    """Palavras complexas e o critério usado ("lista" ou "silabas>=4")."""
    complexas = 0
    inicio_frase = True
    pos = 0
    for m in _PALAVRA.finditer(texto):
        entre = texto[pos : m.start()]
        if re.search(r"[.!?:;\n]", entre):
            inicio_frase = True
        pos = m.end()
        p = m.group()
        sigla = len(p) > 1 and p.isupper()
        nome_proprio = p[0].isupper() and not inicio_frase
        inicio_frase = False
        if sigla or nome_proprio:
            continue
        if comuns is not None:
            complexas += p.lower() not in comuns and p not in comuns
        else:
            complexas += contar_silabas(p.lower()) >= 4
    return complexas, ("lista" if comuns is not None else "silabas>=4")


# --- preparar o texto para ler como se fala --------------------------------------------------------------------------

_UNIDADES = ("zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "onze", "doze",
             "treze", "quatorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove")  # fmt: skip
_DEZENAS = ("", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa")
_CENTENAS = ("", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos",
             "oitocentos", "novecentos")  # fmt: skip
_ESCALAS = ((10**12, "trilhão", "trilhões"), (10**9, "bilhão", "bilhões"), (10**6, "milhão", "milhões"))
_MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
          "novembro", "dezembro")  # fmt: skip


def _ate_mil(n: int) -> str:
    if n == 100:
        return "cem"
    c, resto = divmod(n, 100)
    partes = [_CENTENAS[c]] if c else []
    if resto:
        if resto < 20:
            partes.append(_UNIDADES[resto])
        else:
            d, u = divmod(resto, 10)
            partes.append(_DEZENAS[d] + (f" e {_UNIDADES[u]}" if u else ""))
    return " e ".join(partes)


def extenso(n: int) -> str:
    """Inteiro por extenso, no português do Brasil: 1200 → "mil e duzentos"; 1250 → "mil duzentos e cinquenta";
    2026 → "dois mil e vinte e seis"; 1500000 → "um milhão e quinhentos mil"."""
    if n < 0:
        return "menos " + extenso(-n)
    if n < 20:
        return _UNIDADES[n]
    if n < 1000:
        return _ate_mil(n)
    grupos: list[tuple[int, str]] = []  # (grupo de três algarismos, texto)
    for escala, um, varios in _ESCALAS:
        q, n = divmod(n, escala)
        if q:
            grupos.append((q % 1000, f"{extenso(q)} {um if q == 1 else varios}"))
    q, n = divmod(n, 1000)
    if q:
        grupos.append((q, "mil" if q == 1 else f"{_ate_mil(q)} mil"))
    if n:
        grupos.append((n, _ate_mil(n)))
    if len(grupos) == 1:
        return grupos[0][1]
    ultimo, texto_ultimo = grupos[-1]
    # "e" antes do último grupo quando ele é menor que cem ou uma centena redonda: "mil e duzentos", "mil e cinco"
    junta = " e " if ultimo < 100 or ultimo % 100 == 0 else " "
    return " ".join(t for _, t in grupos[:-1]) + junta + texto_ultimo


def _numero_falado(inteiro: str, decimal: str | None) -> str:
    falado = extenso(int(inteiro.replace(".", "")))
    if not decimal:
        return falado
    if len(decimal) > 2 or decimal.startswith("0"):
        return falado + " vírgula " + " ".join(_UNIDADES[int(c)] for c in decimal)
    return falado + " vírgula " + extenso(int(decimal))


_UNIDADE_FALADA = {
    "ha": "hectares",
    "km²": "quilômetros quadrados",
    "km2": "quilômetros quadrados",
    "km": "quilômetros",
    "m": "metros",
    "kg": "quilos",
    "t": "toneladas",
    "mm": "milímetros",
}
_NUM = r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?"
_RE_DATA = re.compile(r"(?<![\w/-])(\d{1,2})/(\d{1,2})/(\d{4})(?![\w/-])")
_ESCALA_FALADA = r"(?:\s(mil|milhão|milhões|bilhão|bilhões))?(?![\w-])"
_RE_REAL = re.compile(r"R\$\s?" + _NUM + _ESCALA_FALADA)
_RE_DOLAR = re.compile(r"US\$\s?" + _NUM + _ESCALA_FALADA)
_RE_PORCENTO = re.compile(r"(?<![\w.,-])" + _NUM + r"\s?%")
_RE_UNIDADE = re.compile(
    r"(?<![\w.,-])"
    + _NUM
    + r"\s?("
    + "|".join(sorted(map(re.escape, _UNIDADE_FALADA), key=len, reverse=True))
    + r")(?![\w²])"
)
_RE_NUMERO = re.compile(r"(?<![\w.,/-])" + _NUM + r"(?![\w/-]|[.,]\d)")


_ABREVIACOES = {
    r"\bart\.": "artigo",
    r"\barts\.": "artigos",
    r"\bSr\.": "senhor",
    r"\bSra\.": "senhora",
    r"\bDr\.": "doutor",
    r"\bDra\.": "doutora",
    r"\bn\.?º": "número",
    r"\bp\. ?ex\.": "por exemplo",
}


def preparar(texto: str) -> str:
    """O texto como se lê em voz alta: abreviações, datas, reais, porcentagens, unidades e números por extenso."""

    def data(m: re.Match) -> str:
        d, mes, ano = int(m[1]), int(m[2]), int(m[3])
        if not 1 <= mes <= 12:
            return m[0]
        dia = "primeiro" if d == 1 else extenso(d)
        return f"{dia} de {_MESES[mes - 1]} de {extenso(ano)}"

    def dinheiro(singular: str, plural: str):
        def falar(m: re.Match) -> str:
            valor = int(m[1].replace(".", ""))
            if m[3]:
                return f"{_numero_falado(m[1], m[2])} {m[3]} de {plural}"
            if valor == 1 and not m[2]:
                return f"um {singular}"
            de = " de" if not m[2] and valor >= 10**6 and valor % 10**6 == 0 else ""
            return f"{_numero_falado(m[1], m[2])}{de} {plural}"

        return falar

    for abrev, por in _ABREVIACOES.items():
        texto = re.sub(abrev, por, texto)
    texto = _RE_DATA.sub(data, texto)
    texto = _RE_REAL.sub(dinheiro("real", "reais"), texto)
    texto = _RE_DOLAR.sub(dinheiro("dólar", "dólares"), texto)
    texto = _RE_PORCENTO.sub(lambda m: f"{_numero_falado(m[1], m[2])} por cento", texto)
    texto = _RE_UNIDADE.sub(lambda m: f"{_numero_falado(m[1], m[2])} {_UNIDADE_FALADA[m[3]]}", texto)
    texto = _RE_NUMERO.sub(lambda m: _numero_falado(m[1], m[2]), texto)
    return texto


# --- notas -----------------------------------------------------------------------------------------------------------


def faixa_martins(flesch: float) -> str:
    """Faixas de Martins et al. (1996) para o Flesch em português."""
    if flesch >= 75:
        return "muito fácil"
    if flesch >= 50:
        return "fácil"
    if flesch >= 25:
        return "difícil"
    return "muito difícil"


def nivel_languagetool(flesch: float) -> int:
    """Nível de 0 (mais difícil) a 6 (mais fácil), nos mesmos cortes da regra de legibilidade do LanguageTool."""
    return sum(flesch >= corte for corte in (30, 50, 60, 70, 80, 90))


def faixa_alt(resultado: float) -> str:
    """Faixa do resultado do ALT (anos de estudo)."""
    if resultado < 13:
        return "alta"
    if resultado < 17:
        return "média"
    return "baixa"


def medir(texto: str, preparar_texto: bool = True, comuns: frozenset[str] | None = None) -> dict:
    """Todas as contagens e notas de um texto, com a versão do medidor. Texto vazio devolve só as contagens zeradas."""
    base = preparar(texto) if preparar_texto else texto
    base = base.strip()
    if not base:
        return {"versao": VERSAO, "preparado": preparar_texto, "palavras": 0}
    if comuns is None:
        comuns = _lista_comuns()
    letras = contar_letras(base)
    palavras = max(contar_palavras(base), 1)
    silabas = contar_silabas(base)
    frases = contar_frases(base)
    complexas, criterio = contar_complexas(base, comuns)
    asl = palavras / frases
    asw = silabas / palavras
    fk = 0.36 * asl + 10.4 * asw - 18
    gf = 0.49 * asl + 19 * complexas / palavras
    ari = 4.6 * letras / palavras + 0.44 * asl - 20
    cli = 5.4 * letras / palavras - 21 * frases / palavras - 14
    resultado = (fk + gf + ari + cli) / 4
    flesch_alt = 226 - 1.04 * asl - 72 * asw
    flesch_martins = 248.835 - 1.015 * asl - 84.6 * asw
    flesch_lt = 206.84 - 1.02 * asl - 60 * asw

    def r(x: float) -> float:
        return round(x, 1)

    return {
        "versao": VERSAO,
        "preparado": preparar_texto,
        "letras": letras,
        "silabas": silabas,
        "palavras": palavras,
        "frases": frases,
        "complexas": complexas,
        "complexas_criterio": criterio,
        "palavras_por_frase": r(asl),
        "silabas_por_palavra": round(asw, 2),
        "flesch_alt": r(flesch_alt),
        "flesch_martins": r(flesch_martins),
        "flesch_languagetool": r(flesch_lt),
        "faixa_martins": faixa_martins(flesch_martins),
        "nivel_languagetool": nivel_languagetool(flesch_lt),
        "flesch_kincaid": r(fk),
        "gunning_fog": r(gf),
        "ari": r(ari),
        "coleman_liau": r(cli),
        "gulpease": r(89 + (300 * frases - 10 * letras) / palavras),
        "resultado_alt": r(resultado),
        "faixa_alt": faixa_alt(resultado),
    }


def resumo(m: dict) -> str:
    """Uma linha para quem aprova a mensagem: "Flesch 72 (fácil), 9 palavras por frase"."""
    if not m.get("palavras"):
        return "texto vazio"
    return (
        f"Flesch {m['flesch_martins']:.0f} ({m['faixa_martins']}), {m['palavras_por_frase']:.0f} palavras por frase, "
        f"resultado do ALT {m['resultado_alt']:.0f} (legibilidade {m['faixa_alt']})"
    )
