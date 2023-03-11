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
import logging
from queue import Queue
from threading import Thread
from typing import Callable

import backoff
import monotonic

from zenml.analytics.request import APIError, post

try:
    from queue import Empty
except ImportError:
    from Queue import Empty

MAX_MSG_SIZE = 32 << 10

# Our servers only accept batches less than 500KB. Here limit is set slightly
# lower to leave space for extra data that will be added later, eg. "sentAt".
BATCH_SIZE_LIMIT = 475000

logger = logging.getLogger(__name__)


class Consumer(Thread):
    """Consumes the messages from the client's queue."""

    def __init__(
        self,
        queue: Queue,
        upload_size: int = 100,
        on_error: Callable = None,
        upload_interval: float = 0.5,
        retries: int = 10,
        timeout: int = 15,
    ) -> None:
        """Initialize and create a consumer thread.

        Args:
            queue: the list of message in the queue.
            upload_size: int, the maximum size for messages a consumer can send
                if the 'sync_mode' is set to False.
            on_error: function to call if an error occurs.
            upload_interval: float, the upload_interval in seconds
            retries: int, the number of max tries before failing.
            timeout: int, the timeout criteria in seconds.
        """
        Thread.__init__(self)
        # Make consumer a daemon thread so that it doesn't block program exit
        self.daemon = True
        self.upload_size = upload_size
        self.upload_interval = upload_interval
        self.on_error = on_error
        self.queue = queue
        # It's important to set running in the constructor: if we are asked to
        # pause immediately after construction, we might set running to True in
        # run() *after* we set it to False in pause... and keep running
        # forever.
        self.running = True
        self.retries = retries
        self.timeout = timeout

    def run(self):
        """Runs the consumer."""
        logger.debug("Consumer is running...")
        while self.running:
            self.upload()

        logger.debug("Consumer exited.")

    def pause(self):
        """Pause the consumer."""
        self.running = False

    def upload(self):
        """Upload the next batch of items, return whether successful."""
        success = False
        batch = self.next()
        if len(batch) == 0:
            return False

        try:
            self.request(batch)
            success = True
        except Exception as e:
            logger.error("error uploading: %s", e)
            success = False
            if self.on_error:
                self.on_error(e, batch)
        finally:
            # mark items as acknowledged from queue
            for _ in batch:
                self.queue.task_done()
            return success

    def next(self):
        """Return the next batch of items to upload."""
        queue = self.queue
        items = []

        start_time = monotonic.monotonic()
        total_size = 0

        while len(items) < self.upload_size:
            elapsed = monotonic.monotonic() - start_time
            if elapsed >= self.upload_interval:
                break
            try:
                item = queue.get(
                    block=True, timeout=self.upload_interval - elapsed
                )
                item_size = len(item.encode())

                if item_size > MAX_MSG_SIZE:
                    logger.error(
                        "Item exceeds 32kb limit, dropping. (%s)", str(item)
                    )
                    continue
                items.append(item)
                total_size += item_size
                if total_size >= BATCH_SIZE_LIMIT:
                    logger.debug("hit batch size limit (size: %d)", total_size)
                    break
            except Empty:
                break

        return items

    def request(self, batch):
        """Attempt to upload the batch and retry before raising an error."""

        def fatal_exception(exc):
            if isinstance(exc, APIError):
                # retry on server errors and client errors
                # with 429 status code (rate limited),
                # don't retry on other client errors
                return (400 <= exc.status < 500) and exc.status != 429
            else:
                # retry on all other errors (e.g. network)
                return False

        @backoff.on_exception(
            backoff.expo,
            Exception,
            max_tries=self.retries + 1,
            giveup=fatal_exception,
        )
        def send_request():
            """Function to send a batch of messages."""
            post(timeout=self.timeout, batch=batch)

        send_request()
