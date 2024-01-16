#  Copyright (c) ZenML GmbH 2023. All Rights Reserved.
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

from typing import Any, ClassVar, Optional
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from zenml.artifacts.external_artifact import ExternalArtifact

GLOBAL_ARTIFACT_VERSION_ID = uuid4()


class MockZenmlClient:
    class Client:
        ARTIFACT_STORE_ID: ClassVar[int] = 42

        class MockArtifactVersionResponse:
            def __init__(self, name, id=GLOBAL_ARTIFACT_VERSION_ID):
                self.artifact_store_id = 42
                self.name = name
                self.id = id

        class MockPipelineRunResponse:
            def __init__(self):
                self.name = "foo"
                self.artifact_versions = [
                    MockZenmlClient.Client.MockArtifactVersionResponse("foo"),
                    MockZenmlClient.Client.MockArtifactVersionResponse("bar"),
                ]

        class MockPipelineResponse:
            def __init__(self):
                self.last_successful_run = (
                    MockZenmlClient.Client.MockPipelineRunResponse()
                )

        def __init__(self):
            self.active_stack = MagicMock()
            self.active_stack.artifact_store.id = self.ARTIFACT_STORE_ID
            self.active_stack.artifact_store.path = "foo"

        def get_artifact_version(self, *args, **kwargs):
            if len(args):
                return MockZenmlClient.Client.MockArtifactVersionResponse(
                    "foo", args[0]
                )
            else:
                return MockZenmlClient.Client.MockArtifactVersionResponse(
                    "foo"
                )

        def get_pipeline(self, *args, **kwargs):
            return MockZenmlClient.Client.MockPipelineResponse()

        def get_pipeline_run(self, *args, **kwargs):
            return MockZenmlClient.Client.MockPipelineRunResponse()


@pytest.mark.parametrize(
    argnames="value,id,artifact_name,exception_start",
    argvalues=[
        [1, None, None, None],
        [None, uuid4(), None, None],
        [None, None, "name", None],
        [None, None, None, "Either `value`, `id`, or `name` must be provided"],
        [1, uuid4(), None, "Only one of `value`, `id`, or `name`"],
        [None, uuid4(), "name", "Only one of `value`, `id`, or `name`"],
        [1, None, "name", "Only one of `value`, `id`, or `name`"],
    ],
    ids=[
        "good_by_value",
        "good_by_id",
        "good_by_name",
        "bad_all_none",
        "bad_id_and_value",
        "bad_id_and_name",
        "bad_value_and_name",
    ],
)
def test_external_artifact_init(
    value: Optional[Any],
    id: Optional[UUID],
    artifact_name: Optional[str],
    exception_start: Optional[str],
):
    """Tests that initialization logic of `ExternalArtifact` works expectedly."""
    if exception_start:
        with pytest.raises(ValueError, match=exception_start):
            ExternalArtifact(
                value=value,
                id=id,
                name=artifact_name,
            )
    else:
        ExternalArtifact(
            value=value,
            id=id,
            name=artifact_name,
        )


def test_upload_by_value(sample_artifact_version_model, mocker):
    """Tests that `upload_by_value` works as expected for `value`."""
    ea = ExternalArtifact(value=1)
    assert ea.id is None
    mocker.patch(
        "zenml.artifacts.utils.save_artifact",
        return_value=sample_artifact_version_model,
    )
    ea.upload_by_value()
    assert ea.id is not None
    assert ea.value is None
    assert ea.name is None


def test_get_artifact_by_value_before_upload_raises():
    """Tests that `get_artifact` raises if called without `upload_by_value` for `value`."""
    ea = ExternalArtifact(value=1)
    assert ea.id is None
    with pytest.raises(RuntimeError):
        with patch.dict(
            "sys.modules",
            {
                "zenml.artifacts.utils": MagicMock(),
                "zenml.client": MockZenmlClient,
            },
        ):
            ea.get_artifact_version_id()


def test_get_artifact_by_id():
    """Tests that `get_artifact` works as expected for `id`."""
    ea = ExternalArtifact(id=GLOBAL_ARTIFACT_VERSION_ID)
    assert ea.value is None
    assert ea.name is None
    assert ea.id is not None
    with patch.dict(
        "sys.modules",
        {
            "zenml.artifacts.utils": MagicMock(),
            "zenml.client": MockZenmlClient,
        },
    ):
        assert ea.get_artifact_version_id() == GLOBAL_ARTIFACT_VERSION_ID


def test_get_artifact_by_pipeline_and_artifact_other_artifact_store():
    """Tests that `get_artifact` raises in case of mismatch between artifact stores (found vs active)."""
    with pytest.raises(
        RuntimeError,
        match=r"The artifact .* is not stored in the artifact store",
    ):
        try:
            old_id = MockZenmlClient.Client.ARTIFACT_STORE_ID
            MockZenmlClient.Client.ARTIFACT_STORE_ID = 45
            with patch.dict(
                "sys.modules",
                {
                    "zenml.artifacts.utils": MagicMock(),
                    "zenml.client": MockZenmlClient,
                },
            ):
                ExternalArtifact(name="bar").get_artifact_version_id()
        finally:
            MockZenmlClient.Client.ARTIFACT_STORE_ID = old_id
