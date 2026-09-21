import pytest
from noetrium_platform.research.experimentation.binding import ResearchBindingRequirements

def test_trial_provider_requirement_id_is_nonempty() -> None:
    with pytest.raises(ValueError, match="trial provider requirement id must be a non-empty string"):
        ResearchBindingRequirements("")
