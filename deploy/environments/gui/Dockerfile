
ARG PLATFORM_BASE_IMAGE=noetrium:local
FROM ${PLATFORM_BASE_IMAGE}

ARG NOETRIUM_ENVIRONMENT_PROFILE_ID
ARG NOETRIUM_ENVIRONMENT_CATEGORY_ID
ARG NOETRIUM_ENVIRONMENT_PROFILE_REVISION
LABEL org.opencontainers.image.noetrium.environment.profile-id="${NOETRIUM_ENVIRONMENT_PROFILE_ID}" \
      org.opencontainers.image.noetrium.environment.category-id="${NOETRIUM_ENVIRONMENT_CATEGORY_ID}" \
      org.opencontainers.image.noetrium.environment.profile-revision="${NOETRIUM_ENVIRONMENT_PROFILE_REVISION}"

ENV NOETRIUM_ENVIRONMENT_PROFILE=gui

USER root
RUN mkdir -p /usr/local/lib/noetrium/environment-doctor.d
COPY deploy/environments/gui/doctor.sh /usr/local/lib/noetrium/environment-doctor.d/gui
RUN chmod 0755 /usr/local/lib/noetrium/environment-doctor.d/gui
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        dbus-x11 imagemagick openbox scrot x11-utils xdotool xvfb \
    && rm -rf /var/lib/apt/lists/*
USER platform

CMD ["environment-doctor", "gui"]
