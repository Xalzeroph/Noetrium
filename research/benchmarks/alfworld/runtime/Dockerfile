FROM python:3.7.17-slim-bullseye

ARG ALFWORLD_COMMIT=32d16c3bc282ca3776516ab7acba0c67f01fa761
ARG TEXTWORLD_COMMIT=634f9f91fec732a79dd9e7623675301a53f06623
ARG DOWNWARD_COMMIT=84769171b9d965bf5739eaa7cf6604b0d9697534

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ALFWORLD_DATA=/data/alfworld \
    PYTHONPATH=/opt/alfworld:/opt/textworld

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake git ca-certificates curl libffi-dev && \
    rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade 'pip<24' 'setuptools<69' wheel && \
    python -m pip install \
      'numpy==1.21.6' 'gym==0.15.4' 'PyYAML==6.0.1' 'networkx==2.6.3' \
      'more-itertools==8.14.0' 'TatSu==4.4.0' 'hashids==1.3.1' \
      'mementos==1.3.1' 'prompt-toolkit==3.0.48' 'cffi==1.15.1' \
      'tqdm==4.67.1'

RUN git clone https://github.com/MarcCote/downward.git /opt/downward && \
    cd /opt/downward && git checkout "$DOWNWARD_COMMIT" && \
    python -m pip install --no-deps .

RUN git clone https://github.com/MarcCote/TextWorld.git /opt/textworld && \
    cd /opt/textworld && git checkout "$TEXTWORLD_COMMIT" && \
    printf '%s\n' \
      'import re' \
      'from textworld.envs.wrappers.tw_inform7 import TWInform7' \
      'from textworld.envs.pddl import PddlEnv' \
      '' \
      'def _guess_backend(path):' \
      '    if path.endswith(".tw-pddl"):' \
      '        return PddlEnv' \
      '    raise ValueError("Unsupported game format for ALFWorld text runtime: {}".format(path))' \
      > /opt/textworld/textworld/envs/__init__.py

RUN git clone https://github.com/alfworld/alfworld.git /opt/alfworld && \
    cd /opt/alfworld && git checkout "$ALFWORLD_COMMIT" && \
    printf '%s\n' \
      'from alfworld.agents.expert.handcoded_expert import HandCodedAgentTimeout, HandCodedAgentFailed' \
      'from alfworld.agents.expert.handcoded_expert_tw import HandCodedTWAgent' \
      > /opt/alfworld/alfworld/agents/expert/__init__.py && \
    printf '%s\n' \
      'from alfworld.agents.environment.alfred_tw_env import AlfredTWEnv' \
      > /opt/alfworld/alfworld/agents/environment/__init__.py

WORKDIR /opt/noetrium/alfworld
COPY worker.py /opt/noetrium/alfworld/worker.py
COPY paper_eval_config.yaml /opt/noetrium/alfworld/paper_eval_config.yaml

ENTRYPOINT ["python", "-u", "/opt/noetrium/alfworld/worker.py"]
CMD ["--data-root", "/data/alfworld", "--config", "/opt/noetrium/alfworld/paper_eval_config.yaml"]
