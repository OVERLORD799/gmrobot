# Copyright (c) 2022-2025, The Isaac Lab Project Developers (https://github.com/isaac-sim/IsaacLab/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""
Python module serving as a project/extension template.
"""

# Register Gym environments / UI when Isaac stack is available.
# Outside Kit (import gates, offline tooling) these deps may be absent.
try:
    from .tasks import *  # noqa: F401,F403
except ModuleNotFoundError:
    pass

try:
    from .ui_extension_example import *  # noqa: F401,F403
except ModuleNotFoundError:
    pass
