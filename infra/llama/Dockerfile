# syntax=docker/dockerfile:1
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
ARG RUST_VERSION=1.100.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential cmake git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Rust fixado na versão validada; o cargo do apt pode ser velho demais. O segredo proxy_ca é opcional: em
# ambientes com proxy TLS, monte o conjunto de CAs na construção, sem copiá-lo para a imagem final.
RUN --mount=type=secret,id=proxy_ca,target=/etc/ssl/certs/ca-certificates.crt \
    curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain ${RUST_VERSION}
ENV PATH=/root/.cargo/bin:${PATH}

WORKDIR /src
RUN --mount=type=secret,id=proxy_ca,target=/etc/ssl/certs/ca-certificates.crt \
    git clone --depth 1 --branch ${LLAMA_TAG} https://github.com/ggml-org/llama.cpp .

# Sem interface web (LLAMA_BUILD_UI e LLAMA_USE_PREBUILT_UI desligados) e sem HTTPS para baixar modelo: o GGUF vem
# do volume. CPU com todas as variantes, carregadas na hora (como a imagem oficial).
RUN --mount=type=secret,id=proxy_ca,target=/etc/ssl/certs/ca-certificates.crt \
    cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
        -DLLAMA_LLGUIDANCE=ON \
        -DGGML_NATIVE=OFF -DGGML_BACKEND_DL=ON -DGGML_CPU_ALL_VARIANTS=ON \
        -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF \
        -DLLAMA_BUILD_UI=OFF -DLLAMA_USE_PREBUILT_UI=OFF -DLLAMA_OPENSSL=OFF \
    && cmake --build build --target llguidance_ext -j"$(nproc)"

# O build.rs do llguidance 1.0.1 supõe o layout antigo de OUT_DIR. Com Cargo 1.100, o header vai para release/build,
# mas o CMake do llama.cpp b12300 procura em release. Copiar o header da MESMA revisão do código Rust evita depender
# desse layout interno; não mudar a gramática nem trocar de versão silenciosamente.
RUN cp build/llguidance/source/parser/llguidance.h build/llguidance/source/target/release/llguidance.h \
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
