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
import logging

import requests

from zenml.constants import ANALYTICS_SERVER_URL

logger = logging.getLogger(__name__)


def post(batch, timeout=15):
    """Post the `kwargs` to the API"""
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
    }
    response = requests.post(
        url=ANALYTICS_SERVER_URL + "/batch",
        headers=headers,
        json=batch,
        timeout=timeout,
    )

    if response.status_code == 200:
        logger.debug("data uploaded successfully")
        return response

    try:
        payload = response.json()
        logger.debug("received response: %s", payload)
        raise APIError(
            response.status_code, payload["code"], payload["message"]
        )
    except ValueError:
        raise APIError(response.status_code, "unknown", response.text)


class APIError(Exception):
    def __init__(self, status, code, message):
        self.message = message
        self.status = status
        self.code = code

    def __str__(self):
        msg = "[ZenML Analytics] {0}: {1} ({2})"
        return msg.format(self.code, self.message, self.status)
