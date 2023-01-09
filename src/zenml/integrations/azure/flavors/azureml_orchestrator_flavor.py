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
"""AzureML orchestrator flavor."""

from typing import TYPE_CHECKING, Type

from zenml.config.base_settings import BaseSettings
from zenml.integrations.azure import AZUREML_ORCHESTRATOR_FLAVOR
from zenml.orchestrators import BaseOrchestratorConfig
from zenml.orchestrators.base_orchestrator import BaseOrchestratorFlavor

if TYPE_CHECKING:
    from zenml.integrations.azure.orchestrators import AzureOrchestrator


class AzureMLOrchestratorSettings(BaseSettings):
    """Settings for the AzureML orchestrator.

    Attributes:
        instance_type: The instance type to use for the processing job.
        processor_role: The IAM role to use for the step execution on a Processor.
        volume_size_in_gb: The size of the EBS volume to use for the processing
            job.
        max_runtime_in_seconds: The maximum runtime in seconds for the
            processing job.
        processor_tags: Tags to apply to the Processor assigned to the step.
    """

    # instance_type: str = "ml.t3.medium"
    # processor_role: Optional[str] = None
    # volume_size_in_gb: int = 30
    # max_runtime_in_seconds: int = 86400
    # processor_tags: Dict[str, str] = {}


class AzureMLOrchestratorConfig(  # type: ignore[misc] # https://github.com/pydantic/pydantic/issues/4173
    BaseOrchestratorConfig, AzureMLOrchestratorSettings
):
    """Config for the AzureML orchestrator.

    Attributes:
        synchronous: Whether to run the processing job synchronously or
            asynchronously. Defaults to False.
        execution_role: The IAM role to use for the pipeline.
        bucket: Name of the S3 bucket to use for storing artifacts
            from the job run. If not provided, a default bucket will be created
            based on the following format:
            "sagemaker-{region}-{aws-account-id}".
    """

    synchronous: bool = False
    # execution_role: str
    # bucket: Optional[str] = None

    @property
    def is_remote(self) -> bool:
        """Checks if this stack component is running remotely.

        This designation is used to determine if the stack component can be
        used with a local ZenML database or if it requires a remote ZenML
        server.

        Returns:
            True if this config is for a remote component, False otherwise.
        """
        return True


class AzureMLOrchestratorFlavor(BaseOrchestratorFlavor):
    """Flavor for the AzureML orchestrator."""

    @property
    def name(self) -> str:
        """Name of the flavor.

        Returns:
            The name of the flavor.
        """
        return AZUREML_ORCHESTRATOR_FLAVOR

    @property
    def config_class(self) -> Type[AzureMLOrchestratorConfig]:
        """Returns AzureMLOrchestratorConfig config class.

        Returns:
            The config class.
        """
        return AzureMLOrchestratorConfig

    @property
    def implementation_class(self) -> Type["AzureOrchestrator"]:
        """Implementation class.

        Returns:
            The implementation class.
        """
        from zenml.integrations.azure.orchestrators import AzureMLOrchestrator

        return AzureMLOrchestrator