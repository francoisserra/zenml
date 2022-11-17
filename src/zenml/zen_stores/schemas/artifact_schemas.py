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

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlmodel import Field, SQLModel

from zenml.enums import ArtifactType
from zenml.models import ArtifactRequestModel, ArtifactResponseModel


class ArtifactSchema(SQLModel, table=True):
    """SQL Model for artifacts of steps."""

    id: UUID = Field(primary_key=True)
    name: str  # Name of the output in the parent step

    parent_step_id: UUID = Field(foreign_key="steprunschema.id")
    producer_step_id: UUID = Field(foreign_key="steprunschema.id")

    type: ArtifactType
    uri: str
    materializer: str
    data_type: str
    is_cached: bool

    mlmd_id: Optional[int] = Field(default=None, nullable=True)
    mlmd_parent_step_id: Optional[int] = Field(default=None, nullable=True)
    mlmd_producer_step_id: Optional[int] = Field(default=None, nullable=True)

    created: datetime = Field(default_factory=datetime.now)
    updated: datetime = Field(default_factory=datetime.now)

    @classmethod
    def from_request(cls, artifact_request: ArtifactRequestModel):
        return cls(
            name=artifact_request.name,
            parent_step_id=artifact_request.parent_step_id,
            producer_step_id=artifact_request.producer_step_id,
            type=artifact_request.type,
            uri=artifact_request.uri,
            materializer=artifact_request.materializer,
            data_type=artifact_request.data_type,
            is_cached=artifact_request.is_cached,
            mlmd_id=artifact_request.mlmd_id,
            mlmd_parent_step_id=artifact_request.mlmd_parent_step_id,
            mlmd_producer_step_id=artifact_request.mlmd_producer_step_id,
        )

    def to_model(self) -> ArtifactResponseModel:
        """Convert an `ArtifactSchema` to an `ArtifactModel`.

        Returns:
            The created `ArtifactModel`.
        """
        return ArtifactResponseModel(
            id=self.id,
            name=self.name,
            parent_step_id=self.parent_step_id,
            producer_step_id=self.producer_step_id,
            type=self.type,
            uri=self.uri,
            materializer=self.materializer,
            data_type=self.data_type,
            is_cached=self.is_cached,
            mlmd_id=self.mlmd_id,
            mlmd_parent_step_id=self.mlmd_parent_step_id,
            mlmd_producer_step_id=self.mlmd_producer_step_id,
            created=self.created,
            updated=self.updated,
        )