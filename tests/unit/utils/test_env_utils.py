#  Copyright (c) ZenML GmbH 2023. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at:
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
#  or implied. See the License for the specific language governing
#  permissions and limitations under the License.

from contextlib import ExitStack as does_not_raise

import pytest

from zenml.utils.env_utils import (
    reconstruct_environment_variables,
    split_environment_variables,
)


def test_split_reconstruct_large_env_vars():
    """Test that splitting and reconstructing large environment variables works."""
    env = {
        "ARIA_TEST_ENV_VAR": "aria",
        "AXL_TEST_ENV_VAR": "axl is gray and puffy",
        "BLUPUS_TEST_ENV_VAR": "blupus",
    }

    split_environment_variables(env=env, size_limit=4)

    assert env == {
        "ARIA_TEST_ENV_VAR": "aria",
        "AXL_TEST_ENV_VAR_CHUNK_0": "axl ",
        "AXL_TEST_ENV_VAR_CHUNK_1": "is g",
        "AXL_TEST_ENV_VAR_CHUNK_2": "ray ",
        "AXL_TEST_ENV_VAR_CHUNK_3": "and ",
        "AXL_TEST_ENV_VAR_CHUNK_4": "puff",
        "AXL_TEST_ENV_VAR_CHUNK_5": "y",
        "BLUPUS_TEST_ENV_VAR_CHUNK_0": "blup",
        "BLUPUS_TEST_ENV_VAR_CHUNK_1": "us",
    }

    reconstruct_environment_variables(env=env)

    assert env == {
        "ARIA_TEST_ENV_VAR": "aria",
        "AXL_TEST_ENV_VAR": "axl is gray and puffy",
        "BLUPUS_TEST_ENV_VAR": "blupus",
    }


def test_split_too_large_env_var_fails():
    """Test that splitting and reconstructing too large an environment variable fails."""
    env = {
        "ARIA_TEST_ENV_VAR": "aria",
        "AXL_TEST_ENV_VAR": "axl is gray and puffy and wonderful",
    }

    with does_not_raise():
        split_environment_variables(env=env, size_limit=4)

    env = {
        "ARIA_TEST_ENV_VAR": "aria",
        "AXL_TEST_ENV_VAR": "axl is gray and puffy and wonderful and otherworldly",
    }

    with pytest.raises(RuntimeError):
        split_environment_variables(env=env, size_limit=4)
