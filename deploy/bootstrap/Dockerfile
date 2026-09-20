# syntax=docker/dockerfile:1.7

# Deployment control-plane image. The host contract is Docker only: Python and
# release tooling execute here rather than leaking from the host workstation.
ARG DOCKER_CLI_IMAGE=docker:27-cli
FROM ${DOCKER_CLI_IMAGE}

RUN apk add --no-cache \
      git \
      python3 \
      py3-pip \
      py3-virtualenv

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /workspace

RUN python3 -c 'import sys; assert sys.version_info >= (3, 11), sys.version'

ENTRYPOINT ["python3", "scripts/build_environment_images.py"]
