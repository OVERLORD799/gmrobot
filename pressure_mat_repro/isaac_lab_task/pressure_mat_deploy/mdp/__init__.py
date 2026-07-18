"""MDP terms for the pressure-mat deploy task.

Stock IsaacLab MDP terms (rewards/events/commands/observations/terminations)
come in via the wildcard import; the project-specific tactile observation,
deploy-walk obs helpers, custom termination, and the leg-only walk action are
re-exported from the sibling modules.
"""

from omni.isaac.lab.envs.mdp import *  # noqa: F401, F403

from .observations import (  # noqa: F401
    tactile_force,
    tactile_force_multi,
    tactile_force_multi_net,
    velocity_commands_deploy,
    walk_sin_phase,
    walk_cos_phase,
    last_action_padded_29,
    _PHASE_PERIOD,
)
from .terminations import root_out_of_mat_bounds  # noqa: F401
from .walk_action import WalkJointAction, WalkJointActionCfg  # noqa: F401
