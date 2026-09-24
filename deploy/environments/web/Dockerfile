
ARG PLATFORM_BASE_IMAGE=noetrium:local
FROM ${PLATFORM_BASE_IMAGE}

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
