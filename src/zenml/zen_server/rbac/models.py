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
"""RBAC model classes."""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from zenml.utils.enum_utils import StrEnum


class Action(StrEnum):
    """RBAC actions."""

    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    READ_SECRET_VALUE = "read_secret_value"
    PRUNE = "prune"

    # Service connectors
    CLIENT = "client"

    # Models
    PROMOTE = "promote"

    # Secrets
    BACKUP_RESTORE = "backup_restore"

    SHARE = "share"


class ResourceType(StrEnum):
    """Resource types of the server API."""

    STACK = "stack"
    FLAVOR = "flavor"
    STACK_COMPONENT = "stack_component"
    PIPELINE = "pipeline"
    CODE_REPOSITORY = "code_repository"
    MODEL = "model"
    MODEL_VERSION = "model_version"
    SERVICE_CONNECTOR = "service_connector"
    ARTIFACT = "artifact"
    ARTIFACT_VERSION = "artifact_version"
    SECRET = "secret"
    TAG = "tag"
    SERVICE_ACCOUNT = "service_account"
    WORKSPACE = "workspace"
    PIPELINE_RUN = "pipeline_run"
    PIPELINE_DEPLOYMENT = "pipeline_deployment"
    PIPELINE_BUILD = "pipeline_build"
    RUN_METADATA = "run_metadata"
    USER = "user"


class Resource(BaseModel):
    """RBAC resource model."""

    type: str
    id: Optional[UUID] = None

    def __str__(self) -> str:
        """Convert to a string.

        Returns:
            Resource string representation.
        """
        representation = self.type
        if self.id:
            representation += f"/{self.id}"

        return representation

    class Config:
        """Pydantic configuration class."""

        frozen = True
