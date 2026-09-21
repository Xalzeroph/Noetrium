
ARG PLATFORM_BASE_IMAGE=noetrium:local
FROM ${PLATFORM_BASE_IMAGE}

ENV NOETRIUM_ENVIRONMENT_PROFILE=gui

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        dbus-x11 imagemagick openbox scrot x11-utils xdotool xvfb \
    && rm -rf /var/lib/apt/lists/*
USER platform

CMD ["environment-doctor", "gui"]
