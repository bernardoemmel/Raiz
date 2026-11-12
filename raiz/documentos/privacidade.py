"""Privacidade dos documentos: CPF e CNPJ sempre mascarados, nome nunca gravado.

Três trancas, nesta ordem:
1. O modelo é instruído a nunca escrever nome de pessoa: cada pessoa vira um rótulo (P1, P2...) e o esquema da resposta
   não tem campo de nome (só órgão público e banco podem ter o nome da instituição).
2. mascarar(): todo CPF e CNPJ de qualquer texto vira ***.456.789-** e **.345.678/****-**. Usa a guarda do pacote
   (raiz/privacidade.py) quando ela existe; senão, a cópia fiel abaixo, com as mesmas regras do front
   (front/compartilhado/privacidade.ts).
3. tirar_nomes(): nos textos livres (resumo de ato, observação), troca por [nome] toda sequência de duas ou mais
   palavras com inicial maiúscula que não são vocabulário de registro de imóveis, lugar ou instituição. Erra para o
   lado de apagar: é mais barato perder uma palavra de um resumo do que gravar um nome.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Iterable

try:  # a guarda única do pacote, quando o back-end (raiz/privacidade.py) está presente
    from raiz.privacidade import cnpj_valido, cpf_valido, mascarar  # type: ignore  # noqa: F401
except ImportError:  # cópia fiel das mesmas regras

    def _so_digitos(s: str) -> str:
        return re.sub(r"\D", "", s)

    def cpf_valido(cpf: str) -> bool:
        d = _so_digitos(cpf)
        if len(d) != 11 or d == d[0] * 11:
            return False
        for n in (9, 10):
            soma = sum(int(d[i]) * (n + 1 - i) for i in range(n))
            if (soma * 10 % 11) % 10 != int(d[n]):
                return False
        return True

    def cnpj_valido(cnpj: str) -> bool:
        s = re.sub(r"[^0-9A-Z]", "", cnpj.upper())
        if len(s) != 14 or not s[12:].isdigit() or s == s[0] * 14:
            return False
        for n, pesos in ((12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]), (13, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])):
            r = sum((ord(s[i]) - 48) * pesos[i] for i in range(n)) % 11
            if (0 if r < 2 else 11 - r) != int(s[n]):
                return False
        return True

    _ANTES = r"(?<![\w./-])"
    _DEPOIS = r"(?![\w]|\.\d|[/-]\w)"
    _CPF_FMT = re.compile(_ANTES + r"\d{3}\.\d{3}\.\d{3}-\d{2}" + _DEPOIS)
    _CNPJ_FMT = re.compile(_ANTES + r"[0-9A-Z]{2}\.[0-9A-Z]{3}\.[0-9A-Z]{3}/[0-9A-Z]{4}-\d{2}" + _DEPOIS)
    _CPF_NU = re.compile(_ANTES + r"\d{11}" + _DEPOIS)
    _CNPJ_NU = re.compile(_ANTES + r"[0-9A-Z]{12}\d{2}" + _DEPOIS)

    def _mascara_cpf(cpf: str) -> str:
        d = _so_digitos(cpf)
        return f"***.{d[3:6]}.{d[6:9]}-**"

    def _mascara_cnpj(cnpj: str) -> str:
        s = re.sub(r"[^0-9A-Z]", "", cnpj.upper())
        return f"**.{s[2:5]}.{s[5:8]}/****-**"

    def mascarar(texto: str) -> str:
        if not texto:
            return texto
        texto = _CNPJ_FMT.sub(lambda m: _mascara_cnpj(m.group(0)), texto)
        texto = _CPF_FMT.sub(lambda m: _mascara_cpf(m.group(0)), texto)
        texto = _CNPJ_NU.sub(lambda m: _mascara_cnpj(m.group(0)) if cnpj_valido(m.group(0)) else m.group(0), texto)
        texto = _CPF_NU.sub(lambda m: _mascara_cpf(m.group(0)) if cpf_valido(m.group(0)) else m.group(0), texto)
        return texto


# --- documento de parte (CPF/CNPJ que o modelo devolve) -----------------------------------------------------------


def mascarar_documento(doc: str | None) -> str | None:
    """Campo de documento de uma parte: devolve só a forma mascarada, ou None. Nunca devolve os dígitos inteiros,
    nem quando os dígitos verificadores não batem (documento lido errado ainda é documento de alguém)."""
    if not doc:
        return None
    s = str(doc).strip()
    if "*" in s:  # já veio mascarado: confere que não sobrou documento inteiro dentro
        return mascarar(s)
    d = re.sub(r"\D", "", s)
    if len(d) == 11:
        return f"***.{d[3:6]}.{d[6:9]}-**"
    alnum = re.sub(r"[^0-9A-Z]", "", s.upper())
    if len(alnum) == 14:
        return f"**.{alnum[2:5]}.{alnum[5:8]}/****-**"
    return "[documento]"


# --- nomes nos textos livres ---------------------------------------------------------------------------------------

# Vocabulário que aparece com inicial maiúscula em certidão e edital e não é nome de pessoa. Comparado sem acento e
# em minúsculas. Nome de lugar composto (município, rio) entra pelo parâmetro permitir.
VOCABULARIO = set(
    """
    ab abertura acao acoes adjudicacao administracao agencia agraria agricultura agro agropecuaria alienacao alqueire
    alqueires amazonia ambiental ambiente anexo anm apa app area areas arrematacao arresto artigo assentamento
    associacao autarquia av averbacao avenida aviso banco bancos bndes bioma brasil br cadastro caixa cancelamento
    capital car carbono cartorio cedula central certidao certificacao certificado chamada chamamento cia cidade
    civil codigo comarca comercio compra companhia compensacao concessao concorrencia condominio conselho consulta
    contrato cooperativa corregedoria cpr credito creditos cri dacao decreto delegacao demarcacao departamento
    desapropriacao desmembramento diario direito diretoria distrito doacao dominio economica edital eletronico
    empresa encerramento energia escritura especial espolio estadual estado estrada execucao extrato fazenda federal
    fiduciaria financiamento financeiro fiscal floresta florestal florestas fndf fno fundiario fundacao fundo geral
    georreferenciamento gleba glebas governo grupo habilitacao heranca hipoteca hipotecaria ibama icmbio ideflor
    imovel imoveis incra indisponibilidade industria instituto integralizacao interesse inventario itr juizo justica
    lavratura lei leilao legal legitimacao licenca licitacao livro lote lotes ltda manejo mata matricula me meio
    ministerio mineracao municipal municipio mutuo nacional natureza norte notas notarial numero oeste oficial
    oficio onus orgao padrao para parcela parque particular partilha penhora permanente permuta pessoa plano portaria
    posse pregao preservacao presidencia produto programa projeto pronaf pronamp propriedade proposta provimento
    publica publico qualificacao reabertura receita recuperacao regional registro registros regularizacao republica
    reserva restauracao resultado retificacao rio rodovia rural santa santo sao secretaria secao sequestro servico
    servidao sfb sicoob sicredi sigef sistema sociedade sul superintendencia tabeliao tabelionato tecnica terra
    terras territorial titulacao titular titulo transcricao transmissao tribunal uniao unidade usucapiao usufruto
    vara venda vila
    ac al am ap ba ce df es go ma mg ms mt pa pb pe pi pr rj rn ro rr rs sc se sp to
    car app rl uf ri cns cnm cpf cnpj rg ccir nirf cib itr sncr cnfp cnuc dou doe eireli epp nº n
    janeiro fevereiro marco abril maio junho julho agosto setembro outubro novembro dezembro
    homologacao ratificacao dispensa inexigibilidade termo aditivo convenio extrato portaria resolucao instrucao
    normativa deliberacao despacho julgamento comissao desenvolvimento agrario familiar pecuaria abastecimento
    educacao saude cultura ciencia tecnologia inovacao fazenda universidade faculdade escola hospital embrapa camara
    assembleia gabinete coordenacao gerencia divisao setor sede mudanca clima sustentabilidade biodiversidade
    conservacao cerrado caatinga pantanal pampa atlantica xingu tapajos araguaia tocantins amazonas para mato grosso
    rondonia acre roraima amapa maranhao piaui goias minas gerais bahia paulo janeiro parana catarina
    contratante contratada contratado objeto valor vigencia fundamento modalidade processo edicao secao
    """.split()
)
CONECTORES = {"de", "da", "do", "das", "dos", "e", "d'", "del", "di"}
_PALAVRA = re.compile(r"\b[^\W\d_]+(?:['’][^\W\d_]+)?\b")


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


def _parece_nome(token: str) -> bool:
    if not token[0].isupper():
        return False
    base = _sem_acento(token)
    if base in VOCABULARIO:
        return False
    if len(token) == 1:  # inicial solta, S/A
        return False
    return True


def tirar_nomes(texto: str | None, permitir: Iterable[str] = ()) -> str | None:
    """Troca por [nome] cada sequência de 2 ou mais palavras com cara de nome próprio (conectores de, da, do, e no
    meio). Frases em `permitir` (ex.: nome do município) são preservadas."""
    if not texto:
        return texto
    protegidos: list[tuple[int, int]] = []
    for frase in permitir:
        if frase:
            for m in re.finditer(re.escape(frase), texto, flags=re.IGNORECASE):
                protegidos.append((m.start(), m.end()))
    tokens = [(m.start(), m.end(), m.group(0)) for m in _PALAVRA.finditer(texto)]
    trechos: list[tuple[int, int]] = []
    i = 0
    while i < len(tokens):
        if not _parece_nome(tokens[i][2]):
            i += 1
            continue
        inicio, fim, nomes, j = tokens[i][0], tokens[i][1], 1, i + 1
        while j < len(tokens):
            entre = texto[fim : tokens[j][0]]
            if entre.strip():  # vírgula, ponto, número: a sequência acaba
                break
            t = tokens[j][2]
            if _parece_nome(t):
                fim, nomes, j = tokens[j][1], nomes + 1, j + 1
                continue
            if _sem_acento(t) in CONECTORES and j + 1 < len(tokens) and _parece_nome(tokens[j + 1][2]):
                if texto[tokens[j][1] : tokens[j + 1][0]].strip():
                    break
                fim, nomes, j = tokens[j + 1][1], nomes + 1, j + 2
                continue
            break
        if nomes >= 2 and not any(a <= inicio and fim <= b for a, b in protegidos):
            trechos.append((inicio, fim))
        i = j
    for a, b in reversed(trechos):
        texto = texto[:a] + "[nome]" + texto[b:]
    return texto


def limpar(obj, chaves_seguras: Iterable[str] = (), permitir: Iterable[str] = ()):
    """Percorre dict/list: mascara CPF/CNPJ em todo texto e tira nomes dos textos livres. Valores das chaves seguras
    (lugar, instituição, enumeração) só passam pela máscara de documento."""
    seguras = set(chaves_seguras)
    permitir = list(permitir)

    def _vai(v, chave: str | None):
        if isinstance(v, str):
            v = mascarar(v)
            return v if chave in seguras else tirar_nomes(v, permitir)
        if isinstance(v, dict):
            return {k: _vai(x, k) for k, x in v.items()}
        if isinstance(v, list):
            return [_vai(x, chave) for x in v]
        return v

    return _vai(obj, None)


# --- log ---------------------------------------------------------------------------------------------------------


class FormatadorSeguro(logging.Formatter):
    """Formata e mascara o resultado final (mensagem, argumentos e traceback)."""

    def format(self, record: logging.LogRecord) -> str:
        return mascarar(super().format(record))


def configurar_log(nivel: int = logging.INFO) -> None:
    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    if not raiz.handlers:
        raiz.addHandler(logging.StreamHandler())
    for h in raiz.handlers:
        h.setFormatter(FormatadorSeguro("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    for barulhento in ("httpx", "httpcore", "urllib3", "anthropic"):
        logging.getLogger(barulhento).setLevel(logging.WARNING)
