# syntax=docker/dockerfile:1.7

ARG PLATFORM_BASE_IMAGE=noetrium:local
FROM ${PLATFORM_BASE_IMAGE}

ENV NOETRIUM_ENVIRONMENT_PROFILE=web

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium chromium-driver fonts-liberation \
    && rm -rf /var/lib/apt/lists/*
USER platform

CMD ["environment-doctor", "web"]
