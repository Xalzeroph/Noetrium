ARG BASE_IMAGE
FROM ${BASE_IMAGE}

ARG NOETRIUM_PROJECT_RUNTIME_KEY
ARG NOETRIUM_PROJECT_RUNTIME_BASE_IMAGE_ID

COPY requirements.lock /tmp/noetrium-project-requirements.lock

RUN python3 -m pip install \
      --disable-pip-version-check \
      --no-input \
      --no-cache-dir \
      --no-deps \
      --require-hashes \
      -r /tmp/noetrium-project-requirements.lock \
    && python3 -m pip check \
    && rm -f /tmp/noetrium-project-requirements.lock

LABEL io.noetrium.project-runtime="true" \
      io.noetrium.project-runtime-key="${NOETRIUM_PROJECT_RUNTIME_KEY}" \
      io.noetrium.project-runtime-base-image-id="${NOETRIUM_PROJECT_RUNTIME_BASE_IMAGE_ID}"
