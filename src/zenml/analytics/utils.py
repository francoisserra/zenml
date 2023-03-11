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
"""The 'analytics' module of ZenML.

This module is based on the 'analytics-python' package created by Segment.
The base functionalities are adapted to work with the ZenML analytics server.
"""

import json
import logging
from uuid import UUID

logger = logging.getLogger(__name__)


class AnalyticsEncoder(json.JSONEncoder):
    """Helper encoder class for JSON serialization."""

    def default(self, obj):
        """The default method to handle UUID and 'AnalyticsEvent' objects."""
        from zenml.utils.analytics_utils import AnalyticsEvent

        # If the object is UUID, we simply return the value of UUID
        if isinstance(obj, UUID):
            return str(obj)

        # If the object is an AnalyticsEvent, return its value
        elif isinstance(obj, AnalyticsEvent):
            return str(obj.value)

        return json.JSONEncoder.default(self, obj)
