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
    healthchecks_modelo_slug: str = "raiz-{tarefa}"  # campos: {tarefa}, {uf}, {cod}
    # escalonamento dos alertas de operação (raiz/operacao/alertas.py): ntfy (aplicativo no celular) e, havendo
    # segunda pessoa de plantão, GoAlert. Sem tópico nem URL, o envio é simulado e fica registrado no alerta.
    ntfy_url: str = "https://ntfy.sh"
    ntfy_topico: SecretStr | None = None  # o nome do tópico funciona como senha: escolher um longo e aleatório
    ntfy_token: SecretStr | None = None
    goalert_url: SecretStr | None = None  # URL da integração genérica (já traz o token)
    # pasta onde o motor trabalha (cache/, saida/, mapbiomas/...); padrão: motor/
    motor_dir_trabalho: str | None = None
    # espelho local da coleta (E1), em Parquet por município: <espelho>/car/<UF>/<mun>.parquet, sigef/...
    espelho_dir: str | None = None
    # cache em disco dos blocos de rasters na nuvem (YbYrá, GPW...): a próxima rodada lê do disco
    raster_cache_dir: str | None = None
    raster_cache_gb: float = 20.0
    # arquivos do front/scripts/geo.py (GeoJSON das camadas e base_<mun>.pmtiles), servidos pela API; padrão front/geo
    geo_dir: str | None = None
    # mapa base do Brasil (recorte do Protomaps, fontes e sprites), servido em /mapa; padrão dados/mapa
    mapa_dir: str | None = None
    # imagens de satélite por fazenda (WebP e metadados), geradas na primeira chamada; padrão dados/imagens
    imagens_dir: str | None = None
    # cache das entradas do valor para quem restaura (Copernicus, CHIRPS, SoilGrids); padrão dados/cache_restauracao
    cache_restauracao_dir: str | None = None
    # armazenamento dos arquivos do motor (agente Dados, raiz/executor): s3://balde/prefixo (Cloudflare R2, SeaweedFS ou
    # outro compatível com S3) ou uma pasta local; padrão dados/armazem. Credenciais só aqui, por variável de ambiente.
    armazem_url: str | None = None
    s3_endpoint: str | None = None  # ex.: https://<conta>.r2.cloudflarestorage.com ou http://localhost:8333
    s3_regiao: str = "auto"
    s3_access_key_id: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("RAIZ_S3_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID")
    )
    s3_secret_access_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("RAIZ_S3_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY")
    )
    # pasta local onde o back-end espelha o armazenamento para carregar no banco; padrão dados/armazem_local
    armazem_espelho_dir: str | None = None
    # cartões, adesivos e vídeos públicos por código curto (cache); padrão dados/publico
    publico_dir: str | None = None
    # voz do vídeo (Qwen3-TTS, liga quando o pacote qwen-tts está instalado no servidor)
    voz_modelo: str | None = None
    voz_falante: str | None = None

    # Modelos de linguagem (E7). A chave da Anthropic também é aceita com o nome padrão ANTHROPIC_API_KEY.
    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("RAIZ_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
    )
    orcamento_mensal_usd: float | None = None  # teto de gasto com modelos; o comando de custo compara com ele
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

    # WhatsApp Cloud API (PyWa). Webhook em /whatsapp, assinatura conferida com o app_secret.
    whatsapp_phone_id: str | None = None
    whatsapp_token: SecretStr | None = None
    whatsapp_verify_token: SecretStr | None = None
    whatsapp_app_secret: SecretStr | None = None
    # token do backoffice para a API (sem ele, só /saude e o webhook respondem)
    api_token: SecretStr | None = None
    # origens do front que podem chamar a API pelo navegador (CORS), separadas por vírgula; vazio = nenhuma
    api_origens: str = ""


@lru_cache
def config() -> Config:
    return Config()
