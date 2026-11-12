"""Leitura de edital (concessão florestal, chamada de restauração, PSA, crédito de carbono) pela API da Anthropic.

O modelo extrai prazos e requisitos e liga cada requisito que fala do imóvel a um critério conhecido (CAR ativo, sem
embargo, área mínima...). Quem avalia o critério é o código (checklist_edital.py), com os dados do motor. A leitura
fica no armazém com a versão do modelo e do prompt, como a da certidão.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from raiz.documentos import __version__
from raiz.documentos.armazem import Armazem, Leitura
from raiz.documentos.busca import http
from raiz.documentos.claude import LeitorClaude, falta_campo
from raiz.documentos.esquemas import enum as _enum
from raiz.documentos.esquemas import num as _num
from raiz.documentos.esquemas import obj as _obj
from raiz.documentos.esquemas import txt as _txt
from raiz.documentos.privacidade import limpar

VERSAO_BASE = "edital-2026a"

GRUPOS = [
    "habilitacao_juridica",
    "regularidade_fiscal",
    "qualificacao_tecnica",
    "qualificacao_economica",
    "imovel_e_area",
    "ambiental",
    "proposta_tecnica",
    "proposta_de_preco",
    "garantia",
    "outro",
]
CRITERIOS = [
    "nenhum",
    "car_ativo",
    "sem_embargo",
    "sem_desmatamento_apos_2008",
    "sem_desmatamento_apos_2020",
    "sem_alerta_desmatamento",
    "matricula_regular",
    "georreferenciamento_sigef",
    "fora_terra_indigena",
    "fora_unidade_conservacao",
    "area_minima_ha",
    "area_maxima_ha",
    "bioma",
    "uf_elegivel",
    "municipio_elegivel",
    "reserva_legal_regular",
    "posse_ou_propriedade",
    "sem_projeto_carbono_sobreposto",
]

REQUISITO = _obj(
    {
        "id": _txt("R1, R2...", nulo=False),
        "grupo": _enum(GRUPOS, "Grupo do requisito."),
        "descricao": _txt("O requisito em uma frase curta, sem nome de pessoa.", nulo=False),
        "documento": {"type": "boolean", "description": "true se é um documento a entregar."},
        "obrigatorio": {"type": "boolean", "description": "false se é só pontuação ou opcional."},
        "criterio": _enum(CRITERIOS, "Critério sobre o imóvel ou a área, quando o requisito é um deles; senão nenhum."),
        "valor_num": _num("Número do critério (ex.: área mínima em ha)."),
        "valor_texto": _txt("Texto do critério (ex.: bioma Amazônia; lista de municípios)."),
        "referencia": _txt("Onde está no edital: item, cláusula ou anexo e a página."),
    }
)
PRAZO = _obj(
    {
        "evento": _txt(
            "O que acontece (ex.: entrega das propostas, sessão pública, pedido de esclarecimento).", nulo=False
        ),
        "data": _txt("AAAA-MM-DD"),
        "hora": _txt("HH:MM, se houver."),
        "referencia": _txt("Item ou página."),
    }
)
ESQUEMA = _obj(
    {
        "e_edital": {"type": "boolean", "description": "false se o documento não é edital, chamada ou aviso."},
        "orgao": _txt("Órgão que publica."),
        "numero": _txt("Número do edital (ex.: Concorrência 01/2026)."),
        "modalidade": _txt("Concorrência, chamamento público, pregão, credenciamento..."),
        "objeto": _txt("Objeto em uma ou duas frases.", nulo=False),
        "uf": _txt("UF da área, se houver."),
        "municipios": {"type": "array", "items": {"type": "string"}},
        "area_total_ha": _num("Área total do objeto, em ha."),
        "data_publicacao": _txt("AAAA-MM-DD"),
        "prazos": {"type": "array", "items": PRAZO},
        "garantia": _txt("Garantia exigida, em texto curto."),
        "valor_estimado": _txt("Valor estimado ou de referência, em texto curto."),
        "criterios_julgamento": {"type": "array", "items": {"type": "string"}},
        "requisitos": {"type": "array", "items": REQUISITO},
        "observacoes": {"type": "array", "items": {"type": "string"}},
        "confianca": _enum(["alta", "media", "baixa"], "Quanto você confia nesta leitura."),
    }
)

SISTEMA = """Você lê editais públicos brasileiros (concessão florestal, chamada pública de restauração, pagamento por
serviço ambiental, crédito de carbono, credenciamento) e devolve o JSON pedido para a Raíz montar o checklist de quem
vai concorrer com um lote de imóveis rurais.

- Liste todos os prazos com data (AAAA-MM-DD) e o que acontece em cada um.
- Liste todos os requisitos de habilitação, de proposta e sobre a área ou os imóveis, cada um numa frase curta.
- Quando o requisito fala do imóvel ou da área, ligue a um critério: CAR ativo, sem embargo, sem desmatamento depois
  de 2008 ou de 2020, sem alerta, matrícula regular, georreferenciamento no SIGEF, fora de terra indígena, fora de
  unidade de conservação, área mínima ou máxima (valor_num em hectares), bioma, UF ou município elegível (valor_texto),
  reserva legal regular, posse ou propriedade comprovada, sem projeto de carbono sobreposto. Senão, critério nenhum.
- Diga onde cada requisito está (item e página).
- Não escreva nome de pessoa (servidor, pregoeiro, signatário), CPF, telefone nem e-mail pessoal.
- Se o documento não for edital, chamada ou aviso, diga e_edital=false.
"""
PEDIDO = "Leia este edital e devolva o JSON do esquema."
CHAVES_SEGURAS = {
    "id",
    "grupo",
    "criterio",
    "data",
    "hora",
    "orgao",
    "numero",
    "modalidade",
    "uf",
    "municipios",
    "data_publicacao",
    "confianca",
    "referencia",
    "valor_texto",
}


def versao_prompt() -> str:
    h = hashlib.sha256((SISTEMA + PEDIDO + json.dumps(ESQUEMA, sort_keys=True)).encode("utf-8")).hexdigest()
    return f"{VERSAO_BASE}+{h[:10]}"


def _baixar(fonte: str | Path) -> tuple[bytes, str, str]:
    """(conteúdo, tipo pdf|texto, chave)."""
    s = str(fonte)
    if s.startswith("http://") or s.startswith("https://"):
        import requests

        r = requests.get(s, headers={"User-Agent": http.AGENTE}, timeout=90)
        r.raise_for_status()
        if r.content[:5] == b"%PDF-" or "pdf" in r.headers.get("content-type", ""):
            return r.content, "pdf", s
        from bs4 import BeautifulSoup

        texto = BeautifulSoup(r.text, "html.parser").get_text("\n", strip=True)
        return texto.encode("utf-8"), "texto", s
    dados = Path(s).read_bytes()
    tipo = "pdf" if dados[:5] == b"%PDF-" else "texto"
    return dados, tipo, f"sha:{hashlib.sha256(dados).hexdigest()[:16]}"


def ler_edital(
    fonte: str | Path,
    leitor: LeitorClaude | None = None,
    armazem: Armazem | None = None,
    json_manual: dict | None = None,
) -> Leitura:
    conteudo, tipo, chave = _baixar(fonte)
    armazem = armazem or Armazem()
    base = dict(
        tipo="edital",
        chave=chave,
        arquivo_sha256=hashlib.sha256(conteudo).hexdigest(),
        prompt_versao=versao_prompt(),
        esquema_versao=versao_prompt().split("+")[1],
        leitor_versao=__version__,
    )
    if json_manual is not None:
        if erro := falta_campo(json_manual, ESQUEMA):
            raise ValueError(f"leitura manual fora do esquema: {erro}")
        dados, info = json_manual, dict(modelo_pedido="humano", modelo="humano")
    else:
        leitor = leitor or LeitorClaude()
        if tipo == "pdf":
            r = leitor.ler_pdf(conteudo, SISTEMA, PEDIDO, ESQUEMA)
        else:
            r = leitor.ler_texto(conteudo.decode("utf-8", errors="ignore"), SISTEMA, PEDIDO, ESQUEMA)
        info = dict(
            modelo_pedido=leitor.modelo,
            modelo=r.modelo,
            esforco=leitor.esforco,
            duracao_ms=r.duracao_ms,
            tokens_entrada=r.uso.entrada,
            tokens_saida=r.uso.saida,
            tokens_cache_leitura=r.uso.cache_leitura,
            tokens_cache_escrita=r.uso.cache_escrita,
            custo_usd=r.custo_usd,
        )
        if not r.ok:
            lt = Leitura(dados={}, erro=r.erro, **base, **info)
            armazem.gravar_leitura(lt)
            return lt
        dados = r.dados
    dados = limpar(dados, CHAVES_SEGURAS)
    lt = Leitura(
        dados=dados,
        confianca=dados.get("confianca"),
        situacao_documento="edital" if dados.get("e_edital", True) else "nao_e_edital",
        **base,
        **info,
    )
    armazem.gravar_leitura(lt)
    return lt
