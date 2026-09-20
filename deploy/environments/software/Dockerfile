# syntax=docker/dockerfile:1.7

ARG PLATFORM_BASE_IMAGE=noetrium:local
FROM ${PLATFORM_BASE_IMAGE}

ENV NOETRIUM_ENVIRONMENT_PROFILE=software

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential cmake jq ninja-build openssh-client patch rsync unzip \
    && rm -rf /var/lib/apt/lists/*
USER platform

CMD ["environment-doctor", "software"]
