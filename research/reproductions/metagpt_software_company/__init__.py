from .fidelity import (
    METAGPT_PAPER_ERA_COMMIT,
    METAGPT_SOFTWARE_COMPANY_FIDELITY,
    MetaGPTSoftwareCompanyFidelity,
)

__all__ = [
    "METAGPT_PAPER_ERA_COMMIT",
    "METAGPT_SOFTWARE_COMPANY_FIDELITY",
    "MetaGPTSoftwareCompanyFidelity",
]

from .program import (
    build_metagpt_software_company_method_program,
    metagpt_initial_state,
)
from .study import (
    build_metagpt_humaneval_study,
    metagpt_humaneval_trial_protocol,
)

__all__ = tuple(dict.fromkeys((*__all__,
    "build_metagpt_software_company_method_program",
    "metagpt_initial_state",
    "build_metagpt_humaneval_study",
    "metagpt_humaneval_trial_protocol",
)))
