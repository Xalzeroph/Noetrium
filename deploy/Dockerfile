ARG PYTHON_RUNTIME_IMAGE=python:3.12-slim-bookworm
FROM ${PYTHON_RUNTIME_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PLATFORM_STATE_DIR=/var/lib/noetrium \
    PLATFORM_EMBEDDED_WHEEL=/opt/noetrium-artifact/noetrium_platform.whl

WORKDIR /opt/noetrium

# The base runtime is deliberately VCS-free. Source provenance is already frozen
# into the evidence-bound wheel and content-addressed source digest before this
# image is built; runtime execution must not require Git or package-manager I/O.

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin platform \
    && mkdir -p "$PLATFORM_STATE_DIR" \
    && chown -R platform:platform /opt/noetrium "$PLATFORM_STATE_DIR"

# The formal container context is materialized by prepare_container_context.py.
# Third-party runtime dependencies are a distinct content layer. Source-only
# Noetrium changes therefore never cause dependency resolution/download again.
COPY runtime-dependencies.txt /tmp/noetrium-runtime-dependencies.txt
RUN python -m pip install -r /tmp/noetrium-runtime-dependencies.txt     && rm -f /tmp/noetrium-runtime-dependencies.txt

# The application wheel is evidence-bound and installed without dependency
# resolution because all external runtime dependencies already exist above.
COPY *.whl /tmp/wheelhouse/
ARG PLATFORM_WHEEL_SHA256=unknown
RUN wheel="$(find /tmp/wheelhouse -maxdepth 1 -type f -name '*.whl' -print)" \
    && test "$(find /tmp/wheelhouse -maxdepth 1 -type f -name '*.whl' | wc -l)" -eq 1 \
    && printf '%s  %s\n' "$PLATFORM_WHEEL_SHA256" "$wheel" | sha256sum -c - \
    && python -m pip install --no-deps "$wheel" \
    && mkdir -p "$(dirname "$PLATFORM_EMBEDDED_WHEEL")" \
    && cp "$wheel" "$PLATFORM_EMBEDDED_WHEEL" \
    && rm -rf /tmp/wheelhouse \
    && chmod 0444 "$PLATFORM_EMBEDDED_WHEEL"

# Entrypoint bytes are independent from wheel installation. Keep this COPY after
# the wheel layer so entrypoint-only changes do not reinstall the package.
COPY --chmod=0755 container-entrypoint.sh /usr/local/bin/noetrium-entrypoint

# Source-specific provenance is metadata-only. Keep it after all expensive
# reusable filesystem layers so commit/evidence changes do not poison cache.
ARG PLATFORM_SOURCE_SHA=unknown
ARG PLATFORM_RUNTIME_PROJECTION_SHA256=unknown
ARG PLATFORM_DISTRIBUTION_EVIDENCE_SHA256=unknown
ARG PLATFORM_PYTHON_RUNTIME_IDENTITY_DIGEST
LABEL org.opencontainers.image.revision="${PLATFORM_SOURCE_SHA}" \
      org.opencontainers.image.noetrium.runtime-projection.sha256="${PLATFORM_RUNTIME_PROJECTION_SHA256}" \
      org.opencontainers.image.noetrium.wheel.sha256="${PLATFORM_WHEEL_SHA256}" \
      org.opencontainers.image.noetrium.distribution-evidence.sha256="${PLATFORM_DISTRIBUTION_EVIDENCE_SHA256}" \
      org.opencontainers.image.noetrium.python-runtime.sha256="${PLATFORM_PYTHON_RUNTIME_IDENTITY_DIGEST}"

USER platform
ENTRYPOINT ["/usr/local/bin/noetrium-entrypoint"]
CMD ["doctor"]
