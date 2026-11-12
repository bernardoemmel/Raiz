"""Configuração por variáveis de ambiente (segredos só no ambiente, nunca no git).

| Variável | Para quê |
|---|---|
| RAIZ_VIGILANCIA_DIR | pasta do estado (alertas, marcações, eventos); padrão raiz/vigilancia/.dados/estado |
| RAIZ_VIGILANCIA_CACHE | pasta do cache (polígonos do Release dados, CSV do Ibama, KML); padrão .dados/cache |
| RAIZ_REPO, RAIZ_TAG_DADOS | de onde vêm os polígonos (bernardoemmel/raiz, Release dados) |
| RAIZ_TAG_VIGILANCIA | Release onde a vigilância publica (padrão vigilancia) |
| RAIZ_VIGILANCIA_CHAVE | chave Fernet que cifra a parte privada (projetos, perdas, marcações) antes de publicar |
| RAIZ_GITHUB_TOKEN (ou GITHUB_TOKEN, GH_TOKEN) | token com permissão de escrever no Release |
| RAIZ_PROJETOS_PRIVADO | YAML (texto ou caminho) com os dados comerciais dos projetos, juntado pelo id |
| MAPBIOMAS_ALERTA_EMAIL, MAPBIOMAS_ALERTA_SENHA | conta da Plataforma MapBiomas Alerta |
| FIRMS_MAP_KEY | chave da API do FIRMS (opcional; sem ela, arquivos públicos de 24 h, 48 h e 7 dias) |
| RAIZ_API_TOKEN | token Bearer das rotas (servidor avulso; no back-end vale a mesma variável) |
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from raiz.vigilancia import PASTA


def _env(nome: str, padrao: str | None = None) -> str | None:
    v = os.environ.get(nome)
    return v if v not in (None, "") else padrao


@dataclass
class Config:
    estado: Path = field(default_factory=lambda: Path(_env("RAIZ_VIGILANCIA_DIR", str(PASTA / ".dados" / "estado"))))
    cache: Path = field(default_factory=lambda: Path(_env("RAIZ_VIGILANCIA_CACHE", str(PASTA / ".dados" / "cache"))))
    repo: str = field(default_factory=lambda: _env("RAIZ_REPO", "bernardoemmel/raiz"))
    tag_dados: str = field(default_factory=lambda: _env("RAIZ_TAG_DADOS", "dados"))
    tag_vigilancia: str = field(default_factory=lambda: _env("RAIZ_TAG_VIGILANCIA", "vigilancia"))
    chave: str | None = field(default_factory=lambda: _env("RAIZ_VIGILANCIA_CHAVE"))
    token_github: str | None = field(
        default_factory=lambda: _env("RAIZ_GITHUB_TOKEN") or _env("GITHUB_TOKEN") or _env("GH_TOKEN")
    )

    def url_release(self, tag: str, arquivo: str) -> str:
        return f"https://github.com/{self.repo}/releases/download/{tag}/{arquivo}"


def config() -> Config:
    return Config()
