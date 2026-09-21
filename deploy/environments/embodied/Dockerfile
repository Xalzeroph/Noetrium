
ARG PLATFORM_BASE_IMAGE=noetrium:local
FROM ${PLATFORM_BASE_IMAGE}

ENV NOETRIUM_ENVIRONMENT_PROFILE=embodied

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libegl1 libgl1 libglfw3 libosmesa6 libglib2.0-0 \
        libx11-6 libxext6 libxrender1 mesa-utils xvfb \
    && rm -rf /var/lib/apt/lists/*
USER platform

CMD ["environment-doctor", "embodied"]
