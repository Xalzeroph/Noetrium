ARG PYTHON_RUNTIME_IMAGE=python:3.12-slim-bookworm
FROM ${PYTHON_RUNTIME_IMAGE}

ARG NOETRIUM_ENVIRONMENT_BASE_REVISION
ARG NOETRIUM_ENVIRONMENT_BASE_BUILD_INPUT_DIGEST
ARG NOETRIUM_PYTHON_RUNTIME_IDENTITY_DIGEST

ENV PYTHONUNBUFFERED=1 \
    PLATFORM_STATE_DIR=/var/lib/noetrium \
    NOETRIUM_ENVIRONMENT_PROFILE=base

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin platform \
    && mkdir -p "$PLATFORM_STATE_DIR" /usr/local/lib/noetrium/environment-doctor.d \
    && chown -R platform:platform "$PLATFORM_STATE_DIR"

COPY --chmod=0755 deploy/environments/base/entrypoint.sh /usr/local/bin/noetrium-entrypoint

LABEL org.opencontainers.image.noetrium.environment.base-revision="${NOETRIUM_ENVIRONMENT_BASE_REVISION}" \
      org.opencontainers.image.noetrium.environment.base-build-input.sha256="${NOETRIUM_ENVIRONMENT_BASE_BUILD_INPUT_DIGEST}" \
      org.opencontainers.image.noetrium.python-runtime.sha256="${NOETRIUM_PYTHON_RUNTIME_IDENTITY_DIGEST}"

USER platform
ENTRYPOINT ["/usr/local/bin/noetrium-entrypoint"]
CMD ["environment-doctor", "base"]
