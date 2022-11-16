#  Copyright (c) ZenML GmbH 2022. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at:
#
#       https://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
#  or implied. See the License for the specific language governing
#  permissions and limitations under the License.
import os
import shutil
import sys
from pathlib import Path
from typing import Generator, Tuple

import pytest
from py._builtin import execfile
from pytest_mock import MockerFixture

from tests.harness.environment import TestEnvironment
from tests.harness.utils import (
    check_test_requirements,
    clean_default_client_session,
    clean_project_session,
    environment_session,
)
from tests.venv_clone_utils import clone_virtualenv
from zenml.client import Client

DEFAULT_ENVIRONMENT_NAME = "default"


def pytest_addoption(parser):
    """Fixture that gets called by pytest ahead of tests. Adds the following cli
    options:

        --environment <environment_name>: Use a test environment with the
            given name to run tests against. If no environment is specified,
            each tests module will run in its own temporary local default
            environment.
        --no-teardown: Do not tear down the test environment after tests
            have run.

    How to use this option:

        ```pytest tests/integration --environment <environment_name>```
    """
    parser.addoption(
        "--environment",
        action="store",
        default=None,
        help="Environment to run tests against",
    )
    parser.addoption(
        "--deployment",
        action="store",
        default=None,
        help="Deployment to run tests against",
    )
    parser.addoption(
        "--requirements",
        action="store",
        default=None,
        help="Global test requirements to run tests against",
    )
    parser.addoption(
        "--no-teardown",
        action="store_true",
        default=False,
        help="Do not tear down the test environment after tests have run.",
    )
    parser.addoption(
        "--no-cleanup",
        action="store_true",
        default=False,
        help="Do not cleanup the temporary resources (e.g. stacks, projects) "
        "set up for tests after tests have run.",
    )
    parser.addoption(
        "--no-provision",
        action="store_true",
        default=False,
        help="Do not provision the test environment before running tests "
        "(assumes it is already provisioned).",
    )


@pytest.fixture(scope="session", autouse=True)
def auto_environment(
    session_mocker: MockerFixture,
    request: pytest.FixtureRequest,
) -> Generator[Tuple[TestEnvironment, Client], None, None]:
    """Fixture to automatically provision and use a test environment for all
    tests in a session.

    Yields:
        The active environment and a client connected with it.
    """

    session_mocker.patch("analytics.track")
    session_mocker.patch("analytics.group")
    session_mocker.patch("analytics.identify")

    environment_name = request.config.getoption("environment", None)
    no_provision = request.config.getoption("no_provision", False)
    no_teardown = request.config.getoption("no_teardown", False)
    no_cleanup = request.config.getoption("no_cleanup", False)

    # If no environment is specified, create an ad-hoc environment
    # consisting of the supplied deployment (or the default one) and
    # the supplied test requirements (if present).
    deployment_name = request.config.getoption(
        "deployment", DEFAULT_ENVIRONMENT_NAME
    )
    requirements_names = request.config.getoption("requirements")

    with environment_session(
        environment_name=environment_name,
        deployment_name=deployment_name,
        requirements_names=requirements_names.split(",")
        if requirements_names
        else [],
        no_provision=no_provision,
        no_teardown=no_teardown,
        no_deprovision=no_cleanup,
    ) as environment:
        yield environment


@pytest.fixture(scope="module", autouse=True)
def check_module_requirements(
    auto_environment: Tuple[TestEnvironment, Client],
    request: pytest.FixtureRequest,
) -> None:
    """Fixture to check test-level requirements for a test module.

    Yields:
        An active ZenML stack with the requirements of the test module.
    """
    env, client = auto_environment
    check_test_requirements(
        request=request,
        environment=env,
        client=client,
    )


@pytest.fixture
def clean_project(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[Client, None, None]:
    """Fixture to create, activate and use a separate ZenML project for an
    individual test.

    Yields:
        A ZenML client configured to use the project.
    """
    with clean_project_session(
        tmp_path_factory=tmp_path_factory,
        clean_repo=True,
    ) as client:
        yield client


@pytest.fixture(scope="module")
def module_clean_project(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[Client, None, None]:
    """Fixture to create, activate and use a separate ZenML
    project for an entire test module.

    Yields:
        A ZenML client configured to use the project.
    """
    with clean_project_session(
        tmp_path_factory=tmp_path_factory,
        clean_repo=True,
    ) as client:
        yield client


@pytest.fixture
def clean_client(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[Client, None, None]:
    """Fixture to get a clean local client with its own global configuration
    for an individual test.

    Args:
        request: Pytest FixtureRequest object
        tmp_path_factory: Pytest TempPathFactory in order to create a new
            temporary directory

    Yields:
        A clean ZenML client.
    """
    with clean_default_client_session(
        tmp_path_factory=tmp_path_factory,
    ) as client:
        yield client


@pytest.fixture(scope="module")
def module_clean_client(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[Client, None, None]:
    """Fixture to get and use a clean local client with its own
    global configuration for a test module.

    Args:
        request: Pytest FixtureRequest object
        tmp_path_factory: Pytest TempPathFactory in order to create a new
            temporary directory

    Yields:
        A clean ZenML client.
    """
    with clean_default_client_session(
        tmp_path_factory=tmp_path_factory,
    ) as client:
        yield client


@pytest.fixture
def files_dir(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    """Fixture that will search for a folder with the same name as the test
    file and move it into the temp path of the test.

    |dir
    |--test_functionality
    |--|--test_specific_method
    |--test_functionality.py#test_specific_method

    In this case if the `test_specific_method()` function inside the
    `test_functionality.py` has this fixture, the
    `test_functionality/test_specific_method` file is copied into the tmp_path.
    The path is passed into the test_specific_method(datadir: str) as string.

    TO use this, ensure the filename (minus '.py') corresponds to the outer
    directory name. And the inner directory corresponds to the test methods
    name.

    Returns:
        tmp_path at which to find the files.
    """
    filename = Path(request.module.__file__)
    test_dir = filename.with_suffix("")

    test_name = request.function.__name__

    tmp_path = tmp_path / test_name

    if os.path.isdir(test_dir):
        test_function_dir = test_dir / test_name
        if os.path.isdir(test_function_dir):
            shutil.copytree(test_function_dir, tmp_path)

    return tmp_path


@pytest.fixture
def virtualenv(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> str:
    """Based on the underlying virtual environment a copy of the environment is
    made and used for the test that uses this fixture.

    Args:
        request: Pytest FixtureRequest object used to create unique tmp dir
                 based on the name of the test
        tmp_path_factory: Pytest TempPathFactory in order to create a new
                          temporary directory

    Yields:
        Path to the virtual environment
    """
    if request.config.getoption("use_virtualenv"):
        # Remember the old executable
        orig_sys_executable = Path(sys.executable)

        test_name = request.node.name
        test_name = test_name.replace("[", "-").replace("]", "-")

        # Create temporary venv
        tmp_path = tmp_path_factory.mktemp(test_name) / "venv"
        # TODO[ENG-707]: Implement for use outside of a base virtual environment
        #  If this happens outside of a virtual environment the complete
        #  /usr space is cloned
        clone_virtualenv(
            src_dir=str(orig_sys_executable.parent.parent),
            dst_dir=str(tmp_path),
        )

        env_bin_dir = "bin"
        if sys.platform == "win32":
            env_bin_dir = "Scripts"

        # Activate venv
        activate_this_file = tmp_path / env_bin_dir / "activate_this.py"

        if not activate_this_file.is_file():
            raise FileNotFoundError(
                "Integration tests don't work for some local "
                "virtual environments. Use virtualenv for "
                "your virtual environment to run integration "
                "tests"
            )

        execfile(
            str(activate_this_file), dict(__file__=str(activate_this_file))
        )

        # Set new system executable
        sys.executable = tmp_path / env_bin_dir / "python"

        yield tmp_path
        # Reset system executable
        sys.executable = orig_sys_executable

        # Switch back to original venv
        activate_this_f = Path(orig_sys_executable).parent / "activate_this.py"

        if not activate_this_f.is_file():
            raise FileNotFoundError(
                "Integration tests don't work for some local "
                "virtual environments. Use virtualenv for "
                "your virtual environment to run integration "
                "tests"
            )
        execfile(str(activate_this_f), dict(__file__=str(activate_this_f)))

    else:
        yield ""
