# Docker-first control-plane runtime. Keep the Python ABI aligned with the
# platform runtime while importing only the Docker client from the official
# Docker CLI image.
ARG DOCKER_CLI_IMAGE=docker:27-cli
ARG PYTHON_RUNTIME_IMAGE=python:3.12-slim-bookworm
ARG NOETRIUM_BOOTSTRAP_INPUT_DIGEST

FROM ${DOCKER_CLI_IMAGE} AS docker-cli

FROM ${PYTHON_RUNTIME_IMAGE}

ARG NOETRIUM_BOOTSTRAP_INPUT_DIGEST

RUN test -r /etc/ssl/certs/ca-certificates.crt

COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-buildx /usr/local/libexec/docker/cli-plugins/docker-buildx
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose

COPY pyproject.toml /tmp/noetrium-pyproject.toml
RUN python3 -c 'import pathlib, subprocess, sys, tomllib; p=tomllib.loads(pathlib.Path("/tmp/noetrium-pyproject.toml").read_text()); build=p.get("build-system", {}).get("requires", []); project=p["project"]; deps=project.get("dependencies", []); release=project.get("optional-dependencies", {}).get("release", []); subprocess.check_call([sys.executable, "-m", "pip", "install", *build, *deps, *release])'     && rm -f /tmp/noetrium-pyproject.toml

LABEL io.noetrium.bootstrap.input-sha256="${NOETRIUM_BOOTSTRAP_INPUT_DIGEST}"

ENV PYTHONUNBUFFERED=1     PIP_DISABLE_PIP_VERSION_CHECK=1     PIP_NO_CACHE_DIR=1

WORKDIR /workspace

RUN python3 -c 'import sys; assert sys.version_info >= (3, 11), sys.version'     && python3 -m venv /tmp/noetrium-venv-probe     && rm -rf /tmp/noetrium-venv-probe     && docker --version     && docker compose version

ENTRYPOINT ["python3", "scripts/build_environment_images.py"]
