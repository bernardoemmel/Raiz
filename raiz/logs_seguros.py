"""Presidio local antes de qualquer saída de log ou persistência de diagnóstico.

O modelo português é instalado pelo uv.lock; não baixa modelos em produção. Falha do
analisador suprime o texto inteiro, nunca libera o original. CPF/CNPJ mantêm a máscara
do contrato; nomes, contato e credenciais reconhecidos são substituídos por marcadores.
"""

from __future__ import annotations

import re
import threading
from functools import lru_cache

_trava = threading.RLock()
_estado = threading.local()
_SUPRIMIDO = "[log suprimido: sanitização indisponível]"
_SEGREDO = re.compile(
    r"(?i)(\b(?:authorization|token|access_token|api_key|password|senha|secret|webhookSecret)\b"
    r"[\"']?\s*[=:]\s*[\"']?)(?:Bearer\s+)?[^\s\"'&,;\}\]]+"
)


@lru_cache(maxsize=1)
def _ferramentas():
    import spacy
    from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    from presidio_analyzer.predefined_recognizers import EmailRecognizer, PhoneRecognizer, SpacyRecognizer
    from presidio_anonymizer import AnonymizerEngine

    if not spacy.util.is_package("pt_core_news_sm"):
        raise RuntimeError("modelo português ausente")
    nlp = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "pt", "model_name": "pt_core_news_sm"}],
        }
    ).create_engine()
    registro = RecognizerRegistry(supported_languages=["pt"])
    registro.add_recognizer(SpacyRecognizer(supported_language="pt", supported_entities=["PERSON"]))
    registro.add_recognizer(EmailRecognizer(supported_language="pt"))
    registro.add_recognizer(PhoneRecognizer(supported_language="pt", supported_regions=["BR"]))
    registro.add_recognizer(
        PatternRecognizer(
            supported_entity="EMAIL_ADDRESS",
            supported_language="pt",
            patterns=[Pattern("email, inclusive domínio interno", r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}", 0.9)],
        )
    )
    # Cobertura determinística de campos rotulados, além de nomes livres encontrados pelo modelo.
    registro.add_recognizer(
        PatternRecognizer(
            supported_entity="PERSON",
            supported_language="pt",
            patterns=[
                Pattern(
                    "nome rotulado",
                    r"(?i)\b(?:nome|propriet[aá]rio|titular|dono)\s*[=:]\s*[\"']?[^\n,;\"'}]+",
                    0.9,
                )
            ],
        )
    )
    return AnalyzerEngine(nlp_engine=nlp, registry=registro, supported_languages=["pt"]), AnonymizerEngine()


def sanitizar_log(texto: str) -> str:
    """Limpa o texto final, incluindo argumentos e traceback; não registra falhas com conteúdo sensível."""
    if not texto:
        return texto
    if getattr(_estado, "ativo", False):
        return _SUPRIMIDO
    _estado.ativo = True
    try:
        from raiz.privacidade import mascarar

        texto = _SEGREDO.sub(r"\1[SEGREDO]", mascarar(texto))
        with _trava:
            analisador, anonimizador = _ferramentas()
            entidades = analisador.analyze(
                text=texto, language="pt", entities=["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"]
            )
            return anonimizador.anonymize(text=texto, analyzer_results=entidades).text
    except Exception:
        return _SUPRIMIDO
    finally:
        _estado.ativo = False


def sanitizar_estrutura(dado):
    """Metadados de diagnóstico: retira chaves pessoais e sanitiza todo texto restante."""
    from raiz.privacidade import colunas_pessoais

    if isinstance(dado, str):
        return sanitizar_log(dado)
    if isinstance(dado, dict):
        pessoais = set(colunas_pessoais(str(k) for k in dado))
        return {
            k: sanitizar_estrutura(v)
            for k, v in dado.items()
            if str(k) not in pessoais and not re.search(r"(?i)token|secret|senha|password|authorization", str(k))
        }
    if isinstance(dado, list | tuple):
        return [sanitizar_estrutura(v) for v in dado]
    return dado
