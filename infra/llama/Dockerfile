# llama-server (llama.cpp, MIT) compilado com llguidance (MIT) para a gramática JSON (E7 passo 10).
#
# Com LLAMA_LLGUIDANCE=ON, o JSON Schema do response_format vai direto ao llguidance, sem mudar a chamada
# (docs/llguidance.md do llama.cpp): cobre mais do JSON Schema que o GBNF e calcula a máscara de tokens mais rápido.
# O llguidance pede o compilador de Rust (cargo) só na construção; a imagem final leva só o servidor.
#
# Construir e subir (no servidor):  docker compose -f infra/docker-compose.yml up -d --build llama
# Trocar de versão: mude LLAMA_TAG (uma tag bNNNNN de github.com/ggml-org/llama.cpp) e rode o teste próprio de novo
# (`raiz modelos calibrar`), porque a confiança depende da versão.

ARG UBUNTU_VERSION=24.04

FROM docker.io/ubuntu:${UBUNTU_VERSION} AS build
ARG LLAMA_TAG=b12300

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential cmake git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Rust estável para o llguidance (o cargo do apt costuma ser velho demais)
RUN curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable
ENV PATH=/root/.cargo/bin:${PATH}

WORKDIR /src
RUN git clone --depth 1 --branch ${LLAMA_TAG} https://github.com/ggml-org/llama.cpp .

# Sem interface web (LLAMA_BUILD_UI e LLAMA_USE_PREBUILT_UI desligados) e sem HTTPS para baixar modelo: o GGUF vem
# do volume. CPU com todas as variantes, carregadas na hora (como a imagem oficial).
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
        -DLLAMA_LLGUIDANCE=ON \
        -DGGML_NATIVE=OFF -DGGML_BACKEND_DL=ON -DGGML_CPU_ALL_VARIANTS=ON \
        -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF \
        -DLLAMA_BUILD_UI=OFF -DLLAMA_USE_PREBUILT_UI=OFF -DLLAMA_OPENSSL=OFF \
    && cmake --build build --target llama-server -j"$(nproc)"

RUN mkdir -p /out \
    && find build -name "*.so*" -exec cp -P {} /out/ \; \
    && cp build/bin/llama-server /out/

FROM docker.io/ubuntu:${UBUNTU_VERSION} AS server

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /out/ /app/
WORKDIR /app

ENV LLAMA_ARG_HOST=0.0.0.0
ENV LLAMA_ARG_PORT=8080

HEALTHCHECK CMD ["curl", "-f", "http://localhost:8080/health"]

ENTRYPOINT ["/app/llama-server"]
