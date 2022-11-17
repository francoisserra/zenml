from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from zenml.enums import ExecutionStatus
from zenml.models.base_models import (
    ProjectScopedRequestModel,
    ProjectScopedResponseModel,
    update,
)
from zenml.models.constants import MODEL_NAME_FIELD_MAX_LENGTH

# ---- #
# BASE #
# ---- #


class StepRunBaseModel(BaseModel):
    name: str = Field(
        title="The name of the pipeline run step.",
        max_length=MODEL_NAME_FIELD_MAX_LENGTH,
    )
    pipeline_run_id: UUID
    parent_step_ids: List[UUID]
    input_artifacts: Dict[str, UUID]
    status: ExecutionStatus

    entrypoint_name: str
    parameters: Dict[str, str]
    step_configuration: Dict[str, Any]
    docstring: str
    num_outputs: Optional[int]

    # IDs in MLMD - needed for some metadata store methods
    mlmd_id: int
    mlmd_parent_step_ids: List[int]


# -------- #
# RESPONSE #
# -------- #


class StepRunResponseModel(StepRunBaseModel, ProjectScopedResponseModel):
    """Domain Model representing a step in a pipeline run."""


# ------- #
# REQUEST #
# ------- #


class StepRunRequestModel(StepRunBaseModel, ProjectScopedRequestModel):
    """Domain Model representing a step in a pipeline run."""


# ------ #
# UPDATE #
# ------ #
@update
class StepRunUpdateModel(StepRunRequestModel):
    """"""
