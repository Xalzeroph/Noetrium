from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest

ALFWORLD_RELEASE_REPOSITORY = "https://github.com/alfworld/alfworld"
ALFWORLD_RELEASE_VERSION = "0.2.2"
ALFWORLD_RELEASE_COMMIT = "32d16c3bc282ca3776516ab7acba0c67f01fa761"
ALFWORLD_RELEASE_PROVIDER = "alfworld.agents.environment.AlfredTWEnv"
ALFWORLD_TEXTWORLD_REPOSITORY = "https://github.com/MarcCote/TextWorld"
ALFWORLD_TEXTWORLD_BRANCH = "handcoded_expert_integration"
ALFWORLD_TEXTWORLD_COMMIT = "634f9f91fec732a79dd9e7623675301a53f06623"
ALFWORLD_FAST_DOWNWARD_REPOSITORY = "https://github.com/MarcCote/downward"
ALFWORLD_FAST_DOWNWARD_BRANCH = "faster_replan"
ALFWORLD_FAST_DOWNWARD_COMMIT = "84769171b9d965bf5739eaa7cf6604b0d9697534"
ALFWORLD_RELEASE_DOWNLOADS = {
    "json": "https://aka.ms/alfworld/json_2.1.1_json.zip",
    "pddl": "https://aka.ms/alfworld/json_2.1.1_pddl.zip",
    "tw_pddl": "https://aka.ms/alfworld/json_2.1.1_tw-pddl.zip",
}
ALFWORLD_TEXT_RUNTIME_AUTHORITY_DIGEST = canonical_digest(
    {
        "alfworld": {
            "repository": ALFWORLD_RELEASE_REPOSITORY,
            "version": ALFWORLD_RELEASE_VERSION,
            "commit": ALFWORLD_RELEASE_COMMIT,
            "provider": ALFWORLD_RELEASE_PROVIDER,
        },
        "textworld": {
            "repository": ALFWORLD_TEXTWORLD_REPOSITORY,
            "branch": ALFWORLD_TEXTWORLD_BRANCH,
            "commit": ALFWORLD_TEXTWORLD_COMMIT,
        },
        "fast_downward": {
            "repository": ALFWORLD_FAST_DOWNWARD_REPOSITORY,
            "branch": ALFWORLD_FAST_DOWNWARD_BRANCH,
            "commit": ALFWORLD_FAST_DOWNWARD_COMMIT,
        },
    }
)

ALFWORLD_RELEASE_AUTHORITY_DIGEST = canonical_digest(
    {
        "repository": ALFWORLD_RELEASE_REPOSITORY,
        "version": ALFWORLD_RELEASE_VERSION,
        "commit": ALFWORLD_RELEASE_COMMIT,
        "provider": ALFWORLD_RELEASE_PROVIDER,
        "downloads": ALFWORLD_RELEASE_DOWNLOADS,
    }
)

__all__ = [
    "ALFWORLD_FAST_DOWNWARD_BRANCH",
    "ALFWORLD_FAST_DOWNWARD_COMMIT",
    "ALFWORLD_FAST_DOWNWARD_REPOSITORY",
    "ALFWORLD_RELEASE_AUTHORITY_DIGEST",
    "ALFWORLD_RELEASE_COMMIT",
    "ALFWORLD_RELEASE_DOWNLOADS",
    "ALFWORLD_RELEASE_PROVIDER",
    "ALFWORLD_RELEASE_REPOSITORY",
    "ALFWORLD_RELEASE_VERSION",
    "ALFWORLD_TEXTWORLD_BRANCH",
    "ALFWORLD_TEXTWORLD_COMMIT",
    "ALFWORLD_TEXTWORLD_REPOSITORY",
    "ALFWORLD_TEXT_RUNTIME_AUTHORITY_DIGEST",
]
