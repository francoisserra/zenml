#  Copyright (c) ZenML GmbH 2021. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at:
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
#  or implied. See the License for the specific language governing
#  permissions and limitations under the License.

import numpy as np
import tensorflow as tf

from zenml.pipelines import pipeline
from zenml.steps import step
from zenml.steps.step_output import Output
from zenml.core.repo import Repository


@step
def importer_mnist() -> Output(
    X_train=np.ndarray, y_train=np.ndarray, X_test=np.ndarray, y_test=np.ndarray
):
    """Download the MNIST data and store it as an artifact"""
    (X_train, y_train), (
        X_test,
        y_test,
    ) = tf.keras.datasets.mnist.load_data()
    return X_train, y_train, X_test, y_test


@pipeline
def load_mnist_pipeline(
    importer,
):
    """The simplest possible pipeline"""
    # We just need to call the function
    importer()


# Run the pipeline
load_mnist_pipeline(importer=importer_mnist()).run()


# Post-execution
repo = Repository()
p = repo.get_pipeline(pipeline_name="load_mnist_pipeline")
runs = p.get_runs()
print(f"Pipeline `load_mnist_pipeline` has {len(runs)} run(s)")
run = runs[0]
print(f"The first run has {len(run.steps)} step(s).")
step = run.steps[0]
print(f"That step has {len(step.outputs)} output artifacts.")
for i, o in enumerate(step.outputs):
    arr = o.read(None)
    print(f"Output {i} is an array with shape: {arr.shape}")
