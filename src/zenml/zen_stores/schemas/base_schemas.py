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
from uuid import UUID, uuid4

from sqlalchemy import Column, ForeignKey
from sqlmodel import Field, SQLModel


class BaseSchema(SQLModel, table=False):
    """Base SQL Model for ZenML entities."""

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created: datetime = Field(default_factory=datetime.now)
    updated: datetime = Field(default_factory=datetime.now)


class UserOwnedSchema(BaseSchema, table=False):
    """Base user-owned SQL model."""

    user_id: UUID = Field(
        sa_column=Column(ForeignKey("userschema.id", ondelete="SET NULL"))
    )


class ProjectScopedSchema(UserOwnedSchema, table=False):
    """Base project-scoped SQL Model."""

    project_id: UUID = Field(
        sa_column=Column(ForeignKey("projectschema.id", ondelete="CASCADE"))
    )


class ShareableSchema(ProjectScopedSchema, table=False):
    """Base shareable SQL Model."""

    is_shared: bool