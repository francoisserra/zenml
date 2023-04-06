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
from types import FunctionType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Optional,
    Type,
    TypeVar,
    Union,
    overload,
)

from zenml.pipelines.new.pipeline_template import (
    CLASS_CONFIGURATION,
    PARAM_ENABLE_ARTIFACT_METADATA,
    PARAM_ENABLE_CACHE,
    PARAM_EXTRA_OPTIONS,
    PARAM_ON_FAILURE,
    PARAM_ON_SUCCESS,
    PARAM_PIPELINE_NAME,
    PARAM_SETTINGS,
    PIPELINE_INNER_FUNC_NAME,
    PipelineTemplate,
)

if TYPE_CHECKING:
    from zenml.config.base_settings import SettingsOrDict

    HookSpecification = Union[str, FunctionType]

F = TypeVar("F", bound=Callable[..., None])


@overload
def pipeline_template(_func: F) -> Type[PipelineTemplate]:
    ...


@overload
def pipeline_template(
    *,
    name: Optional[str] = None,
    enable_cache: Optional[bool] = None,
    enable_artifact_metadata: Optional[bool] = None,
    settings: Optional[Dict[str, "SettingsOrDict"]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Callable[[F], Type[PipelineTemplate]]:
    ...


def pipeline_template(
    _func: Optional[F] = None,
    *,
    name: Optional[str] = None,
    enable_cache: Optional[bool] = None,
    enable_artifact_metadata: Optional[bool] = None,
    settings: Optional[Dict[str, "SettingsOrDict"]] = None,
    extra: Optional[Dict[str, Any]] = None,
    on_failure: Optional["HookSpecification"] = None,
    on_success: Optional["HookSpecification"] = None,
) -> Union[Type[PipelineTemplate], Callable[[F], Type[PipelineTemplate]]]:
    """Outer decorator function for the creation of a ZenML pipeline.

    In order to be able to work with parameters such as "name", it features a
    nested decorator structure.

    Args:
        _func: The decorated function.
        name: The name of the pipeline. If left empty, the name of the
            decorated function will be used as a fallback.
        enable_cache: Whether to use caching or not.
        enable_artifact_metadata: Whether to enable artifact metadata or not.
        settings: Settings for this pipeline.
        extra: Extra configurations for this pipeline.
        on_failure: Callback function in event of failure of the step. Can be
            a function with three possible parameters,
            `StepContext`, `BaseParameters`, and `BaseException`,
            or a source path to a function of the same specifications
            (e.g. `module.my_function`).
        on_success: Callback function in event of failure of the step. Can be
            a function with two possible parameters, `StepContext` and
            `BaseParameters, or a source path to a function of the same specifications
            (e.g. `module.my_function`).

    Returns:
        the inner decorator which creates the pipeline class based on the
        ZenML BasePipeline
    """

    def inner_decorator(func: F) -> Type[PipelineTemplate]:
        """Inner decorator function for the creation of a ZenML pipeline.

        Args:
            func: types.FunctionType, this function will be used as the
                "connect" method of the generated Pipeline

        Returns:
            the class of a newly generated ZenML Pipeline
        """
        return type(
            func.__name__,
            (PipelineTemplate,),
            {
                PIPELINE_INNER_FUNC_NAME: staticmethod(func),  # type: ignore[arg-type]
                CLASS_CONFIGURATION: {
                    PARAM_PIPELINE_NAME: name,
                    PARAM_ENABLE_CACHE: enable_cache,
                    PARAM_ENABLE_ARTIFACT_METADATA: enable_artifact_metadata,
                    PARAM_SETTINGS: settings,
                    PARAM_EXTRA_OPTIONS: extra,
                    PARAM_ON_FAILURE: on_failure,
                    PARAM_ON_SUCCESS: on_success,
                },
                "__module__": func.__module__,
                "__doc__": func.__doc__,
            },
        )

    if _func is None:
        return inner_decorator
    else:
        return inner_decorator(_func)