# syntax=docker/dockerfile:1.7

FROM python:3.12-slim-bookworm

ARG PLATFORM_SOURCE_SHA=unknown
ARG PLATFORM_WHEEL_SHA256=unknown
ARG PLATFORM_DISTRIBUTION_EVIDENCE_SHA256=unknown
LABEL org.opencontainers.image.revision="${PLATFORM_SOURCE_SHA}" \
      org.opencontainers.image.noetrium.wheel.sha256="${PLATFORM_WHEEL_SHA256}" \
      org.opencontainers.image.noetrium.distribution-evidence.sha256="${PLATFORM_DISTRIBUTION_EVIDENCE_SHA256}"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PLATFORM_STATE_DIR=/var/lib/noetrium \
    PLATFORM_EMBEDDED_WHEEL=/opt/noetrium-artifact/noetrium_platform.whl

WORKDIR /opt/noetrium
COPY *.whl /tmp/wheelhouse/
COPY container-entrypoint.sh /usr/local/bin/noetrium-entrypoint

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN wheel="$(find /tmp/wheelhouse -maxdepth 1 -type f -name '*.whl' -print)" \
    && test "$(find /tmp/wheelhouse -maxdepth 1 -type f -name '*.whl' | wc -l)" -eq 1 \
    && printf '%s  %s\n' "$PLATFORM_WHEEL_SHA256" "$wheel" | sha256sum -c - \
    && python -m pip install --no-deps "$wheel" \
    && mkdir -p "$(dirname "$PLATFORM_EMBEDDED_WHEEL")" \
    && cp "$wheel" "$PLATFORM_EMBEDDED_WHEEL" \
    && rm -rf /tmp/wheelhouse \
    && chmod 0444 "$PLATFORM_EMBEDDED_WHEEL" \
    && chmod 0755 /usr/local/bin/noetrium-entrypoint

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin platform \
    && mkdir -p "$PLATFORM_STATE_DIR" \
    && chown -R platform:platform /opt/noetrium "$PLATFORM_STATE_DIR"

USER platform
ENTRYPOINT ["/usr/local/bin/noetrium-entrypoint"]
CMD ["doctor"]
