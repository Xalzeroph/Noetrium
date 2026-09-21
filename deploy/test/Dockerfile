ARG PLATFORM_TEST_BASE_IMAGE=noetrium:local
FROM ${PLATFORM_TEST_BASE_IMAGE}

USER root
ARG PYTEST_VERSION=8.4.2
RUN python -m pip install --no-cache-dir "pytest==${PYTEST_VERSION}"
USER platform
WORKDIR /workspace
