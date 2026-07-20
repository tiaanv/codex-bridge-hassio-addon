FROM node:22-slim AS codex-cli

ARG CODEX_CLI_VERSION=0.139.0

RUN npm install --global "@openai/codex@${CODEX_CLI_VERSION}"

FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /usr/local/bin/uv
COPY --from=codex-cli /usr/local/bin/node /usr/local/bin/node
COPY --from=codex-cli /usr/local/lib/node_modules/@openai/codex /usr/local/lib/node_modules/@openai/codex

ARG GPTMOCK_COMMIT=88f1ba9f089056d4ed992c6cc84e0f6638cea6dc
ARG GPTMOCK_ARCHIVE_SHA256=0ed3179c167da0f1d31b01c1320ee23b4ba6740c2ab2a4f54ae49ea327f3cad5
ARG CODEX_CLI_VERSION=0.139.0
ARG BUILD_VERSION
ARG BUILD_ARCH

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH \
    GPTMOCK_HOME=/data \
    GPTMOCK_HOST=127.0.0.1 \
    GPTMOCK_PORT=8001 \
    GPTMOCK_LOGIN_BIND=127.0.0.1

WORKDIR /app

# Build GPTMock directly from its pinned GitHub source. Do not replace this
# with rapidrabbit76/gptmock from Docker Hub; that image can lag behind source.
ADD https://github.com/rapidrabbit76/GPTMock/archive/${GPTMOCK_COMMIT}.tar.gz /tmp/gptmock.tar.gz

RUN echo "${GPTMOCK_ARCHIVE_SHA256}  /tmp/gptmock.tar.gz" | sha256sum --check --strict - \
    && tar --extract --gzip --file=/tmp/gptmock.tar.gz --strip-components=1 --directory=/app \
    && rm /tmp/gptmock.tar.gz \
    && uv sync --frozen --no-dev \
    && ln --symbolic ../lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex \
    && codex --version

LABEL \
    io.hass.name="Codex Bridge (Hassio Add-on)" \
    io.hass.description="Home Assistant wrapper for GPTMock" \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}" \
    org.opencontainers.image.source="https://github.com/h3racl3z/codex-bridge-hassio-addon" \
    org.opencontainers.image.licenses="MIT AND Apache-2.0" \
    org.opencontainers.image.gptmock.commit="${GPTMOCK_COMMIT}" \
    org.opencontainers.image.codex.version="${CODEX_CLI_VERSION}"

COPY rootfs /

RUN chmod 0755 /run.sh

EXPOSE 8000 8099

ENTRYPOINT []
CMD ["/run.sh"]
