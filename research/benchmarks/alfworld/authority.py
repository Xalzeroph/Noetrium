from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest

ALFWORLD_RELEASE_REPOSITORY = "https://github.com/alfworld/alfworld"
ALFWORLD_RELEASE_VERSION = "0.2.2"
ALFWORLD_RELEASE_COMMIT = "32d16c3bc282ca3776516ab7acba0c67f01fa761"
ALFWORLD_RELEASE_PROVIDER = "alfworld.agents.environment.AlfredTWEnv"
ALFWORLD_RELEASE_DOWNLOADS = {
    "json": "https://aka.ms/alfworld/json_2.1.1_json.zip",
    "pddl": "https://aka.ms/alfworld/json_2.1.1_pddl.zip",
    "tw_pddl": "https://aka.ms/alfworld/json_2.1.1_tw-pddl.zip",
}
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
    "ALFWORLD_RELEASE_AUTHORITY_DIGEST",
    "ALFWORLD_RELEASE_COMMIT",
    "ALFWORLD_RELEASE_DOWNLOADS",
    "ALFWORLD_RELEASE_PROVIDER",
    "ALFWORLD_RELEASE_REPOSITORY",
    "ALFWORLD_RELEASE_VERSION",
]
