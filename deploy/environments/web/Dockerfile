
ARG PLATFORM_ENVIRONMENT_BASE_IMAGE=noetrium-env-base:local
FROM ${PLATFORM_ENVIRONMENT_BASE_IMAGE}

ARG NOETRIUM_ENVIRONMENT_PROFILE_ID
ARG NOETRIUM_ENVIRONMENT_CATEGORY_ID
ARG NOETRIUM_ENVIRONMENT_PROFILE_REVISION
ARG NOETRIUM_ENVIRONMENT_BUILD_INPUT_DIGEST
LABEL org.opencontainers.image.noetrium.environment.profile-id="${NOETRIUM_ENVIRONMENT_PROFILE_ID}" \
      org.opencontainers.image.noetrium.environment.category-id="${NOETRIUM_ENVIRONMENT_CATEGORY_ID}" \
      org.opencontainers.image.noetrium.environment.profile-revision="${NOETRIUM_ENVIRONMENT_PROFILE_REVISION}" \
      org.opencontainers.image.noetrium.environment.build-input.sha256="${NOETRIUM_ENVIRONMENT_BUILD_INPUT_DIGEST}"

ENV NOETRIUM_ENVIRONMENT_PROFILE=web

USER root
RUN mkdir -p /usr/local/lib/noetrium/environment-doctor.d
COPY deploy/environments/web/doctor.sh /usr/local/lib/noetrium/environment-doctor.d/web
RUN chmod 0755 /usr/local/lib/noetrium/environment-doctor.d/web
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium chromium-driver fonts-liberation \
    && rm -rf /var/lib/apt/lists/*
USER platform

CMD ["environment-doctor", "web"]
