import pytest
from noetrium_platform.research.experimentation.binding import ResearchModelRoleRequirement

def test_prompt_configuration_id_is_nonempty_when_present() -> None:
    with pytest.raises(ValueError, match="prompt configuration id must be a non-empty string"):
        ResearchModelRoleRequirement("solver","model",prompt_configuration_id="")
