"""O que o modelo devolve ao ler uma certidão de matrícula (JSON Schema da saída estruturada) e o prompt de sistema.

O esquema não tem campo de nome de pessoa: cada pessoa vira um rótulo (P1, P2...). Só órgão público e instituição
financeira podem vir com o nome da instituição. A versão do prompt é o hash do texto do prompt e do esquema: mudou uma
vírgula, muda a versão gravada em cada leitura.
"""

from __future__ import annotations

import hashlib
import json

from raiz.documentos.esquemas import enum as _enum
from raiz.documentos.esquemas import num as _num
from raiz.documentos.esquemas import obj as _obj
from raiz.documentos.esquemas import txt as _txt

VERSAO_BASE = "certidao-2026a"

UNIDADES_AREA = [
    "ha",
    "m2",
    "alqueire_paulista",
    "alqueire_mineiro",
    "alqueire_goiano",
    "alqueire_baiano",
    "alqueire_do_norte",
    "tarefa",
    "braca_quadrada",
    "outro",
]

TRANSMISSAO = [
    "compra_e_venda",
    "doacao",
    "heranca_partilha",
    "usucapiao",
    "desapropriacao",
    "arrematacao_adjudicacao",
    "permuta",
    "integralizacao_capital",
    "dacao_em_pagamento",
    "titulacao_publica",
    "legitimacao_fundiaria",
    "divisao_extincao_condominio",
    "transmissao_outra",
]
ONUS = [
    "hipoteca",
    "alienacao_fiduciaria",
    "cedula_credito",
    "penhora",
    "arresto",
    "sequestro",
    "indisponibilidade",
    "usufruto",
    "servidao",
    "clausula_restritiva",
    "acao_judicial",
    "arrendamento_ou_contrato",
    "onus_outro",
]
CADASTRO = [
    "georreferenciamento",
    "ccir_itr_car",
    "reserva_legal",
    "retificacao_area",
    "desmembramento",
    "unificacao",
    "benfeitoria",
    "qualificacao_parte",
    "cadastro_outro",
]
ENCERRAMENTO = ["encerramento_matricula", "cancelamento_matricula", "bloqueio_matricula", "desbloqueio_matricula"]
NATUREZAS = ["abertura", *TRANSMISSAO, *ONUS, *CADASTRO, "cancelamento", *ENCERRAMENTO, "outro"]

TIPOS_PARTE = [
    "pessoa_fisica",
    "pessoa_juridica",
    "orgao_publico",
    "instituicao_financeira",
    "espolio",
    "desconhecido",
]


PARTE = _obj(
    {
        "rotulo": _txt("P1, P2, P3... A mesma pessoa tem sempre o mesmo rótulo no documento inteiro.", nulo=False),
        "tipo": _enum(TIPOS_PARTE, "Tipo da parte. Espólio usa o rótulo da pessoa falecida."),
        "documento": _txt(
            "CPF ou CNPJ JÁ MASCARADO (***.456.789-** ou **.345.678/****-**). Nunca os dígitos inteiros. null se a "
            "certidão não traz."
        ),
        "nome_instituicao": _txt(
            "Só para órgão público ou instituição financeira (ex.: INCRA, Estado do Pará, Banco da Amazônia). null "
            "para pessoa física, espólio e empresa privada."
        ),
    }
)

ATO = _obj(
    {
        "numero": _txt('Como está na certidão: "R-3", "AV-12", ou "abertura" para o texto de abertura.', nulo=False),
        "tipo": _enum(["abertura", "registro", "averbacao"], "Abertura da matrícula, registro (R) ou averbação (AV)."),
        "data": _txt("Data do ato no formato AAAA-MM-DD; null se não der para ler."),
        "natureza": _enum(NATUREZAS, "O que o ato faz. Cancelamento de ônus ou de outro ato = cancelamento."),
        "afeta": _enum(
            ["propriedade", "onus", "cadastro", "encerramento", "outro"],
            "propriedade = muda quem é dono; onus = cria ônus ou restrição; cadastro = dado do imóvel; "
            "encerramento = encerra, cancela, bloqueia ou desbloqueia a matrícula.",
        ),
        "transmitentes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Rótulos de quem transmite (ou do devedor, no ônus).",
        },
        "adquirentes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Rótulos de quem recebe (ou do credor, no ônus).",
        },
        "fracao_pct": _num("Porcentagem do imóvel transmitida; null quando é o imóvel todo."),
        "cancela": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Números dos atos que este ato "
            'cancela ou dá baixa (ex.: ["R-4"]). Vazio se não cancela nada.',
        },
        "area_valor": _num("Área do imóvel depois deste ato, quando o ato muda a área (retificação, desmembramento)."),
        "area_unidade": _enum(UNIDADES_AREA, "Unidade de area_valor.", nulo=True),
        "matricula_destino": _txt("Número da matrícula para onde o imóvel foi transportado, no encerramento."),
        "pagina": {"type": ["integer", "null"], "description": "Página do PDF (a primeira é 1) onde o ato está."},
        "resumo": _txt(
            "Uma frase curta do que o ato faz, sem nome de pessoa (use os rótulos P1, P2), sem CPF e sem endereço.",
            nulo=False,
        ),
    }
)

ESQUEMA = _obj(
    {
        "documento": _obj(
            {
                "tipo_documento": _enum(
                    [
                        "certidao_inteiro_teor",
                        "certidao_onus_reais",
                        "certidao_matricula_resumida",
                        "outro_documento_do_registro",
                        "nao_e_certidao",
                    ],
                    "Que documento é.",
                ),
                "data_emissao": _txt("Data em que a certidão foi emitida, AAAA-MM-DD."),
                "legivel": {"type": "boolean", "description": "false se partes que importam não dão para ler."},
                "paginas_ilegiveis": {"type": "array", "items": {"type": "integer"}},
                "observacoes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Problemas de leitura ou do documento, sem nome de pessoa.",
                },
            }
        ),
        "cartorio": _obj(
            {
                "nome": _txt("Nome do cartório (ex.: Cartório do Registro de Imóveis da Comarca de Tucumã)."),
                "cns": _txt("Código Nacional de Serventia (CNS) do cartório, como impresso (ex.: 06.842-9)."),
                "comarca": _txt("Comarca."),
                "uf": _txt("UF do cartório, duas letras."),
            }
        ),
        "matricula": _obj(
            {
                "numero": _txt("Número da matrícula, como impresso.", nulo=False),
                "livro": _txt("Livro (normalmente 2)."),
                "cnm": _txt("Código Nacional de Matrícula, quando a certidão traz."),
                "data_abertura": _txt("Data de abertura da matrícula, AAAA-MM-DD."),
                "origem": _enum(
                    [
                        "titulo_publico",
                        "transcricao_anterior",
                        "matricula_anterior",
                        "usucapiao",
                        "desconhecida",
                    ],
                    "De onde a matrícula veio: título do INCRA, do Estado ou da União; transcrição ou matrícula "
                    "anterior; usucapião.",
                ),
                "origem_referencia": _txt("Número da transcrição, matrícula ou título de origem."),
                "situacao_declarada": _enum(
                    ["ativa", "encerrada", "cancelada", "bloqueada", "transportada", "nao_informada"],
                    "Situação que a própria certidão declara.",
                ),
                "matricula_destino": _txt("Se foi transportada ou encerrada: o número da nova matrícula."),
            }
        ),
        "imovel": _obj(
            {
                "municipio": _txt("Município do imóvel segundo a certidão."),
                "uf": _txt("UF do imóvel, duas letras."),
                "area_valor": _num("Área ATUAL do imóvel (depois de retificações e desmembramentos)."),
                "area_unidade": _enum(UNIDADES_AREA, "Unidade de area_valor.", nulo=True),
                "area_original_valor": _num("Área na abertura da matrícula."),
                "area_original_unidade": _enum(UNIDADES_AREA, "Unidade de area_original_valor.", nulo=True),
                "codigo_incra_sncr": _txt("Código do imóvel no SNCR/CCIR."),
                "car": _txt("Código do CAR, se aparece."),
                "cib_nirf": _txt("CIB ou NIRF da Receita Federal, se aparece."),
                "georreferenciado": {
                    "type": ["boolean", "null"],
                    "description": "true se há averbação de georreferenciamento ou certificação do SIGEF/INCRA.",
                },
                "certificacao_sigef": _txt("Número da certificação do INCRA/SIGEF, se aparece."),
            }
        ),
        "partes": {"type": "array", "items": PARTE},
        "atos": {"type": "array", "items": ATO, "description": "Todos os atos, na ordem da certidão."},
        "proprietarios_atuais": {
            "type": "array",
            "items": _obj({"rotulo": _txt("Rótulo da parte.", nulo=False), "fracao_pct": _num("Fração em %.")}),
            "description": "Quem é dono hoje, segundo o último estado da matrícula.",
        },
        "confianca": _enum(["alta", "media", "baixa"], "Quanto você confia nesta leitura como um todo."),
    }
)

SISTEMA = """Você lê certidões de matrícula de imóvel rural emitidas por cartórios de Registro de Imóveis do Brasil e
devolve os fatos no JSON pedido. Quem usa o resultado é a Raíz, que confere se a matrícula do imóvel bate com o que o
SIGEF/INCRA e o CAR dizem.

Privacidade (obrigatório, sem exceção):
- Nunca escreva nome de pessoa física, de espólio ou de empresa privada em nenhum campo. Cada pessoa vira um rótulo:
  P1, P2, P3... na ordem em que aparece. A mesma pessoa (mesmo nome ou mesmo CPF) recebe sempre o mesmo rótulo, em
  todos os atos. Cônjuges são pessoas diferentes, com rótulos diferentes. Espólio usa o rótulo da pessoa falecida.
- CPF e CNPJ só mascarados: ***.456.789-** e **.345.678/****-** (mantenha só os dígitos do meio).
- Não escreva RG, endereço, estado civil, profissão, filiação nem nome de cônjuge.
- Órgão público (INCRA, União, Estado, Município) e banco ou cooperativa de crédito podem ter o nome da instituição em
  nome_instituicao. Empresa privada não.

Leitura:
- Liste todos os atos na ordem: o texto de abertura (numero "abertura"), cada registro (R-1, R-2...) e cada
  averbação (AV-1, AV-2...). Não pule ato.
- Em cada ato, diga quem transmite e quem recebe pelos rótulos. No ônus, transmitente é o devedor e adquirente é o
  credor.
- Quando um ato cancela ou dá baixa em outro (quitação de hipoteca, levantamento de penhora, cancelamento de ato),
  ponha o número do ato cancelado em "cancela".
- Encerramento, cancelamento, bloqueio ou transporte da matrícula para outra é natureza de encerramento; diga a
  matrícula de destino quando houver.
- Área: copie o número e a unidade como estão (não converta). Área atual é a última depois de retificação ou
  desmembramento.
- Datas em AAAA-MM-DD. Página: número da página do PDF onde o ato está.
- Se uma parte não dá para ler, não invente: use null, marque legivel=false quando for o caso e explique em
  observacoes. Se o documento não for certidão de registro de imóveis, diga tipo_documento="nao_e_certidao".
- O resumo de cada ato é uma frase curta, sem nomes, por exemplo: "P1 vende o imóvel todo a P2" ou "hipoteca
  cedular em favor do Banco da Amazônia, devedor P2".
"""

PEDIDO = "Leia esta certidão de matrícula e devolva o JSON do esquema."


def versao_prompt() -> str:
    h = hashlib.sha256((SISTEMA + PEDIDO + json.dumps(ESQUEMA, sort_keys=True)).encode("utf-8")).hexdigest()
    return f"{VERSAO_BASE}+{h[:10]}"


def versao_esquema() -> str:
    return hashlib.sha256(json.dumps(ESQUEMA, sort_keys=True).encode("utf-8")).hexdigest()[:10]


# Campos de texto que são lugar, instituição ou enumeração: passam só pela máscara de CPF/CNPJ, não pela de nomes
CHAVES_SEGURAS = {
    "numero",
    "tipo",
    "data",
    "natureza",
    "afeta",
    "area_unidade",
    "area_original_unidade",
    "matricula_destino",
    "tipo_documento",
    "data_emissao",
    "nome",
    "cns",
    "comarca",
    "uf",
    "livro",
    "cnm",
    "data_abertura",
    "origem",
    "origem_referencia",
    "situacao_declarada",
    "municipio",
    "codigo_incra_sncr",
    "car",
    "cib_nirf",
    "certificacao_sigef",
    "rotulo",
    "documento",
    "nome_instituicao",
    "confianca",
    "transmitentes",
    "adquirentes",
    "cancela",
}
