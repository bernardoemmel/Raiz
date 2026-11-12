"""Configuração lida do ambiente e do arquivo .env (nunca do git).

Toda variável começa com RAIZ_. Exemplo: RAIZ_BANCO_URL=postgresql+psycopg://raiz:raiz@localhost:5432/raiz
"""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from raiz import RAIZ_REPO


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RAIZ_", env_file=(RAIZ_REPO / ".env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    banco_url: str = "postgresql+psycopg://raiz:raiz@localhost:5432/raiz"
    # chave para cifrar o esquema pessoal (telefone, BSUID); sem ela, nada pessoal é gravado
    chave_pessoal: SecretStr | None = None
    # Healthchecks (https://healthchecks.io ou instância própria fora do servidor da Raíz)
    healthchecks_url: str = "https://hc-ping.com"
    healthchecks_chave_ping: SecretStr | None = None
    # pasta onde o motor grava (motor/saida por padrão)
    motor_saida: str | None = None


@lru_cache
def config() -> Config:
    return Config()
