"""Configuração lida do ambiente e do arquivo .env (nunca do git).

Toda variável começa com RAIZ_. Exemplo: RAIZ_BANCO_URL=postgresql+psycopg://raiz:raiz@localhost:5432/raiz
"""

from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from raiz import RAIZ_REPO


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RAIZ_", env_file=(RAIZ_REPO / ".env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    banco_url: str = "postgresql+psycopg://raiz:raiz@localhost:5432/raiz"
    # banco descartável dos testes (é zerado a cada rodada de testes)
    banco_url_teste: str | None = None
    # chave para cifrar o esquema pessoal (telefone, BSUID); sem ela, nada pessoal é gravado
    chave_pessoal: SecretStr | None = None
    # Healthchecks (https://healthchecks.io ou instância própria fora do servidor da Raíz)
    healthchecks_url: str = "https://hc-ping.com"
    healthchecks_chave_ping: SecretStr | None = None
    # pasta onde o motor grava (motor/saida por padrão)
    motor_saida: str | None = None

    # Modelos de linguagem (E7). A chave da Anthropic também é aceita com o nome padrão ANTHROPIC_API_KEY.
    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("RAIZ_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
    )
    modelo_conversa: str = "claude-sonnet-5-5"  # conversa e leitura de documento (juiz da cascata)
    modelo_triagem: str = "claude-haiku-5-5"  # triagem (um dos votos baratos)
    modelo_local: str = "qwen3-4b-instruct-2507"  # o outro voto barato, no llama.cpp
    llama_url: str = "http://localhost:8080"

    # Langfuse (instância própria). Também aceita os nomes padrão do SDK.
    langfuse_public_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("RAIZ_LANGFUSE_PUBLIC_KEY", "LANGFUSE_PUBLIC_KEY")
    )
    langfuse_secret_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("RAIZ_LANGFUSE_SECRET_KEY", "LANGFUSE_SECRET_KEY")
    )
    langfuse_host: str | None = Field(
        default=None, validation_alias=AliasChoices("RAIZ_LANGFUSE_HOST", "LANGFUSE_HOST")
    )


@lru_cache
def config() -> Config:
    return Config()
