
ARG PLATFORM_BASE_IMAGE=noetrium:local
FROM ${PLATFORM_BASE_IMAGE}

ARG NOETRIUM_ENVIRONMENT_PROFILE_ID
ARG NOETRIUM_ENVIRONMENT_CATEGORY_ID
ARG NOETRIUM_ENVIRONMENT_PROFILE_REVISION
LABEL org.opencontainers.image.noetrium.environment.profile-id="${NOETRIUM_ENVIRONMENT_PROFILE_ID}" \
      org.opencontainers.image.noetrium.environment.category-id="${NOETRIUM_ENVIRONMENT_CATEGORY_ID}" \
      org.opencontainers.image.noetrium.environment.profile-revision="${NOETRIUM_ENVIRONMENT_PROFILE_REVISION}"

ENV NOETRIUM_ENVIRONMENT_PROFILE=embodied

USER root
RUN mkdir -p /usr/local/lib/noetrium/environment-doctor.d
COPY deploy/environments/embodied/doctor.sh /usr/local/lib/noetrium/environment-doctor.d/embodied
RUN chmod 0755 /usr/local/lib/noetrium/environment-doctor.d/embodied
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libegl1 libgl1 libglfw3 libosmesa6 libglib2.0-0 \
        libx11-6 libxext6 libxrender1 mesa-utils xvfb \
    && rm -rf /var/lib/apt/lists/*
USER platform

CMD ["environment-doctor", "embodied"]
