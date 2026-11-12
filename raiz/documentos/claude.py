"""Leitura de documento pela API da Anthropic, com saída estruturada: o modelo devolve sempre o JSON do esquema.

- Modelo padrão claude-opus-5-5 com esforço high (ler a cadeia de uma matrícula é trabalho de atenção); troque com
  RAIZ_MODELO_DOCUMENTO e RAIZ_ESFORCO_DOCUMENTO. O modelo que respondeu de fato fica gravado em cada leitura.
- PDF vai inteiro como bloco de documento (o modelo lê texto e imagem, inclusive certidão escaneada). Acima de 30 MB
  vai pela Files API e o arquivo é apagado logo depois da leitura.
- Reserva do lado do servidor ligada nos modelos que aceitam (fallbacks="default"): se o classificador de segurança
  recusar, a própria API refaz o pedido num modelo de reserva, e o nome dele volta na resposta.
- Pedido em streaming (resposta longa não estoura o tempo do HTTP) e cache automático do prompt de sistema.
- Nada do documento vai para log: só o tamanho, as páginas, os tokens e o erro já mascarado.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass, field

from raiz.documentos import config
from raiz.documentos.privacidade import mascarar

log = logging.getLogger(__name__)

BETA_RESERVA = "server-side-fallback-2026-07-01"
COM_RESERVA = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-2", "claude-fable-5-1"}
LIMITE_BASE64 = 30 * 1024 * 1024  # o pedido inteiro pode ter até 32 MB

# US$ por milhão de tokens (entrada, saída, leitura de cache). Escrita de cache = 1,25 x entrada. Conferido em 11/2026.
PRECOS = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-opus-5": (5.00, 25.00, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10),
    "claude-sonnet-5": (2.00, 10.00, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-fable-5-2": (8.00, 40.00, 0.20),
    "claude-opus-4-8": (5.00, 25.00, 0.50),
}


@dataclass
class Uso:
    entrada: int = 0
    saida: int = 0
    cache_leitura: int = 0
    cache_escrita: int = 0


@dataclass
class Resultado:
    dados: dict | None
    modelo: str
    uso: Uso = field(default_factory=Uso)
    custo_usd: float | None = None
    duracao_ms: int = 0
    erro: str | None = None
    recusou: bool = False

    @property
    def ok(self) -> bool:
        return self.dados is not None and self.erro is None and not self.recusou


def custo(uso: Uso, modelo: str) -> float | None:
    p = PRECOS.get(modelo)
    if p is None:
        return None
    ent, sai, cache = p
    return round(
        (uso.entrada * ent + uso.saida * sai + uso.cache_leitura * cache + uso.cache_escrita * ent * 1.25) / 1e6, 6
    )


def _cliente_padrao():
    import anthropic

    chave = config.chave_anthropic()
    # sem chave, o SDK procura sozinho (ANTHROPIC_AUTH_TOKEN, perfil do `ant auth login`...)
    return anthropic.Anthropic(api_key=chave, max_retries=4) if chave else anthropic.Anthropic(max_retries=4)


class LeitorClaude:
    provedor = "anthropic"

    def __init__(
        self,
        modelo: str | None = None,
        esforco: str | None = None,
        cliente=None,
        reserva: bool = True,
        max_tokens: int = 64000,
    ):
        self.modelo = modelo or config.modelo_documento()
        self.esforco = esforco or config.esforco_documento()
        self._cliente = cliente
        self.reserva = reserva and self.modelo in COM_RESERVA
        self.max_tokens = max_tokens

    @property
    def cliente(self):
        if self._cliente is None:
            self._cliente = _cliente_padrao()
        return self._cliente

    # --- entradas -------------------------------------------------------------------------------------------------

    def ler_pdf(self, pdf: bytes, sistema: str, pedido: str, esquema: dict) -> Resultado:
        arquivo_id = None
        if len(pdf) > LIMITE_BASE64:
            try:
                enviado = self.cliente.files.upload(file=("documento.pdf", pdf, "application/pdf"))
                arquivo_id = enviado.id
            except Exception as ex:  # noqa: BLE001 - qualquer falha de envio vira erro da leitura
                return Resultado(None, self.modelo, erro=f"envio do PDF grande falhou: {mascarar(str(ex))[:200]}")
            fonte = {"type": "file", "file_id": arquivo_id}
        else:
            fonte = {"type": "base64", "media_type": "application/pdf", "data": base64.standard_b64encode(pdf).decode()}
        try:
            return self.ler(sistema, [{"type": "document", "source": fonte}, {"type": "text", "text": pedido}], esquema)
        finally:
            if arquivo_id:
                try:
                    self.cliente.files.delete(arquivo_id)
                except Exception:  # noqa: BLE001
                    log.warning("não consegui apagar o PDF enviado à Files API (%s)", arquivo_id)

    def ler_texto(self, texto: str, sistema: str, pedido: str, esquema: dict) -> Resultado:
        conteudo = [{"type": "text", "text": f"<documento>\n{texto}\n</documento>"}, {"type": "text", "text": pedido}]
        return self.ler(sistema, conteudo, esquema)

    # --- chamada --------------------------------------------------------------------------------------------------

    def _parametros(self, sistema: str, conteudo: list[dict], esquema: dict) -> dict:
        return dict(
            model=self.modelo,
            max_tokens=self.max_tokens,
            system=sistema,
            messages=[{"role": "user", "content": conteudo}],
            output_config={"format": {"type": "json_schema", "schema": esquema}, "effort": self.esforco},
            cache_control={"type": "ephemeral"},
        )

    def ler(self, sistema: str, conteudo: list[dict], esquema: dict) -> Resultado:
        import anthropic

        t0 = time.perf_counter()
        params = self._parametros(sistema, conteudo, esquema)
        try:
            if self.reserva:
                fluxo = self.cliente.beta.messages.stream(**params, betas=[BETA_RESERVA], fallbacks="default")
            else:
                fluxo = self.cliente.messages.stream(**params)
            with fluxo as s:
                r = s.get_final_message()
        except anthropic.BadRequestError as ex:
            return self._erro(f"pedido recusado pela API (400): {mascarar(str(ex))[:300]}", t0)
        except anthropic.AuthenticationError:
            return self._erro("credencial da Anthropic inválida: confira ANTHROPIC_API_KEY", t0)
        except anthropic.PermissionDeniedError:
            return self._erro("a chave da Anthropic não tem permissão para este modelo", t0)
        except anthropic.NotFoundError:
            return self._erro(f"modelo não encontrado: {self.modelo}", t0)
        except anthropic.RateLimitError as ex:
            return self._erro(f"limite de uso da API: {mascarar(str(ex))[:200]}", t0)
        except anthropic.APIStatusError as ex:
            return self._erro(f"API {ex.status_code}: {mascarar(str(ex))[:200]}", t0)
        except anthropic.APIConnectionError as ex:
            return self._erro(f"sem conexão com a API: {mascarar(str(ex))[:200]}", t0)
        except TypeError as ex:  # o SDK levanta TypeError quando não acha credencial nenhuma
            if "auth" not in str(ex).lower() and "api_key" not in str(ex).lower():
                raise
            return self._erro("sem credencial da Anthropic: defina ANTHROPIC_API_KEY no .env", t0)
        return self._resposta(r, t0)

    def _erro(self, msg: str, t0: float) -> Resultado:
        log.warning("leitura falhou: %s", msg)
        return Resultado(None, self.modelo, erro=msg, duracao_ms=int((time.perf_counter() - t0) * 1000))

    def _resposta(self, r, t0: float) -> Resultado:
        u = r.usage
        uso = Uso(
            entrada=getattr(u, "input_tokens", 0) or 0,
            saida=getattr(u, "output_tokens", 0) or 0,
            cache_leitura=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_escrita=getattr(u, "cache_creation_input_tokens", 0) or 0,
        )
        modelo = getattr(r, "model", None) or self.modelo
        base = dict(
            modelo=modelo, uso=uso, custo_usd=custo(uso, modelo), duracao_ms=int((time.perf_counter() - t0) * 1000)
        )
        log.info(
            "leitura: modelo=%s entrada=%d saida=%d cache=%d ms=%d",
            modelo,
            uso.entrada,
            uso.saida,
            uso.cache_leitura,
            base["duracao_ms"],
        )
        if r.stop_reason == "refusal":
            det = getattr(r, "stop_details", None)
            cat = getattr(det, "category", None) if det else None
            return Resultado(None, recusou=True, erro=f"recusa do modelo ({cat or 'sem categoria'})", **base)
        if r.stop_reason == "max_tokens":
            return Resultado(
                None, erro="resposta cortada (max_tokens): documento longo demais para uma leitura", **base
            )
        texto = next((b.text for b in r.content if getattr(b, "type", None) == "text"), None)
        if not texto:
            return Resultado(None, erro="resposta sem texto", **base)
        try:
            dados = json.loads(texto)
        except json.JSONDecodeError:
            return Resultado(None, erro="resposta fora do formato JSON", **base)
        if not isinstance(dados, dict):
            return Resultado(None, erro="resposta não é objeto JSON", **base)
        return Resultado(dados, **base)


def falta_campo(dados: dict, esquema: dict, caminho: str = "") -> str | None:
    """Conferência mínima do JSON contra o esquema (objeto, campos obrigatórios, enum, tipos de topo). A saída
    estruturada já garante o formato; isto pega leitura manual (JSON feito por gente) e mudança de esquema."""
    tipos = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}
    t = esquema.get("type")
    ts = t if isinstance(t, list) else [t]
    if dados is None:
        return None if "null" in ts else f"{caminho or 'raiz'} vazio"
    if "object" in ts and isinstance(dados, dict):
        for k in esquema.get("required", []):
            if k not in dados:
                return f"falta {caminho}{k}"
        for k, sub in esquema.get("properties", {}).items():
            if k in dados and (erro := falta_campo(dados[k], sub, f"{caminho}{k}.")):
                return erro
        return None
    if "array" in ts and isinstance(dados, list):
        for i, x in enumerate(dados):
            if erro := falta_campo(x, esquema.get("items", {}), f"{caminho}{i}."):
                return erro
        return None
    if "enum" in esquema and dados not in esquema["enum"]:
        return f"{caminho.rstrip('.')} fora da lista: {dados!r}"
    ok = [tipos[x] for x in ts if x in tipos]
    if ok and not isinstance(dados, tuple(ok)) or (isinstance(dados, bool) and "boolean" not in ts and ok):
        return f"{caminho.rstrip('.')} não é {'/'.join(x for x in ts if x)}"
    return None
