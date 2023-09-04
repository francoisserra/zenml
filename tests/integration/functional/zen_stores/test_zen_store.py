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
import os
import uuid
from contextlib import ExitStack as does_not_raise
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pytest
from pydantic import SecretStr

from tests.integration.functional.utils import sample_name
from tests.integration.functional.zen_stores.utils import (
    CodeRepositoryContext,
    ComponentContext,
    CrudTestConfig,
    PipelineRunContext,
    RoleContext,
    ServiceConnectorContext,
    ServiceConnectorTypeContext,
    StackContext,
    TeamContext,
    UserContext,
    list_of_entities,
)
from tests.unit.pipelines.test_build_utils import (
    StubLocalRepositoryContext,
)
from zenml.client import Client
from zenml.enums import SecretScope, StackComponentType, StoreType
from zenml.exceptions import (
    DoesNotExistException,
    EntityExistsError,
    IllegalOperationError,
    StackExistsError,
)
from zenml.logging.step_logging import prepare_logs_uri
from zenml.models import (
    ArtifactFilterModel,
    ComponentFilterModel,
    ComponentUpdateModel,
    PipelineRunFilterModel,
    RoleFilterModel,
    RoleRequestModel,
    RoleUpdateModel,
    ServiceConnectorFilterModel,
    ServiceConnectorUpdateModel,
    StackFilterModel,
    StackRequestModel,
    StackUpdateModel,
    StepRunFilterModel,
    TeamRoleAssignmentRequestModel,
    TeamUpdateModel,
    UserRoleAssignmentRequestModel,
    UserUpdateModel,
    WorkspaceFilterModel,
    WorkspaceUpdateModel,
)
from zenml.models.base_models import (
    WorkspaceScopedRequestModel,
)
from zenml.models.flavor_models import FlavorBaseModel
from zenml.utils import code_repository_utils, source_utils
from zenml.utils.artifact_utils import (
    _load_artifact_store,
    _load_file_from_artifact_store,
)
from zenml.zen_stores.base_zen_store import (
    DEFAULT_ADMIN_ROLE,
    DEFAULT_GUEST_ROLE,
    DEFAULT_STACK_NAME,
    DEFAULT_USERNAME,
    DEFAULT_WORKSPACE_NAME,
)
from zenml.zen_stores.sql_zen_store import SqlZenStore

DEFAULT_NAME = "default"

# .--------------.
# | GENERIC CRUD |
# '--------------'


@pytest.mark.parametrize(
    "crud_test_config",
    list_of_entities,
    ids=[e.entity_name for e in list_of_entities],
)
def test_basic_crud_for_entity(crud_test_config: CrudTestConfig):
    """Tests the basic crud operations for a given entity."""
    client = Client()

    # Create the entity
    create_model = crud_test_config.create_model
    if "user" in create_model.__fields__:
        create_model.user = client.active_user.id
    if "workspace" in create_model.__fields__:
        create_model.workspace = client.active_workspace.id
    if "stack" in create_model.__fields__:
        create_model.stack = client.active_stack_model.id

    # Test the creation
    created_entity = crud_test_config.create_method(create_model)

    if hasattr(created_entity, "name"):
        # Filter by name to verify the entity was actually created
        entities_list = crud_test_config.list_method(
            crud_test_config.filter_model(name=create_model.name)
        )
        assert entities_list.total == 1

    # Filter by id to verify the entity was actually created
    entities_list = crud_test_config.list_method(
        crud_test_config.filter_model(id=created_entity.id)
    )
    assert entities_list.total == 1
    # Test the get method
    with does_not_raise():
        returned_entity_by_id = crud_test_config.get_method(created_entity.id)
    assert returned_entity_by_id == created_entity
    if crud_test_config.update_model:
        # Update the created entity
        update_model = crud_test_config.update_model
        with does_not_raise():
            updated_entity = crud_test_config.update_method(
                created_entity.id, update_model
            )
        # Ids should remain the same
        assert updated_entity.id == created_entity.id
        # Something in the Model should have changed
        assert updated_entity.json() != created_entity.json()

    # Cleanup
    with does_not_raise():
        crud_test_config.delete_method(created_entity.id)
    # Filter by id to verify the entity was actually deleted
    with pytest.raises(KeyError):
        crud_test_config.get_method(created_entity.id)
    # Filter by id to verify the entity was actually deleted
    entities_list = crud_test_config.list_method(
        crud_test_config.filter_model(id=created_entity.id)
    )
    assert entities_list.total == 0


@pytest.mark.parametrize(
    "crud_test_config",
    list_of_entities,
    ids=[e.entity_name for e in list_of_entities],
)
def test_create_entity_twice_fails(crud_test_config: CrudTestConfig):
    """Tests getting a non-existent entity by id."""
    if crud_test_config.entity_name in {"artifact", "build", "deployment"}:
        pytest.skip(
            f"Duplicates of {crud_test_config.entity_name} are allowed."
        )

    client = Client()
    # Create the entity
    create_model = crud_test_config.create_model
    if isinstance(create_model, WorkspaceScopedRequestModel) or isinstance(
        create_model, FlavorBaseModel
    ):
        create_model.user = client.active_user.id
        create_model.workspace = client.active_workspace.id
    # First creation is successful
    created_entity = crud_test_config.create_method(
        crud_test_config.create_model
    )
    # Second one fails
    with pytest.raises(EntityExistsError):
        crud_test_config.create_method(crud_test_config.create_model)
    # Cleanup
    with does_not_raise():
        crud_test_config.delete_method(created_entity.id)
    # Filter by id to verify the entity was actually deleted
    with pytest.raises(KeyError):
        crud_test_config.get_method(created_entity.id)


@pytest.mark.parametrize(
    "crud_test_config",
    list_of_entities,
    ids=[e.entity_name for e in list_of_entities],
)
def test_get_nonexistent_entity_fails(crud_test_config: CrudTestConfig):
    """Tests getting a non-existent entity by id."""
    with pytest.raises(KeyError):
        crud_test_config.get_method(uuid.uuid4())


@pytest.mark.parametrize(
    "crud_test_config",
    list_of_entities,
    ids=[e.entity_name for e in list_of_entities],
)
def test_updating_nonexisting_entity_raises_error(
    crud_test_config: CrudTestConfig,
):
    """Tests updating a nonexistent entity raises an error."""
    if crud_test_config.update_model:
        # Update the created entity
        update_model = crud_test_config.update_model
        with pytest.raises(KeyError):
            crud_test_config.update_method(uuid.uuid4(), update_model)
    else:
        pytest.skip(
            "For entities that do not support updates, this test is not run."
        )


@pytest.mark.parametrize(
    "crud_test_config",
    list_of_entities,
    ids=[e.entity_name for e in list_of_entities],
)
def test_deleting_nonexistent_entity_raises_error(
    crud_test_config: CrudTestConfig,
):
    """Tests deleting a nonexistent workspace raises an error."""
    with pytest.raises(KeyError):
        crud_test_config.delete_method(uuid.uuid4())


# .----------.
# | WORKSPACES |
# '----------'


def test_only_one_default_workspace_present():
    """Tests that one and only one default workspace is present."""
    client = Client()
    assert (
        len(
            client.zen_store.list_workspaces(
                WorkspaceFilterModel(name="default")
            )
        )
        == 1
    )


def test_updating_default_workspace_fails():
    """Tests updating the default workspace."""
    client = Client()

    default_workspace = client.zen_store.get_workspace(DEFAULT_WORKSPACE_NAME)
    assert default_workspace.name == DEFAULT_WORKSPACE_NAME
    workspace_update = WorkspaceUpdateModel(
        name="aria_workspace",
        description="Aria has taken possession of this workspace.",
    )
    with pytest.raises(IllegalOperationError):
        client.zen_store.update_workspace(
            workspace_id=default_workspace.id,
            workspace_update=workspace_update,
        )


def test_deleting_default_workspace_fails():
    """Tests deleting the default workspace."""
    client = Client()
    with pytest.raises(IllegalOperationError):
        client.zen_store.delete_workspace(DEFAULT_NAME)


# .-------.
# | TEAMS |
# '-------'


def test_adding_user_to_team():
    """Tests adding a user to a team."""
    zen_store = Client().zen_store
    with UserContext() as created_user:
        with TeamContext() as created_team:
            team_update = TeamUpdateModel(users=[created_user.id])
            team_update = zen_store.update_team(
                team_id=created_team.id, team_update=team_update
            )

            assert created_user.id in team_update.user_ids
            assert len(team_update.users) == 1

            # Make sure the team name has not been inadvertently changed
            assert (
                zen_store.get_team(created_team.id).name == created_team.name
            )


def test_adding_nonexistent_user_to_real_team_raises_error():
    """Tests adding a nonexistent user to a team raises an error."""
    zen_store = Client().zen_store
    with TeamContext() as created_team:
        nonexistent_id = uuid.uuid4()

        team_update = TeamUpdateModel(users=[nonexistent_id])
        with pytest.raises(KeyError):
            zen_store.update_team(
                team_id=created_team.id, team_update=team_update
            )


def test_removing_user_from_team_succeeds():
    """Tests removing a user from a team."""

    zen_store = Client().zen_store
    sample_name("arias_team")

    with UserContext() as created_user:
        with TeamContext() as created_team:
            team_update = TeamUpdateModel(users=[created_user.id])
            team_update = zen_store.update_team(
                team_id=created_team.id, team_update=team_update
            )

            assert created_user.id in team_update.user_ids

            team_update = TeamUpdateModel(users=[])
            team_update = zen_store.update_team(
                team_id=created_team.id, team_update=team_update
            )

            assert created_user.id not in team_update.user_ids


def test_access_user_in_team_succeeds():
    """Tests accessing a users in a team."""

    zen_store = Client().zen_store
    sample_name("arias_team")

    with UserContext() as created_user:
        with TeamContext() as created_team:
            team_update = TeamUpdateModel(users=[created_user.id])
            team_update = zen_store.update_team(
                team_id=created_team.id, team_update=team_update
            )
            assert created_user in team_update.users


#  .------.
# | USERS |
# '-------'


def test_active_user():
    """Tests the active user can be queried with .get_user()."""
    zen_store = Client().zen_store
    active_user = zen_store.get_user()
    assert active_user is not None
    # The SQL zen_store only supports the default user as active user
    if zen_store.type == StoreType.SQL:
        assert active_user.name == DEFAULT_USERNAME
    else:
        # TODO: Implement this
        assert True


def test_updating_default_user_fails():
    """Tests that updating the default user is prohibited."""
    client = Client()
    default_user = client.zen_store.get_user(DEFAULT_USERNAME)
    assert default_user
    user_update = UserUpdateModel(name="axl")
    with pytest.raises(IllegalOperationError):
        client.zen_store.update_user(
            user_id=default_user.id, user_update=user_update
        )


def test_deleting_default_user_fails():
    """Tests that deleting the default user is prohibited."""
    zen_store = Client().zen_store
    with pytest.raises(IllegalOperationError):
        zen_store.delete_user("default")


def test_getting_team_for_user_succeeds():
    pass


def test_team_for_user_succeeds():
    """Tests accessing a users in a team."""

    zen_store = Client().zen_store
    sample_name("arias_team")

    with UserContext() as created_user:
        with TeamContext() as created_team:
            team_update = TeamUpdateModel(users=[created_user.id])
            team_update = zen_store.update_team(
                team_id=created_team.id, team_update=team_update
            )

            updated_user_response = zen_store.get_user(created_user.id)

            assert team_update in updated_user_response.teams


# .-------.
# | ROLES |
# '-------'


def test_creating_role_with_empty_permissions_succeeds():
    """Tests creating a role."""
    zen_store = Client().zen_store

    with RoleContext() as created_role:
        new_role = RoleRequestModel(name=sample_name("cat"), permissions=set())
        created_role = zen_store.create_role(new_role)
        with does_not_raise():
            zen_store.get_role(role_name_or_id=created_role.name)
        list_of_roles = zen_store.list_roles(
            RoleFilterModel(name=created_role.name)
        )
        assert list_of_roles.total > 0


def test_deleting_builtin_role_fails():
    """Tests deleting a built-in role fails."""
    zen_store = Client().zen_store

    with pytest.raises(IllegalOperationError):
        zen_store.delete_role(DEFAULT_ADMIN_ROLE)

    with pytest.raises(IllegalOperationError):
        zen_store.delete_role(DEFAULT_GUEST_ROLE)


def test_updating_builtin_role_fails():
    """Tests updating a built-in role fails."""
    zen_store = Client().zen_store

    role = zen_store.get_role(DEFAULT_ADMIN_ROLE)
    role_update = RoleUpdateModel(name="cat_feeder")

    with pytest.raises(IllegalOperationError):
        zen_store.update_role(role_id=role.id, role_update=role_update)

    role = zen_store.get_role(DEFAULT_GUEST_ROLE)
    with pytest.raises(IllegalOperationError):
        zen_store.update_role(role_id=role.id, role_update=role_update)


def test_deleting_assigned_role_fails():
    """Tests assigning a role to a user."""
    zen_store = Client().zen_store
    with RoleContext() as created_role:
        with UserContext() as created_user:
            role_assignment = UserRoleAssignmentRequestModel(
                role=created_role.id,
                user=created_user.id,
                workspace=None,
            )
            with does_not_raise():
                (zen_store.create_user_role_assignment(role_assignment))
            with pytest.raises(IllegalOperationError):
                zen_store.delete_role(created_role.id)


# .------------------.
# | ROLE ASSIGNMENTS |
# '------------------'


def test_assigning_role_to_user_succeeds():
    """Tests assigning a role to a user."""
    zen_store = Client().zen_store

    with RoleContext() as created_role:
        with UserContext() as created_user:
            role_assignment = UserRoleAssignmentRequestModel(
                role=created_role.id,
                user=created_user.id,
                workspace=None,
            )
            with does_not_raise():
                assignment = zen_store.create_user_role_assignment(
                    role_assignment
                )

    # With user and role deleted the assignment should be deleted as well
    with pytest.raises(KeyError):
        zen_store.delete_user_role_assignment(assignment.id)


def test_assigning_role_to_team_succeeds():
    """Tests assigning a role to a user."""
    zen_store = Client().zen_store

    with RoleContext() as created_role:
        with TeamContext() as created_team:
            role_assignment = TeamRoleAssignmentRequestModel(
                role=created_role.id,
                team=created_team.id,
                workspace=None,
            )
            with does_not_raise():
                assignment = zen_store.create_team_role_assignment(
                    role_assignment
                )
    # With user and role deleted the assignment should be deleted as well
    with pytest.raises(KeyError):
        zen_store.get_team_role_assignment(assignment.id)


def test_assigning_role_if_assignment_already_exists_fails():
    """Tests assigning a role to a user if the assignment already exists."""
    zen_store = Client().zen_store

    with RoleContext() as created_role:
        with UserContext() as created_user:
            role_assignment = UserRoleAssignmentRequestModel(
                role=created_role.id,
                user=created_user.id,
                workspace=None,
            )
            with does_not_raise():
                (zen_store.create_user_role_assignment(role_assignment))
            with pytest.raises(EntityExistsError):
                (zen_store.create_user_role_assignment(role_assignment))


def test_revoking_role_for_user_succeeds():
    """Tests revoking a role for a user."""
    zen_store = Client().zen_store

    with RoleContext() as created_role:
        with UserContext() as created_user:
            role_assignment = UserRoleAssignmentRequestModel(
                role=created_role.id,
                user=created_user.id,
                workspace=None,
            )
            with does_not_raise():
                role_assignment = zen_store.create_user_role_assignment(
                    role_assignment
                )
                zen_store.delete_user_role_assignment(
                    user_role_assignment_id=role_assignment.id
                )
            with pytest.raises(KeyError):
                zen_store.get_user_role_assignment(
                    user_role_assignment_id=role_assignment.id
                )


def test_revoking_role_for_team_succeeds():
    """Tests revoking a role for a team."""
    zen_store = Client().zen_store

    with RoleContext() as created_role:
        with TeamContext() as created_team:
            role_assignment = TeamRoleAssignmentRequestModel(
                role=created_role.id,
                team=created_team.id,
                workspace=None,
            )
            with does_not_raise():
                role_assignment = zen_store.create_team_role_assignment(
                    role_assignment
                )
                zen_store.delete_team_role_assignment(
                    team_role_assignment_id=role_assignment.id
                )
            with pytest.raises(KeyError):
                zen_store.get_team_role_assignment(
                    team_role_assignment_id=role_assignment.id
                )


def test_revoking_nonexistent_role_fails():
    """Tests revoking a nonexistent role fails."""
    zen_store = Client().zen_store
    with pytest.raises(KeyError):
        zen_store.delete_team_role_assignment(
            team_role_assignment_id=uuid.uuid4()
        )
    with pytest.raises(KeyError):
        zen_store.delete_user_role_assignment(
            user_role_assignment_id=uuid.uuid4()
        )


# .------------------.
# | Stack components |
# '------------------'

# TODO: tests regarding sharing of components missing


def test_update_default_stack_component_fails():
    """Tests that updating default stack components fails."""
    client = Client()
    store = client.zen_store
    default_artifact_store = store.list_stack_components(
        ComponentFilterModel(
            workspace_id=client.active_workspace.id,
            type=StackComponentType.ARTIFACT_STORE,
            name="default",
        )
    )[0]

    default_orchestrator = store.list_stack_components(
        ComponentFilterModel(
            workspace_id=client.active_workspace.id,
            type=StackComponentType.ORCHESTRATOR,
            name="default",
        )
    )[0]

    component_update = ComponentUpdateModel(name="aria")
    with pytest.raises(IllegalOperationError):
        store.update_stack_component(
            component_id=default_orchestrator.id,
            component_update=component_update,
        )

    default_orchestrator.name = "axl"
    with pytest.raises(IllegalOperationError):
        store.update_stack_component(
            component_id=default_artifact_store.id,
            component_update=component_update,
        )


def test_delete_default_stack_component_fails():
    """Tests that deleting default stack components is prohibited."""
    client = Client()
    store = client.zen_store
    default_artifact_store = store.list_stack_components(
        ComponentFilterModel(
            workspace_id=client.active_workspace.id,
            type=StackComponentType.ARTIFACT_STORE,
            name="default",
        )
    )[0]

    default_orchestrator = store.list_stack_components(
        ComponentFilterModel(
            workspace_id=client.active_workspace.id,
            type=StackComponentType.ORCHESTRATOR,
            name="default",
        )
    )[0]

    with pytest.raises(IllegalOperationError):
        store.delete_stack_component(default_artifact_store.id)

    with pytest.raises(IllegalOperationError):
        store.delete_stack_component(default_orchestrator.id)


def test_count_stack_components():
    """Tests that the count stack_component command returns the correct amount."""
    client = Client()
    store = client.zen_store
    if not isinstance(store, SqlZenStore):
        pytest.skip("Test only applies to SQL store")
    active_workspace = client.active_workspace

    count_before = store.list_stack_components(
        ComponentFilterModel(scope_workspace=active_workspace.id)
    ).total

    assert (
        store.count_stack_components(workspace_id=active_workspace.id)
        == count_before
    )

    with ComponentContext(
        StackComponentType.ARTIFACT_STORE, config={}, flavor="s3"
    ):
        assert (
            store.count_stack_components(workspace_id=active_workspace.id)
            == count_before + 1
        )


# .-------------------------.
# | Stack component flavors |
# '-------------------------'

# .--------.
# | STACKS |
# '--------'


def test_updating_default_stack_fails():
    """Tests that updating the default stack is prohibited."""
    client = Client()

    default_stack = client.get_stack(DEFAULT_STACK_NAME)
    assert default_stack.name == DEFAULT_WORKSPACE_NAME
    stack_update = StackUpdateModel(name="axls_stack")
    with pytest.raises(IllegalOperationError):
        client.zen_store.update_stack(
            stack_id=default_stack.id, stack_update=stack_update
        )


def test_deleting_default_stack_fails():
    """Tests that deleting the default stack is prohibited."""
    client = Client()

    default_stack = client.get_stack(DEFAULT_STACK_NAME)
    with pytest.raises(IllegalOperationError):
        client.zen_store.delete_stack(default_stack.id)


def test_get_stack_fails_with_nonexistent_stack_id():
    """Tests getting stack fails with nonexistent stack id."""
    client = Client()
    store = client.zen_store

    with pytest.raises(KeyError):
        store.get_stack(uuid.uuid4())


def test_filter_stack_succeeds():
    """Tests getting stack."""
    client = Client()
    store = client.zen_store

    with ComponentContext(
        c_type=StackComponentType.ORCHESTRATOR, flavor="local", config={}
    ) as orchestrator:
        with ComponentContext(
            c_type=StackComponentType.ARTIFACT_STORE, flavor="local", config={}
        ) as artifact_store:
            components = {
                StackComponentType.ORCHESTRATOR: [orchestrator.id],
                StackComponentType.ARTIFACT_STORE: [artifact_store.id],
            }
            with StackContext(components=components) as stack:
                returned_stacks = store.list_stacks(
                    StackFilterModel(name=stack.name)
                )
                assert returned_stacks


def test_crud_on_stack_succeeds():
    """Tests getting stack."""
    client = Client()
    store = client.zen_store

    with ComponentContext(
        c_type=StackComponentType.ORCHESTRATOR, flavor="local", config={}
    ) as orchestrator:
        with ComponentContext(
            c_type=StackComponentType.ARTIFACT_STORE, flavor="local", config={}
        ) as artifact_store:
            components = {
                StackComponentType.ORCHESTRATOR: [orchestrator.id],
                StackComponentType.ARTIFACT_STORE: [artifact_store.id],
            }
            stack_name = sample_name("arias_stack")
            new_stack = StackRequestModel(
                name=stack_name,
                components=components,
                workspace=client.active_workspace.id,
                user=client.active_user.id,
            )
            created_stack = store.create_stack(stack=new_stack)

            stacks = store.list_stacks(StackFilterModel(name=stack_name))
            assert len(stacks) == 1

            with does_not_raise():
                stack = store.get_stack(created_stack.id)
                assert stack is not None

            # Update
            stack_update = StackUpdateModel(name="axls_stack")
            store.update_stack(stack_id=stack.id, stack_update=stack_update)

            stacks = store.list_stacks(StackFilterModel(name="axls_stack"))
            assert len(stacks) == 1
            stacks = store.list_stacks(StackFilterModel(name=stack_name))
            assert len(stacks) == 0

            # Cleanup
            store.delete_stack(created_stack.id)
            with pytest.raises(KeyError):
                store.get_stack(created_stack.id)


def test_register_stack_fails_when_stack_exists():
    """Tests registering stack fails when stack exists."""
    client = Client()
    store = client.zen_store

    with ComponentContext(
        c_type=StackComponentType.ORCHESTRATOR, flavor="local", config={}
    ) as orchestrator:
        with ComponentContext(
            c_type=StackComponentType.ARTIFACT_STORE, flavor="local", config={}
        ) as artifact_store:
            components = {
                StackComponentType.ORCHESTRATOR: [orchestrator.id],
                StackComponentType.ARTIFACT_STORE: [artifact_store.id],
            }
            with StackContext(components=components) as stack:
                new_stack = StackRequestModel(
                    name=stack.name,
                    components=components,
                    workspace=client.active_workspace.id,
                    user=client.active_user.id,
                )
                with pytest.raises(StackExistsError):
                    # TODO: [server] inject user and workspace into stack as well
                    store.create_stack(
                        stack=new_stack,
                    )


def test_updating_nonexistent_stack_fails():
    """Tests updating nonexistent stack fails."""
    client = Client()
    store = client.zen_store

    stack_update = StackUpdateModel(name="axls_stack")
    nonexistent_id = uuid.uuid4()
    with pytest.raises(KeyError):
        store.update_stack(stack_id=nonexistent_id, stack_update=stack_update)
    with pytest.raises(KeyError):
        store.get_stack(nonexistent_id)


def test_deleting_nonexistent_stack_fails():
    """Tests deleting nonexistent stack fails."""
    client = Client()
    store = client.zen_store
    non_existent_stack_id = uuid.uuid4()
    with pytest.raises(KeyError):
        store.delete_stack(non_existent_stack_id)


def test_deleting_a_stack_succeeds():
    """Tests deleting stack."""
    client = Client()
    store = client.zen_store

    with ComponentContext(
        c_type=StackComponentType.ORCHESTRATOR, flavor="local", config={}
    ) as orchestrator:
        with ComponentContext(
            c_type=StackComponentType.ARTIFACT_STORE, flavor="local", config={}
        ) as artifact_store:
            components = {
                StackComponentType.ORCHESTRATOR: [orchestrator.id],
                StackComponentType.ARTIFACT_STORE: [artifact_store.id],
            }
            with StackContext(components=components) as stack:
                store.delete_stack(stack.id)
                with pytest.raises(KeyError):
                    store.get_stack(stack.id)


def test_deleting_a_stack_recursively_succeeds():
    """Tests deleting stack recursively."""
    client = Client()
    store = client.zen_store

    with ComponentContext(
        c_type=StackComponentType.ORCHESTRATOR, flavor="local", config={}
    ) as orchestrator:
        with ComponentContext(
            c_type=StackComponentType.ARTIFACT_STORE, flavor="local", config={}
        ) as artifact_store:
            components = {
                StackComponentType.ORCHESTRATOR: [orchestrator.id],
                StackComponentType.ARTIFACT_STORE: [artifact_store.id],
            }
            with StackContext(components=components) as stack:
                client.delete_stack(stack.id, recursive=True)
                with pytest.raises(KeyError):
                    store.get_stack(stack.id)
                with pytest.raises(KeyError):
                    store.get_stack_component(orchestrator.id)
                with pytest.raises(KeyError):
                    store.get_stack_component(artifact_store.id)


def test_deleting_a_stack_recursively_with_some_stack_components_present_in_another_stack_succeeds():
    """Tests deleting stack recursively."""
    client = Client()
    store = client.zen_store

    with ComponentContext(
        c_type=StackComponentType.ORCHESTRATOR, flavor="local", config={}
    ) as orchestrator:
        with ComponentContext(
            c_type=StackComponentType.ARTIFACT_STORE, flavor="local", config={}
        ) as artifact_store:
            components = {
                StackComponentType.ORCHESTRATOR: [orchestrator.id],
                StackComponentType.ARTIFACT_STORE: [artifact_store.id],
            }
            with StackContext(components=components) as stack:
                with ComponentContext(
                    c_type=StackComponentType.SECRETS_MANAGER,
                    flavor="local",
                    config={},
                ) as secret:
                    components = {
                        StackComponentType.ORCHESTRATOR: [orchestrator.id],
                        StackComponentType.ARTIFACT_STORE: [artifact_store.id],
                        StackComponentType.SECRETS_MANAGER: [secret.id],
                    }
                    with StackContext(components=components) as stack:
                        client.delete_stack(stack.id, recursive=True)
                        with pytest.raises(KeyError):
                            store.get_stack(stack.id)
                        with pytest.raises(KeyError):
                            store.get_stack_component(secret.id)


def test_private_stacks_are_inaccessible():
    """Tests stack scoping via sharing on rest zen stores."""
    if Client().zen_store.type == StoreType.SQL:
        pytest.skip("SQL Zen Stores do not support stack scoping")

    default_user_id = Client().active_user.id
    with ComponentContext(
        c_type=StackComponentType.ORCHESTRATOR,
        flavor="local",
        config={},
        user_id=default_user_id,
    ) as orchestrator:
        with ComponentContext(
            c_type=StackComponentType.ARTIFACT_STORE,
            flavor="local",
            config={},
            user_id=default_user_id,
        ) as artifact_store:
            components = {
                StackComponentType.ORCHESTRATOR: [orchestrator.id],
                StackComponentType.ARTIFACT_STORE: [artifact_store.id],
            }
            with StackContext(
                components=components, user_id=default_user_id
            ) as stack:
                with UserContext(login=True):
                    # Unshared stack should be invisible to the current user
                    #  Client() needs to be instantiated here with the new
                    #  logged-in user
                    filtered_stacks = Client().zen_store.list_stacks(
                        StackFilterModel(name=stack.name)
                    )
                    assert len(filtered_stacks) == 0


def test_public_stacks_are_accessible():
    """Tests stack scoping via sharing on rest zen stores."""
    client = Client()
    store = client.zen_store
    if store.type == StoreType.SQL:
        pytest.skip("SQL Zen Stores do not support stack scoping")

    default_user_id = client.active_user.id
    with ComponentContext(
        c_type=StackComponentType.ORCHESTRATOR,
        flavor="local",
        config={},
        user_id=default_user_id,
    ) as orchestrator:
        with ComponentContext(
            c_type=StackComponentType.ARTIFACT_STORE,
            flavor="local",
            config={},
            user_id=default_user_id,
        ) as artifact_store:
            components = {
                StackComponentType.ORCHESTRATOR: [orchestrator.id],
                StackComponentType.ARTIFACT_STORE: [artifact_store.id],
            }
            with StackContext(
                components=components, user_id=default_user_id
            ) as stack:
                # Update
                stack_update = StackUpdateModel(is_shared=True)
                store.update_stack(
                    stack_id=stack.id, stack_update=stack_update
                )

                with UserContext(login=True):
                    #  Client() needs to be instantiated here with the new
                    #  logged-in user
                    filtered_stacks = Client().zen_store.list_stacks(
                        StackFilterModel(name=stack.name)
                    )
                    assert len(filtered_stacks) == 1


# .-----------.
# | Pipelines |
# '-----------'

# .----------------.
# | Pipeline runs  |
# '----------------'


def test_list_runs_is_ordered():
    """Tests listing runs returns ordered runs."""
    client = Client()
    store = client.zen_store

    num_pipelines_before = store.list_runs(PipelineRunFilterModel()).total

    num_runs = 5
    with PipelineRunContext(num_runs):
        pipelines = store.list_runs(PipelineRunFilterModel()).items
        assert len(pipelines) == num_pipelines_before + num_runs
        assert all(
            pipelines[i].created <= pipelines[i + 1].created
            for i in range(len(pipelines) - 1)
        )


def test_count_runs():
    """Tests that the count runs command returns the correct amount."""
    client = Client()
    store = client.zen_store
    if not isinstance(store, SqlZenStore):
        pytest.skip("Test only applies to SQL store")
    active_workspace = client.active_workspace

    num_runs = store.list_runs(
        PipelineRunFilterModel(scope_workspace=active_workspace.id)
    ).total

    # At baseline this should be the same
    assert store.count_runs(workspace_id=active_workspace.id) == num_runs

    with PipelineRunContext(5):
        assert (
            store.count_runs(workspace_id=active_workspace.id)
            == store.list_runs(
                PipelineRunFilterModel(scope_workspace=active_workspace.id)
            ).total
        )
        assert (
            store.count_runs(workspace_id=active_workspace.id) == num_runs + 5
        )


def test_filter_runs_by_code_repo(mocker):
    """Tests filtering runs by code repository id."""
    mocker.patch.object(
        source_utils, "get_source_root", return_value=os.getcwd()
    )
    store = Client().zen_store

    with CodeRepositoryContext() as repo:
        clean_local_context = StubLocalRepositoryContext(
            code_repository_id=repo.id, root=os.getcwd(), commit="commit"
        )
        mocker.patch.object(
            code_repository_utils,
            "find_active_code_repository",
            return_value=clean_local_context,
        )

        with PipelineRunContext(1):
            filter_model = PipelineRunFilterModel(
                code_repository_id=uuid.uuid4()
            )
            assert store.list_runs(filter_model).total == 0

            filter_model = PipelineRunFilterModel(code_repository_id=repo.id)
            assert store.list_runs(filter_model).total == 1


def test_deleting_run_deletes_steps():
    """Tests deleting run deletes its steps."""
    client = Client()
    store = client.zen_store

    # Just in case the test db is not in a clean state we compare relative
    num_steps_before = store.list_run_steps(StepRunFilterModel()).total
    num_pipelines_before = store.list_runs(PipelineRunFilterModel()).total

    num_runs = 1

    with PipelineRunContext(num_runs) as runs:
        steps = store.list_run_steps(StepRunFilterModel())

        assert steps.total == num_steps_before + num_runs * 2
        pipelines = store.list_runs(PipelineRunFilterModel())
        assert pipelines.total == num_pipelines_before + num_runs
        run_id = runs[0].id
        store.delete_run(run_id)
        assert (
            len(store.list_run_steps(StepRunFilterModel())) == num_steps_before
        )


# .--------------------.
# | Pipeline run steps |
# '--------------------'


def test_get_run_step_outputs_succeeds():
    """Tests getting run step outputs."""
    client = Client()
    store = client.zen_store

    with PipelineRunContext(1):
        steps = store.list_run_steps(StepRunFilterModel(name="step_2"))

        for step in steps.items:
            run_step_outputs = store.get_run_step(step.id).outputs
            assert len(run_step_outputs) == 1


def test_get_run_step_inputs_succeeds():
    """Tests getting run step inputs."""
    client = Client()
    store = client.zen_store

    with PipelineRunContext(1):
        steps = store.list_run_steps(StepRunFilterModel(name="step_2"))
        for step in steps.items:
            run_step_inputs = store.get_run_step(step.id).inputs
            assert len(run_step_inputs) == 1


# .-----------.
# | Artifacts |
# '-----------'


def test_list_unused_artifacts():
    """Tests listing with `unused=True` only returns unused artifacts."""
    client = Client()
    store = client.zen_store

    num_artifacts_before = store.list_artifacts(ArtifactFilterModel()).total
    num_unused_artifacts_before = store.list_artifacts(
        ArtifactFilterModel(only_unused=True)
    ).total
    num_runs = 1
    with PipelineRunContext(num_runs):
        artifacts = store.list_artifacts(ArtifactFilterModel())
        assert artifacts.total == num_artifacts_before + num_runs * 2

        artifacts = store.list_artifacts(ArtifactFilterModel(only_unused=True))
        assert artifacts.total == num_unused_artifacts_before


def test_artifacts_are_not_deleted_with_run():
    """Tests listing with `unused=True` only returns unused artifacts."""
    client = Client()
    store = client.zen_store

    num_artifacts_before = store.list_artifacts(ArtifactFilterModel()).total
    num_runs = 1
    with PipelineRunContext(num_runs):
        artifacts = store.list_artifacts(ArtifactFilterModel())
        assert artifacts.total == num_artifacts_before + num_runs * 2

        # Cleanup
        pipelines = store.list_runs(PipelineRunFilterModel()).items
        for p in pipelines:
            store.delete_run(p.id)

        artifacts = store.list_artifacts(ArtifactFilterModel())
        assert artifacts.total == num_artifacts_before + num_runs * 2


# .---------.
# | Logs    |
# '---------'


def test_logs_are_recorded_properly(clean_client):
    """Tests if logs are stored in the artifact store."""
    client = Client()
    store = client.zen_store

    with PipelineRunContext(2):
        steps = store.list_run_steps(StepRunFilterModel())
        step1_logs = steps[0].logs
        step2_logs = steps[1].logs
        artifact_store = _load_artifact_store(
            step1_logs.artifact_store_id, store
        )
        step1_logs_content = _load_file_from_artifact_store(
            step1_logs.uri, artifact_store=artifact_store, mode="r"
        )
        step2_logs_content = _load_file_from_artifact_store(
            step2_logs.uri, artifact_store=artifact_store, mode="r"
        )

        # Step 1 has the word log! Defined in PipelineRunContext
        assert "log" in step1_logs_content

        # Step 2 does not have logs!
        assert "Step step_2 has started." in step2_logs_content


def test_logs_are_recorded_properly_when_disabled(clean_client):
    """Tests no logs are stored in the artifact store when disabled"""
    client = Client()
    store = client.zen_store

    with PipelineRunContext(2, enable_step_logs=False):
        steps = store.list_run_steps(StepRunFilterModel())
        step1_logs = steps[0].logs
        step2_logs = steps[1].logs
        assert not step1_logs
        assert not step2_logs

        artifact_store_id = steps[0].output.artifact_store_id
        assert artifact_store_id

        artifact_store = _load_artifact_store(artifact_store_id, store)

        logs_uri_1 = prepare_logs_uri(
            artifact_store=artifact_store,
            step_name=steps[0].name,
        )

        logs_uri_2 = prepare_logs_uri(
            artifact_store=artifact_store,
            step_name=steps[1].name,
        )

        prepare_logs_uri(
            artifact_store=artifact_store,
            step_name=steps[1].name,
        )

        with pytest.raises(DoesNotExistException):
            _load_file_from_artifact_store(
                logs_uri_1, artifact_store=artifact_store, mode="r"
            )

        with pytest.raises(DoesNotExistException):
            _load_file_from_artifact_store(
                logs_uri_2, artifact_store=artifact_store, mode="r"
            )


# .--------------------.
# | Service Connectors |
# '--------------------'


def test_connector_with_no_secrets():
    """Tests that a connector with no secrets has no attached secret."""
    client = Client()
    store = client.zen_store

    config = {
        "language": "meow",
        "foods": "tuna",
    }
    with ServiceConnectorContext(
        connector_type="cat'o'matic",
        auth_method="paw-print",
        resource_types=["cat"],
        resource_id="aria",
        configuration=config,
    ) as connector:
        assert connector.id is not None
        assert connector.type == "cat'o'matic"
        assert connector.auth_method == "paw-print"
        assert connector.resource_types == ["cat"]
        assert connector.resource_id == "aria"
        assert connector.configuration == config
        assert len(connector.secrets) == 0
        assert connector.secret_id is None

        registered_connector = store.get_service_connector(connector.id)

        assert registered_connector.id == connector.id
        assert registered_connector.name == connector.name
        assert registered_connector.type == connector.type
        assert registered_connector.auth_method == connector.auth_method
        assert registered_connector.resource_types == connector.resource_types
        assert registered_connector.configuration == config
        assert len(registered_connector.secrets) == 0
        assert registered_connector.secret_id is None


def test_connector_with_secrets():
    """Tests that a connector with secrets has an attached secret."""
    client = Client()
    store = client.zen_store

    config = {
        "language": "meow",
        "foods": "tuna",
    }
    secrets = {
        "hiding-place": SecretStr("thatsformetoknowandyouneverfindout"),
        "dreams": SecretStr("notyourbusiness"),
    }
    with ServiceConnectorContext(
        connector_type="cat'o'matic",
        auth_method="paw-print",
        resource_types=["cat"],
        resource_id="blupus",
        configuration=config,
        secrets=secrets,
    ) as connector:
        assert connector.id is not None
        assert connector.type == "cat'o'matic"
        assert connector.auth_method == "paw-print"
        assert connector.resource_types == ["cat"]
        assert connector.resource_id == "blupus"
        assert connector.configuration == config
        assert len(connector.secrets) == 0
        assert connector.secret_id is not None

        secret = store.get_secret(connector.secret_id)
        assert secret.id == connector.secret_id
        assert secret.name.startswith(f"connector-{connector.name}")
        assert secret.values == secrets

        registered_connector = store.get_service_connector(connector.id)

        assert registered_connector.id == connector.id
        assert registered_connector.name == connector.name
        assert registered_connector.type == connector.type
        assert registered_connector.auth_method == connector.auth_method
        assert registered_connector.resource_types == connector.resource_types
        assert registered_connector.configuration == config
        assert len(registered_connector.secrets) == 0
        assert registered_connector.secret_id == connector.secret_id


def test_connector_with_no_config_no_secrets():
    """Tests that a connector with no config and no secrets is possible."""
    client = Client()
    store = client.zen_store

    with ServiceConnectorContext(
        connector_type="cat'o'matic",
        auth_method="whiskers",
        resource_types=["spacecat"],
        resource_id="axl",
    ) as connector:
        assert connector.id is not None
        assert connector.type == "cat'o'matic"
        assert connector.auth_method == "whiskers"
        assert connector.resource_types == ["spacecat"]
        assert connector.resource_id == "axl"
        assert len(connector.configuration) == 0
        assert len(connector.secrets) == 0
        assert connector.secret_id is None

        registered_connector = store.get_service_connector(connector.id)

        assert registered_connector.id == connector.id
        assert registered_connector.name == connector.name
        assert registered_connector.type == connector.type
        assert registered_connector.auth_method == connector.auth_method
        assert registered_connector.resource_types == connector.resource_types
        assert len(connector.configuration) == 0
        assert len(registered_connector.secrets) == 0
        assert registered_connector.secret_id is None


def test_connector_with_labels():
    """Tests that a connector with labels is possible."""
    client = Client()
    store = client.zen_store

    config = {
        "language": "meow",
        "foods": "tuna",
    }
    secrets = {
        "hiding-place": SecretStr("thatsformetoknowandyouneverfindout"),
        "dreams": SecretStr("notyourbusiness"),
    }
    labels = {
        "whereabouts": "unknown",
        "age": "eternal",
    }
    with ServiceConnectorContext(
        connector_type="cat'o'matic",
        auth_method="tail-print",
        resource_types=["cat"],
        resource_id="aria",
        configuration=config,
        secrets=secrets,
        labels=labels,
    ) as connector:
        assert connector.id is not None
        assert connector.type == "cat'o'matic"
        assert connector.auth_method == "tail-print"
        assert connector.resource_types == ["cat"]
        assert connector.resource_id == "aria"
        assert connector.configuration == config
        assert len(connector.secrets) == 0
        assert connector.secret_id is not None
        assert connector.labels == labels

        secret = store.get_secret(connector.secret_id)
        assert secret.id == connector.secret_id
        assert secret.name.startswith(f"connector-{connector.name}")
        assert secret.values == secrets

        registered_connector = store.get_service_connector(connector.id)

        assert registered_connector.id == connector.id
        assert registered_connector.name == connector.name
        assert registered_connector.type == connector.type
        assert registered_connector.auth_method == connector.auth_method
        assert registered_connector.resource_types == connector.resource_types
        assert registered_connector.configuration == config
        assert len(registered_connector.secrets) == 0
        assert registered_connector.secret_id == connector.secret_id
        assert registered_connector.labels == labels


def test_connector_secret_share_lifespan():
    """Tests that a connector's secret shares its lifespan."""
    client = Client()
    store = client.zen_store

    config = {
        "language": "meow",
        "foods": "tuna",
    }
    secrets = {
        "hiding-place": SecretStr("thatsformetoknowandyouneverfindout"),
        "dreams": SecretStr("notyourbusiness"),
    }
    with ServiceConnectorContext(
        connector_type="cat'o'matic",
        auth_method="paw-print",
        resource_types=["cat"],
        resource_id="blupus",
        configuration=config,
        secrets=secrets,
    ) as connector:
        assert connector.id is not None
        assert connector.type == "cat'o'matic"
        assert connector.auth_method == "paw-print"
        assert connector.resource_types == ["cat"]
        assert connector.resource_id == "blupus"
        assert connector.configuration == config
        assert len(connector.secrets) == 0
        assert connector.secret_id is not None

        secret = store.get_secret(connector.secret_id)
        assert secret.id == connector.secret_id
        assert secret.name.startswith(f"connector-{connector.name}")
        assert secret.values == secrets

        store.delete_service_connector(connector.id)

        with pytest.raises(KeyError):
            store.get_service_connector(connector.id)

        with pytest.raises(KeyError):
            store.get_secret(connector.secret_id)


def test_connector_name_reuse_for_same_user_fails():
    """Tests that a connector's name cannot be re-used for the same user."""

    with ServiceConnectorContext(
        connector_type="cat'o'matic",
        auth_method="paw-print",
        resource_types=["cat"],
    ) as connector_one:
        with pytest.raises(EntityExistsError):
            with ServiceConnectorContext(
                name=connector_one.name,
                connector_type="cat'o'matic",
                auth_method="paw-print",
                resource_types=["cat"],
            ):
                pass


def test_connector_same_name_different_users():
    """Tests that a connector's name can be used if another user has it."""

    if Client().zen_store.type == StoreType.SQL:
        pytest.skip("SQL Zen Stores do not support user switching.")

    with ServiceConnectorContext(
        connector_type="cat'o'matic",
        auth_method="paw-print",
        resource_types=["cat"],
    ) as connector_one:
        with UserContext(login=True):
            #  Client() needs to be instantiated here with the new
            #  logged-in user
            other_client = Client()

            with ServiceConnectorContext(
                name=connector_one.name,
                connector_type="cat'o'matic",
                auth_method="paw-print",
                resource_types=["cat"],
                client=other_client,
            ):
                pass


def test_connector_same_name_different_users_shared():
    """Tests that a connector's name can be used even if another user has it shared."""

    if Client().zen_store.type == StoreType.SQL:
        pytest.skip("SQL Zen Stores do not support user switching.")

    with ServiceConnectorContext(
        connector_type="cat'o'matic",
        auth_method="paw-print",
        resource_types=["cat"],
        is_shared=True,
    ) as connector_one:
        with UserContext(login=True):
            #  Client() needs to be instantiated here with the new
            #  logged-in user
            other_client = Client()

            with ServiceConnectorContext(
                name=connector_one.name,
                connector_type="cat'o'matic",
                auth_method="paw-print",
                resource_types=["cat"],
                client=other_client,
            ):
                pass


def test_connector_same_name_different_users_both_shared():
    """Tests that a shared connector's name cannot be used if another user also has it shared."""

    if Client().zen_store.type == StoreType.SQL:
        pytest.skip("SQL Zen Stores do not support user switching.")

    with ServiceConnectorContext(
        connector_type="cat'o'matic",
        auth_method="paw-print",
        resource_types=["cat"],
        is_shared=True,
    ) as connector_one:
        with UserContext(login=True):
            #  Client() needs to be instantiated here with the new
            #  logged-in user
            other_client = Client()

            with pytest.raises(EntityExistsError):
                with ServiceConnectorContext(
                    name=connector_one.name,
                    connector_type="cat'o'matic",
                    auth_method="paw-print",
                    resource_types=["cat"],
                    client=other_client,
                    is_shared=True,
                ):
                    pass


def test_connector_list():
    """Tests connector listing and filtering."""
    client = Client()
    store = client.zen_store

    config1 = {
        "language": "meow",
        "foods": "tuna",
    }
    secrets1 = {
        "hiding-place": SecretStr("thatsformetoknowandyouneverfindout"),
        "dreams": SecretStr("notyourbusiness"),
    }
    labels1 = {
        "whereabouts": "unknown",
        "age": "eternal",
    }
    config2 = {
        "language": "beast",
        "foods": "everything",
    }
    secrets2 = {
        "hiding-place": SecretStr("someplaceyouwillneverfindme"),
        "dreams": SecretStr("milkandmiceandeverythingnice"),
    }
    labels2 = {
        "whereabouts": "everywhere",
        "weight": "ethereal",
    }
    config3 = {
        "language": "mousespeech",
        "foods": "cheese",
    }
    secrets3 = {
        "hiding-place": SecretStr("underthebed"),
        "dreams": SecretStr("cheesecheesecheese"),
    }
    labels3 = {
        "whereabouts": "unknown",
        "nick": "rodent",
    }

    with ServiceConnectorContext(
        connector_type="cat'o'matic",
        auth_method="paw-print",
        resource_types=["cat"],
        resource_id="aria",
        configuration=config1,
        secrets=secrets1,
        labels=labels1,
    ) as aria_connector:
        with ServiceConnectorContext(
            connector_type="tail'o'matic",
            auth_method="tail-print",
            resource_types=["cat", "mouse"],
            configuration=config2,
            secrets=secrets2,
            labels=labels2,
        ) as multi_connector:
            with ServiceConnectorContext(
                connector_type="tail'o'matic",
                auth_method="tail-print",
                resource_types=["mouse"],
                resource_id="bartholomew",
                configuration=config3,
                secrets=secrets3,
                labels=labels3,
            ) as rodent_connector:
                # List all connectors
                connectors = store.list_service_connectors(
                    ServiceConnectorFilterModel()
                ).items
                assert len(connectors) >= 3
                assert aria_connector in connectors
                assert multi_connector in connectors
                assert rodent_connector in connectors

                # Filter by name
                connectors = store.list_service_connectors(
                    ServiceConnectorFilterModel(name=aria_connector.name)
                ).items
                assert len(connectors) == 1
                assert aria_connector.id == connectors[0].id

                connectors = store.list_service_connectors(
                    ServiceConnectorFilterModel(name=multi_connector.name)
                ).items
                assert len(connectors) == 1
                assert multi_connector.id == connectors[0].id

                # Filter by connector type
                connectors = store.list_service_connectors(
                    ServiceConnectorFilterModel(connector_type="cat'o'matic")
                ).items
                assert len(connectors) >= 1
                assert aria_connector.id in [c.id for c in connectors]
                assert multi_connector.id not in [c.id for c in connectors]
                assert rodent_connector.id not in [c.id for c in connectors]

                connectors = store.list_service_connectors(
                    ServiceConnectorFilterModel(connector_type="tail'o'matic")
                ).items
                assert len(connectors) >= 2
                assert aria_connector.id not in [c.id for c in connectors]
                assert multi_connector.id in [c.id for c in connectors]
                assert rodent_connector.id in [c.id for c in connectors]

                # Filter by auth method
                connectors = store.list_service_connectors(
                    ServiceConnectorFilterModel(auth_method="paw-print")
                ).items
                assert len(connectors) >= 1
                assert aria_connector.id in [c.id for c in connectors]
                assert multi_connector.id not in [c.id for c in connectors]
                assert rodent_connector.id not in [c.id for c in connectors]

                connectors = store.list_service_connectors(
                    ServiceConnectorFilterModel(auth_method="tail-print")
                ).items
                assert len(connectors) >= 1
                assert aria_connector.id not in [c.id for c in connectors]
                assert multi_connector.id in [c.id for c in connectors]
                assert rodent_connector.id in [c.id for c in connectors]

                # Filter by resource type
                connectors = store.list_service_connectors(
                    ServiceConnectorFilterModel(resource_type="cat")
                ).items
                assert len(connectors) >= 2
                assert aria_connector.id in [c.id for c in connectors]
                assert multi_connector.id in [c.id for c in connectors]
                assert rodent_connector.id not in [c.id for c in connectors]

                connectors = store.list_service_connectors(
                    ServiceConnectorFilterModel(resource_type="mouse")
                ).items
                assert len(connectors) >= 2
                assert aria_connector.id not in [c.id for c in connectors]
                assert multi_connector.id in [c.id for c in connectors]
                assert rodent_connector.id in [c.id for c in connectors]

                # Filter by resource id
                connectors = store.list_service_connectors(
                    ServiceConnectorFilterModel(
                        resource_type="cat",
                        resource_id="aria",
                    )
                ).items
                assert len(connectors) >= 1
                assert aria_connector.id in [c.id for c in connectors]
                assert multi_connector.id not in [c.id for c in connectors]
                assert rodent_connector.id not in [c.id for c in connectors]

                connectors = store.list_service_connectors(
                    ServiceConnectorFilterModel(
                        resource_type="mouse",
                        resource_id="bartholomew",
                    )
                ).items
                assert len(connectors) >= 1
                assert aria_connector.id not in [c.id for c in connectors]
                assert multi_connector.id not in [c.id for c in connectors]
                assert rodent_connector.id in [c.id for c in connectors]

                # Filter by labels
                connectors = store.list_service_connectors(
                    ServiceConnectorFilterModel(
                        labels={"whereabouts": "unknown"}
                    )
                ).items
                assert len(connectors) >= 2
                assert aria_connector.id in [c.id for c in connectors]
                assert multi_connector.id not in [c.id for c in connectors]
                assert rodent_connector.id in [c.id for c in connectors]

                connectors = store.list_service_connectors(
                    ServiceConnectorFilterModel(labels={"whereabouts": None})
                ).items
                assert len(connectors) >= 3
                assert aria_connector.id in [c.id for c in connectors]
                assert multi_connector.id in [c.id for c in connectors]
                assert rodent_connector.id in [c.id for c in connectors]

                connectors = store.list_service_connectors(
                    ServiceConnectorFilterModel(
                        labels={"nick": "rodent", "whereabouts": "unknown"}
                    )
                ).items
                assert len(connectors) >= 1
                assert aria_connector.id not in [c.id for c in connectors]
                assert multi_connector.id not in [c.id for c in connectors]
                assert rodent_connector.id in [c.id for c in connectors]

                connectors = store.list_service_connectors(
                    ServiceConnectorFilterModel(
                        labels={"weight": None, "whereabouts": None}
                    )
                ).items
                assert len(connectors) >= 1
                assert aria_connector.id not in [c.id for c in connectors]
                assert multi_connector.id in [c.id for c in connectors]
                assert rodent_connector.id not in [c.id for c in connectors]


def test_private_connector_not_visible_to_other_user():
    """Tests that a private connector is not visible to another user."""

    if Client().zen_store.type == StoreType.SQL:
        pytest.skip("SQL Zen Stores do not support user switching.")

    with ServiceConnectorContext(
        connector_type="cat'o'matic",
        auth_method="paw-print",
        resource_types=["cat"],
        is_shared=False,
    ) as connector:
        with UserContext(login=True):
            #  Client() needs to be instantiated here with the new
            #  logged-in user
            other_client = Client()
            other_store = other_client.zen_store

            with pytest.raises(KeyError):
                other_store.get_service_connector(connector.id)

            connectors = other_store.list_service_connectors(
                ServiceConnectorFilterModel()
            ).items

            assert connector.id not in [c.id for c in connectors]


def test_shared_connector_is_visible_to_other_user():
    """Tests that a shared connector is visible to another user."""

    if Client().zen_store.type == StoreType.SQL:
        pytest.skip("SQL Zen Stores do not support user switching.")

    with ServiceConnectorContext(
        connector_type="cat'o'matic",
        auth_method="paw-print",
        resource_types=["cat"],
        is_shared=True,
    ) as connector:
        with UserContext(login=True):
            #  Client() needs to be instantiated here with the new
            #  logged-in user
            other_client = Client()
            other_store = other_client.zen_store

            other_store.get_service_connector(connector.id)

            connectors = other_store.list_service_connectors(
                ServiceConnectorFilterModel()
            ).items

            assert connector.id in [c.id for c in connectors]


def _update_connector_and_test(
    new_name: Optional[str] = None,
    new_connector_type: Optional[str] = None,
    new_auth_method: Optional[str] = None,
    new_resource_types: Optional[List[str]] = None,
    new_resource_id_or_not: Optional[Tuple[Optional[str]]] = None,
    new_config: Optional[Dict[str, str]] = None,
    new_secrets: Optional[Dict[str, Optional[SecretStr]]] = None,
    new_expires_at: Optional[datetime] = None,
    new_expiration_seconds_or_not: Optional[Tuple[Optional[int]]] = None,
    new_labels: Optional[Dict[str, str]] = None,
):
    """Helper function to update a connector and test that the update was successful."""
    client = Client()
    store = client.zen_store

    config = {
        "language": "meow",
        "foods": "tuna",
    }
    secrets = {
        "hiding-place": SecretStr("thatsformetoknowandyouneverfindout"),
        "dreams": SecretStr("notyourbusiness"),
    }
    labels = {
        "whereabouts": "unknown",
        "age": "eternal",
    }
    now = datetime.utcnow()
    with ServiceConnectorContext(
        connector_type="cat'o'matic",
        auth_method="paw-print",
        resource_types=["cat"],
        resource_id="blupus",
        configuration=config,
        secrets=secrets,
        expires_at=now,
        expiration_seconds=60,
        labels=labels,
    ) as connector:
        assert connector.id is not None
        assert connector.type == "cat'o'matic"
        assert connector.auth_method == "paw-print"
        assert connector.resource_types == ["cat"]
        assert connector.resource_id == "blupus"
        assert connector.configuration == config
        assert len(connector.secrets) == 0
        assert connector.secret_id is not None
        assert connector.labels == labels

        secret = store.get_secret(connector.secret_id)
        assert secret.id == connector.secret_id
        assert secret.name.startswith(f"connector-{connector.name}")
        assert secret.values == secrets

        # Update the connector
        # NOTE: we need to pass the `resource_id` and `expiration_seconds`
        # fields in the update model, otherwise the update will remove them
        # from the connector.
        new_resource_id = (
            new_resource_id_or_not[0]
            if new_resource_id_or_not
            else connector.resource_id
        )
        new_expiration_seconds = (
            new_expiration_seconds_or_not[0]
            if new_expiration_seconds_or_not
            else connector.expiration_seconds
        )
        store.update_service_connector(
            connector.id,
            update=ServiceConnectorUpdateModel(
                name=new_name,
                connector_type=new_connector_type,
                auth_method=new_auth_method,
                resource_types=new_resource_types,
                resource_id=new_resource_id,
                configuration=new_config,
                secrets=new_secrets,
                expires_at=new_expires_at,
                expiration_seconds=new_expiration_seconds,
                labels=new_labels,
            ),
        )

        # Check that the connector has been updated
        registered_connector = store.get_service_connector(connector.id)

        assert registered_connector.id == connector.id
        assert registered_connector.name == new_name or connector.name
        assert (
            registered_connector.type == new_connector_type or connector.type
        )
        assert (
            registered_connector.auth_method == new_auth_method
            or connector.auth_method
        )
        assert (
            registered_connector.resource_types == new_resource_types
            or connector.resource_types
        )
        assert registered_connector.resource_id == new_resource_id
        assert len(registered_connector.secrets) == 0

        # the `configuration` and `secrets` fields represent a full
        # valid configuration update, not just a partial update. If either is
        # set (i.e. not None) in the update, their values
        # will replace the existing configuration and secrets values.

        if new_config is not None:
            assert registered_connector.configuration == new_config or {}
        else:
            assert (
                registered_connector.configuration == connector.configuration
            )

        if new_secrets is not None:
            if not new_secrets:
                # Existing secret is deleted if no new secrets are provided
                assert registered_connector.secret_id is None
            else:
                # New secret is created if secrets are updated
                assert registered_connector.secret_id != connector.secret_id
        else:
            assert registered_connector.secret_id == connector.secret_id

        assert registered_connector.labels == new_labels or connector.labels

        if new_secrets is not None:
            if not new_secrets:
                # Existing secret is deleted if secrets are removed
                with pytest.raises(KeyError):
                    store.get_secret(connector.secret_id)
            else:
                # Previous secret is deleted if secrets are updated
                with pytest.raises(KeyError):
                    store.get_secret(connector.secret_id)

                # Check that a new secret has been created
                new_secret = store.get_secret(registered_connector.secret_id)
                assert new_secret.id == registered_connector.secret_id
                # Secret name should have changed
                assert new_secret.name.startswith(
                    f"connector-{new_name or connector.name}"
                )
                assert new_secret.values == new_secrets
        else:
            new_secret = store.get_secret(connector.secret_id)
            assert new_secret.id == connector.secret_id
            # Secret name should not have changed
            assert new_secret.name == secret.name
            assert new_secret.values == secrets


def test_connector_update_name():
    """Tests that a connector's name can be updated."""
    _update_connector_and_test(
        new_name="axl-incognito",
    )


def test_connector_update_type():
    """Tests that a connector's type can be updated."""
    _update_connector_and_test(
        new_connector_type="dog'o'matic",
    )


def test_connector_update_resource_types():
    """Tests that a connector's resource types can be updated."""
    _update_connector_and_test(new_resource_types=["cat", "dog"])


def test_connector_update_resource_id():
    """Tests that a connector's resource ID can be updated or removed."""
    _update_connector_and_test(new_resource_id_or_not=("axl",))
    _update_connector_and_test(new_resource_id_or_not=(None,))


def test_connector_update_auth_method():
    """Tests that a connector's auth method can be updated."""
    _update_connector_and_test(
        new_auth_method="collar",
    )


def test_connector_update_config():
    """Tests that a connector's configuration and secrets can be updated."""

    new_config = {
        "language": "purr",
        "chase": "own-tail",
    }
    new_secrets = {
        "hiding-place": SecretStr("anotherplaceyouwillneverfindme"),
        "food": SecretStr("firebreathingdragon"),
    }

    _update_connector_and_test(
        new_config=new_config,
    )
    _update_connector_and_test(
        new_secrets=new_secrets,
    )
    _update_connector_and_test(
        new_config=new_config,
        new_secrets=new_secrets,
    )
    _update_connector_and_test(
        new_config={},
    )
    _update_connector_and_test(
        new_secrets={},
    )


def test_connector_update_expiration():
    """Tests that a connector's expiration period can be updated or removed."""
    _update_connector_and_test(new_expiration_seconds_or_not=(90,))
    _update_connector_and_test(new_expiration_seconds_or_not=(None,))


def test_connector_update_expires_at():
    """Tests that a connector's expiration date can be updated."""
    _update_connector_and_test(new_expires_at=datetime.now())


def test_connector_update_labels():
    """Tests that a connector's labels can be updated."""
    labels = {
        "whereabouts": "everywhere",
        "form": "fluid",
    }
    _update_connector_and_test(new_labels=labels)
    _update_connector_and_test(new_labels={})


def test_connector_name_update_fails_if_exists():
    """Tests that a connector's name cannot be updated to an existing name."""

    client = Client()
    store = client.zen_store

    with ServiceConnectorContext(
        connector_type="cat'o'matic",
        auth_method="paw-print",
        resource_types=["cat"],
    ) as connector_one:
        with ServiceConnectorContext(
            connector_type="cat'o'matic",
            auth_method="paw-print",
            resource_types=["cat"],
        ) as connector_two:
            with pytest.raises(EntityExistsError):
                store.update_service_connector(
                    connector_one.id,
                    update=ServiceConnectorUpdateModel(
                        name=connector_two.name
                    ),
                )


def test_connector_sharing():
    """Tests that a connector can be shared."""

    client = Client()
    store = client.zen_store

    if client.zen_store.type == StoreType.SQL:
        pytest.skip("SQL Zen Stores do not support user switching.")

    config = {
        "language": "meow",
        "foods": "tuna",
    }
    secrets = {
        "hiding-place": SecretStr("thatsformetoknowandyouneverfindout"),
        "dreams": SecretStr("notyourbusiness"),
    }

    with ServiceConnectorContext(
        connector_type="cat'o'matic",
        auth_method="paw-print",
        resource_types=["cat"],
        configuration=config,
        secrets=secrets,
        is_shared=False,
    ) as connector:
        assert connector.secret_id is not None
        secret = store.get_secret(connector.secret_id)
        assert secret.scope == SecretScope.USER

        with UserContext(login=True):
            #  Client() needs to be instantiated here with the new
            #  logged-in user
            other_client = Client()
            other_store = other_client.zen_store

            with pytest.raises(KeyError):
                other_store.get_service_connector(connector.id)

            connectors = other_store.list_service_connectors(
                ServiceConnectorFilterModel()
            ).items

            assert connector.id not in [c.id for c in connectors]

        updated_connector = store.update_service_connector(
            connector.id,
            update=ServiceConnectorUpdateModel(is_shared=True),
        )

        assert updated_connector.secret_id is not None
        assert updated_connector.secret_id == connector.secret_id
        secret = store.get_secret(updated_connector.secret_id)
        assert secret.scope == SecretScope.WORKSPACE

        with UserContext(login=True):
            #  Client() needs to be instantiated here with the new
            #  logged-in user
            other_client = Client()
            other_store = other_client.zen_store

            other_store.get_service_connector(connector.id)

            connectors = other_store.list_service_connectors(
                ServiceConnectorFilterModel()
            ).items

            assert connector.id in [c.id for c in connectors]


def test_connector_sharing_fails_if_name_shared():
    """Tests that a connector cannot be shared if the name is already shared."""

    client = Client()

    if client.zen_store.type == StoreType.SQL:
        pytest.skip("SQL Zen Stores do not support user switching.")

    with ServiceConnectorContext(
        connector_type="cat'o'matic",
        auth_method="paw-print",
        resource_types=["cat"],
        is_shared=True,
    ) as connector:
        with UserContext(login=True):
            #  Client() needs to be instantiated here with the new
            #  logged-in user
            other_client = Client()
            other_store = other_client.zen_store

            other_store.get_service_connector(connector.id)

            connectors = other_store.list_service_connectors(
                ServiceConnectorFilterModel()
            ).items

            assert connector.id in [c.id for c in connectors]

            with ServiceConnectorContext(
                name=connector.name,
                connector_type="cat'o'matic",
                auth_method="paw-print",
                resource_types=["cat"],
                is_shared=False,
            ) as other_connector:
                with pytest.raises(EntityExistsError):
                    other_store.update_service_connector(
                        other_connector.id,
                        update=ServiceConnectorUpdateModel(is_shared=True),
                    )


# .-------------------------.
# | Service Connector Types |
# '-------------------------'


def test_connector_type_register():
    """Tests that a connector type can be registered locally."""

    client = Client()
    store = client.zen_store

    connector_type = sample_name("cat'o'matic")
    resource_type_one = sample_name("scratch")
    resource_type_two = sample_name("purr")

    with pytest.raises(KeyError):
        store.get_service_connector_type(connector_type)
    assert (
        store.list_service_connector_types(connector_type=connector_type) == []
    )
    assert (
        store.list_service_connector_types(resource_type=resource_type_one)
        == []
    )
    assert (
        store.list_service_connector_types(resource_type=resource_type_two)
        == []
    )

    with ServiceConnectorTypeContext(
        connector_type=connector_type,
        resource_type_one=resource_type_one,
        resource_type_two=resource_type_two,
    ) as connector_type_spec:
        assert (
            store.get_service_connector_type(connector_type)
            == connector_type_spec
        )
        assert store.list_service_connector_types(
            resource_type=resource_type_one
        ) == [connector_type_spec]
        assert store.list_service_connector_types(
            resource_type=resource_type_two
        ) == [connector_type_spec]


def test_connector_validation():
    """Tests that a connector type is used to validate a connector."""

    client = Client()
    store = client.zen_store

    if store.type != StoreType.SQL:
        pytest.skip("Only applicable to SQL store")

    connector_type = sample_name("cat'o'matic")
    resource_type_one = sample_name("scratch")
    resource_type_two = sample_name("purr")

    with ServiceConnectorTypeContext(
        connector_type=connector_type,
        resource_type_one=resource_type_one,
        resource_type_two=resource_type_two,
    ):
        # All attributes
        config = {
            "color": "pink",
            "name": "aria",
        }
        secrets = {
            "hiding_spot": SecretStr("thatsformetoknowandyouneverfindout"),
            "secret_word": SecretStr("meowmeowmeow"),
        }
        with ServiceConnectorContext(
            connector_type=connector_type,
            auth_method="voice-print",
            resource_types=[resource_type_one, resource_type_two],
            configuration=config,
            secrets=secrets,
        ) as connector:
            assert connector.configuration == config
            assert connector.secrets == {}
            assert connector.secret_id is not None
            secret = store.get_secret(connector.secret_id)
            assert secret.values == secrets

        # Only required attributes
        config = {
            "name": "aria",
        }
        secrets = {
            "secret_word": SecretStr("meowmeowmeow"),
        }
        with ServiceConnectorContext(
            connector_type=connector_type,
            auth_method="voice-print",
            resource_types=[resource_type_one, resource_type_two],
            configuration=config,
            secrets=secrets,
        ) as connector:
            assert connector.configuration == config
            assert connector.secrets == {}
            assert connector.secret_id is not None
            secret = store.get_secret(connector.secret_id)
            assert secret.values == secrets

        # Missing required configuration attribute
        config = {}
        secrets = {
            "secret_word": SecretStr("meowmeowmeow"),
        }
        with pytest.raises(ValueError):
            with ServiceConnectorContext(
                connector_type=connector_type,
                auth_method="voice-print",
                resource_types=[resource_type_one, resource_type_two],
                configuration=config,
                secrets=secrets,
            ):
                pass

        # Missing required secret attribute
        config = {
            "name": "aria",
        }
        secrets = {}
        with pytest.raises(ValueError):
            with ServiceConnectorContext(
                connector_type=connector_type,
                auth_method="voice-print",
                resource_types=[resource_type_one, resource_type_two],
                configuration=config,
                secrets=secrets,
            ):
                pass

        # All attributes mashed together
        config = {
            "color": "pink",
            "name": "aria",
        }
        secrets = {
            "hiding_spot": SecretStr("thatsformetoknowandyouneverfindout"),
            "secret_word": SecretStr("meowmeowmeow"),
        }
        full_config = config.copy()
        full_config.update(
            {k: v.get_secret_value() for k, v in secrets.items()}
        )
        with ServiceConnectorContext(
            connector_type=connector_type,
            auth_method="voice-print",
            resource_types=[resource_type_one, resource_type_two],
            configuration=full_config,
        ) as connector:
            assert connector.configuration == config
            assert connector.secrets == {}
            assert connector.secret_id is not None
            secret = store.get_secret(connector.secret_id)
            assert secret.values == secrets

        # Different auth method
        with pytest.raises(ValueError):
            with ServiceConnectorContext(
                connector_type=connector_type,
                auth_method="claw-marks",
                resource_types=[resource_type_one, resource_type_two],
                configuration=config,
                secrets=secrets,
            ):
                pass

        # Wrong auth method
        with pytest.raises(ValueError):
            with ServiceConnectorContext(
                connector_type=connector_type,
                auth_method="paw-print",
                resource_types=[resource_type_one, resource_type_two],
                configuration=config,
                secrets=secrets,
            ):
                pass

        # Single type
        with ServiceConnectorContext(
            connector_type=connector_type,
            auth_method="voice-print",
            resource_types=[resource_type_one],
            configuration=config,
            secrets=secrets,
        ):
            pass

        # Wrong resource type
        with pytest.raises(ValueError):
            with ServiceConnectorContext(
                connector_type=connector_type,
                auth_method="voice-print",
                resource_types=["purr"],
                configuration=config,
                secrets=secrets,
            ):
                pass

        # Single instance
        with ServiceConnectorContext(
            connector_type=connector_type,
            auth_method="voice-print",
            resource_types=[resource_type_one],
            resource_id="aria",
            configuration=config,
            secrets=secrets,
        ):
            pass
