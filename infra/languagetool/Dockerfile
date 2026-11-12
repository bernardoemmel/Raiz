# Revisor de estilo e legibilidade do português (E9, passo 2): servidor do LanguageTool, chamado pelo back-end antes
# de cada mensagem ao dono (raiz/revisor.py). LanguageTool é LGPL-2.1: roda só como serviço no servidor, separado, sem
# código copiado para o produto. Só o português é usado; as outras línguas ficam no pacote, mas não carregam.
#   docker compose --env-file .env -f infra/docker-compose.yml up -d revisor
#   RAIZ_LANGUAGETOOL_URL=http://localhost:8010 no .env
FROM eclipse-temurin:21-jre-noble

ARG LT_VERSAO=6.6
RUN apt-get update \
    && apt-get install -y --no-install-recommends unzip curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL -o /tmp/lt.zip "https://languagetool.org/download/LanguageTool-${LT_VERSAO}.zip" \
    && unzip -q /tmp/lt.zip -d /opt \
    && mv "/opt/LanguageTool-${LT_VERSAO}" /opt/languagetool \
    && rm /tmp/lt.zip \
    && useradd --system --uid 10010 languagetool

COPY servidor.properties /opt/languagetool/servidor.properties
USER languagetool
WORKDIR /opt/languagetool
EXPOSE 8010
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
    CMD curl -fsS "http://localhost:8010/v2/languages" > /dev/null || exit 1
# --public: escuta em todas as interfaces dentro do contêiner; fora dele, o compose só abre para a própria máquina
CMD ["java", "-Xms256m", "-Xmx768m", "-cp", "languagetool-server.jar", "org.languagetool.server.HTTPServer", \
     "--port", "8010", "--public", "--config", "servidor.properties"]
