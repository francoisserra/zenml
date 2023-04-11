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
"""AWS Service Connector.

The AWS Service Connector implements various authentication methods for AWS
services:

- AWS secret key (access key, secret key)
- AWS STS tokens (access key, secret key, session token)
- IAM roles (i.e. generating temporary STS tokens on the fly by assuming an
IAM role)

Best practices:

- development: use the AWS secret key associated with your AWS account
- production environment: apply the principle of least privilege by configuring
different IAM roles for each AWS service that you use, and use the IAM role
authentication method to generate temporary STS token credentials. This has the
limitation that STS tokens are only valid for a short period of time,
e.g. 12 hours and need to be refreshed periodically. If the
connector consumer is a long-running process like a kubernetes cluster that
needs authenticated access to the ECR registry, the credentials need to be
refreshed periodically by means outside of the service consumer, or the
consumer needs to poll ZenML for new credentials on every authentication
attempt, or ZenML needs to implement an asynchronous periodic refresh mechanism
outside of the interaction between the service consumer and the service
connector.
"""
import base64
import re
import tempfile
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError
from botocore.signers import RequestSigner
from pydantic import SecretStr

from zenml.exceptions import AuthorizationException
from zenml.models import (
    AuthenticationMethodSpecificationModel,
    ResourceTypeSpecificationModel,
    ServiceConnectorSpecificationModel,
)
from zenml.service_connectors.service_connector import (
    AuthenticationConfig,
    ServiceConnector,
)
from zenml.utils.enum_utils import StrEnum


class DockerCredentials(AuthenticationConfig):
    """Docker client authentication credentials."""

    username: SecretStr
    password: SecretStr


DOCKER_RESOURCE_TYPE = "docker"


class KubernetesCredentials(AuthenticationConfig):
    """Kubernetes authentication config."""

    certificate_authority: SecretStr
    server: SecretStr
    client_certificate: SecretStr
    client_key: SecretStr


KUBERNETES_RESOURCE_TYPE = "kubernetes"
# ----------------------------------

AWS_CONNECTOR_TYPE = "aws"
AWS_RESOURCE_TYPE = "aws"


class AWSSecretKey(AuthenticationConfig):
    """AWS secret key credentials."""

    aws_access_key_id: SecretStr
    aws_secret_access_key: SecretStr


class STSToken(AWSSecretKey):
    """AWS STS token."""

    aws_session_token: SecretStr


class AWSBaseConfig(AWSSecretKey):
    """AWS base configuration."""

    region: Optional[str] = None
    endpoint_url: Optional[str] = None


class AWSSecretKeyConfig(AWSBaseConfig, AWSSecretKey):
    """AWS secret key authentication configuration."""


class STSTokenConfig(AWSBaseConfig, STSToken):
    """AWS STS token authentication configuration."""


class IAMRoleAuthenticationConfig(AWSSecretKeyConfig):
    """AWS IAM authentication config."""

    role_arn: str
    expiration_seconds: Optional[int] = None


class AWSAuthenticationMethods(StrEnum):
    """AWS Authentication methods."""

    SECRET_KEY = "AWS secret key"
    STS_TOKEN = "AWS STS token"
    IAM_ROLE = "AWS IAM role"


AWS_SERVICE_CONNECTOR_SPECIFICATION = ServiceConnectorSpecificationModel(
    type=AWS_CONNECTOR_TYPE,
    description="""
This ZenML AWS service connector facilitates connecting to, authenticating to
and accessing AWS services, from S3 buckets to EKS clusters. Explicit long-term
AWS credentials are supported, as well as temporary credentials such as STS
tokens or IAM roles. The connector also allows configuration of local Docker and
Kubernetes clients as well as auto-configuration by discovering and loading
credentials stored on a local environment.

The connector supports the following authentication methods:

- `AWS secret key`: uses long-term AWS credentials consisting of an access key
ID and secret access key. This method is preferred during development and
testing due to its simplicity and ease of use. It is not recommended for
production use due to the risk of long-term credentials being exposed. The IAM
roles method is preferred for production, unless there are specific reasons to
use long-term credentials (e.g. an external client or long-running process is
involved and it is not possible to periodically regenerate temporary credentials
upon expiration).

- `AWS STS token`: uses temporary STS tokens explicitly generated by the user or
auto-configured from a local environment. This method has the major limitation
that the user must regularly generate new tokens and update the connector
configuration as STS tokens expire. This method is best used in cases where the
connector only needs to be used for a short period of time.

- `AWS IAM role`: generates temporary STS credentials by assuming an IAM role.
This is the recommended method for production use. The connector needs to be
configured with an IAM role accompanied by an access key ID and secret access
key that have permission to assume the IAM role. The connector will then
generate new temporary STS tokens upon request. This method might not be
suitable in cases where the consumer cannot re-generate temporary credentials
upon expiration (e.g. an external client or long-running process is involved).

The connector facilitates access to any AWS service, including S3, ECR, EKS,
EC2, etc. by providing pre-configured boto3 clients for these services. In
addition to authenticating to AWS services, the connector also supports
authentication for Docker and Kubernetes clients. This is reflected in the range
of resource types supported by the connector:

- the connector supports any of the well known AWS service names as a resource
type. The AWS service name must be one of the values listed in the boto3
documentation (e.g. "s3", "secretsmanager", "sagemaker"):
https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/index.html
When this resource type is used, the connector provides to consumers a boto3
client specifically configured for the specified service.

- `docker`: this is an alternative to the AWS ECR service that allows consumers
to discover this connector as a Docker client provider. When used by connector
consumers, they are provided a pre-authenticated python-docker client instance
instead of a boto3 client.

- `kubernetes`: this is an alternative to the AWS EKS service that allows
consumers to discover this connector as a Docker client provider. When used by
connector consumers, they are issued a pre-authenticated python-kubernetes
client instance instead of a boto3 client.

- `aws`: this is a special multi-purpose AWS resource type. It allows consumers
to use the connector to connect to any AWS service. When used by connector
consumers, they are provided a generic boto3 session instance pre-configured
with AWS credentials. This session can then be used to create boto3 clients
for any particular AWS service.
""",
    auth_methods=[
        AuthenticationMethodSpecificationModel(
            auth_method=AWSAuthenticationMethods.SECRET_KEY,
            description="Uses long-term AWS credentials consisting of an "
            "access key ID and secret access key.",
            config_class=AWSSecretKeyConfig,
        ),
        AuthenticationMethodSpecificationModel(
            auth_method=AWSAuthenticationMethods.STS_TOKEN,
            description="Uses temporary STS tokens explicitly generated by "
            "the user or auto-configured from a local environment.",
            config_class=STSTokenConfig,
        ),
        AuthenticationMethodSpecificationModel(
            auth_method=AWSAuthenticationMethods.IAM_ROLE,
            description="Generates temporary STS credentials by assuming an "
            "IAM role.",
            config_class=IAMRoleAuthenticationConfig,
        ),
    ],
    resource_types=[
        ResourceTypeSpecificationModel(
            resource_types=[svc],
            description=f"{svc} AWS resource.",
            auth_methods=AWSAuthenticationMethods.values(),
            # Request an AWS specific resource instance ID (e.g. an S3
            # bucket name, ECR repository name) to be configured in the
            # connector or provided by the consumer
            multi_instance=True,
            logo_url="https://public-flavor-logos.s3.eu-central-1.amazonaws.com/container_registry/aws.png",
        )
        for svc in boto3.Session().get_available_services()
        if svc not in ["ecr", "eks"]
    ]
    + [
        ResourceTypeSpecificationModel(
            resource_types=[AWS_RESOURCE_TYPE],
            description="Any AWS resource.",
            auth_methods=AWSAuthenticationMethods.values(),
            # Don't request an AWS specific resource instance ID, given that
            # the connector provides a generic boto3 session instance.
            multi_instance=False,
            logo_url="https://public-flavor-logos.s3.eu-central-1.amazonaws.com/container_registry/aws.png",
        ),
        ResourceTypeSpecificationModel(
            resource_types=[KUBERNETES_RESOURCE_TYPE, "eks"],
            description="EKS Kubernetes cluster.",
            auth_methods=AWSAuthenticationMethods.values(),
            # Request an EKS cluster name to be configured in the
            # connector or provided by the consumer
            multi_instance=True,
            logo_url="https://public-flavor-logos.s3.eu-central-1.amazonaws.com/orchestrator/kubernetes.png",
        ),
        ResourceTypeSpecificationModel(
            resource_types=[DOCKER_RESOURCE_TYPE, "ecr"],
            description="ECR container registry.",
            auth_methods=AWSAuthenticationMethods.values(),
            # Request an ECR registry to be configured in the
            # connector or provided by the consumer
            multi_instance=True,
        ),
    ],
)


class AWSServiceConnector(ServiceConnector):
    """AWS service connector."""

    config: AWSBaseConfig

    @classmethod
    def get_specification(cls) -> ServiceConnectorSpecificationModel:
        """Get the service connector specification.

        Returns:
            The service connector specification.
        """
        return AWS_SERVICE_CONNECTOR_SPECIFICATION

    @classmethod
    def _get_eks_bearer_token(
        cls, session: boto3.Session, cluster_id: str, region: str
    ) -> str:
        """Generate a bearer token for authenticating to the EKS API server.

        Based on: https://github.com/kubernetes-sigs/aws-iam-authenticator/blob/master/README.md#api-authorization-from-outside-a-cluster

        Args:
            session: An authenticated boto3 session to use for generating the
                token.
            cluster_id: The name of the EKS cluster.
            region: The AWS region the EKS cluster is in.

        Returns:
            A bearer token for authenticating to the EKS API server.
        """
        STS_TOKEN_EXPIRES_IN = 60

        client = session.client("sts", region_name=region)
        service_id = client.meta.service_model.service_id

        signer = RequestSigner(
            service_id,
            region,
            "sts",
            "v4",
            session.get_credentials(),
            session.events,
        )

        params = {
            "method": "GET",
            "url": f"https://sts.{region}.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15",
            "body": {},
            "headers": {"x-k8s-aws-id": cluster_id},
            "context": {},
        }

        signed_url = signer.generate_presigned_url(
            params,
            region_name=region,
            expires_in=STS_TOKEN_EXPIRES_IN,
            operation_name="",
        )

        base64_url = base64.urlsafe_b64encode(
            signed_url.encode("utf-8")
        ).decode("utf-8")

        # remove any base64 encoding padding:
        return "k8s-aws-v1." + re.sub(r"=*", "", base64_url)

    def _connect_to_resource(
        self,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        """Authenticate and connect to an AWS resource.

        Initialize and return a session or client object depending on the
        connector configuration and the requested resource type:

        - initialize and return a boto3 session if the requested resource type
        is a generic AWS resource
        - initialize and return a boto3 client for an AWS service
        - initialize and return a python-docker client if the requested resource
        type is a Docker registry
        - initialize and return a python-kubernetes client if the requested
        resource type is a Kubernetes cluster

        Args:
            config: The connector configuration.
            resource_type: The type of resource to connect to.
            resource_id: The ID of the AWS resource to connect to.
            kwargs: Additional implementation specific keyword arguments to pass
                to the session or client constructor.

        Returns:
            A boto3 session or client object for AWS resources, a python-docker
            client object for Docker registries, or a python-kubernetes client
            object for Kubernetes clusters.

        Raises:
            AuthorizationException: If authentication failed.
            NotImplementedError: If the connector instance does not support
                connecting to the indicated resource type or client type.
        """
        # Regardless of the resource type, we must authenticate to AWS first
        # before we can connect to any AWS resource
        auth_method = self.auth_method
        cfg = self.config
        if auth_method == AWSAuthenticationMethods.SECRET_KEY:
            assert isinstance(cfg, AWSSecretKeyConfig)
            # Create a boto3 session using long-term AWS credentials
            session = boto3.Session(
                aws_access_key_id=cfg.aws_access_key_id.get_secret_value(),
                aws_secret_access_key=cfg.aws_secret_access_key.get_secret_value(),
                region_name=self.config.region,
            )
        elif auth_method == AWSAuthenticationMethods.STS_TOKEN:
            assert isinstance(cfg, STSTokenConfig)
            # Create a boto3 session using a temporary AWS STS token
            session = boto3.Session(
                aws_access_key_id=cfg.aws_access_key_id.get_secret_value(),
                aws_secret_access_key=cfg.aws_secret_access_key.get_secret_value(),
                aws_session_token=cfg.aws_session_token.get_secret_value(),
                region_name=self.config.region,
            )
        elif auth_method == AWSAuthenticationMethods.IAM_ROLE:
            assert isinstance(cfg, IAMRoleAuthenticationConfig)
            # Create a boto3 session using an IAM role
            session = boto3.Session(
                aws_access_key_id=cfg.aws_access_key_id.get_secret_value(),
                aws_secret_access_key=cfg.aws_secret_access_key.get_secret_value(),
                region_name=self.config.region,
            )

            sts = session.client("sts")
            try:
                response = sts.assume_role(
                    RoleArn=cfg.role_arn,
                )
            except ClientError as e:
                raise AuthorizationException(
                    f"Failed to assume IAM role {cfg.role_arn} "
                    f"using the AWS credentials configured in the connector: "
                    f"{e}"
                ) from e

            session = boto3.Session(
                aws_access_key_id=response["Credentials"]["AccessKeyId"],
                aws_secret_access_key=response["Credentials"][
                    "SecretAccessKey"
                ],
                aws_session_token=response["Credentials"]["SessionToken"],
            )
        else:
            raise NotImplementedError(
                f"Authentication method '{auth_method}' is not supported by "
                "the AWS connector."
            )

        if resource_type == AWS_RESOURCE_TYPE:
            return session

        region_id: Optional[str] = None
        if resource_type == DOCKER_RESOURCE_TYPE:
            from docker import DockerClient

            resource_id = resource_id or self.resource_id
            if not resource_id:
                raise ValueError(
                    "The AWS connector was not configured with an ECR "
                    "repository ID and one was not provided at runtime."
                )

            # The resource ID could mean different things:
            #
            # - an ECR repository ARN
            # - an ECR repository URI
            # - an ECR registry ID
            # - the ECR repository name
            #
            # We need to extract the registry ID and region ID from the provided
            # resource ID
            registry_id: Optional[str] = None
            registry_name: Optional[str] = None
            if re.match(
                r"^arn:aws:ecr:[a-z0-9-]+:\d{12}:repository(/.*)*$",
                resource_id,
            ):
                # The resource ID is an ECR repository ARN
                registry_id = resource_id.split(":")[4]
                region_id = resource_id.split(":")[3]
            elif re.match(
                r"^(https://)?\d{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com(/.*)*$",
                resource_id,
            ):
                # The resource ID is an ECR repository URI
                registry_id = resource_id.split(".")[0].split("/")[-1]
                region_id = resource_id.split(".")[3]
            elif re.match(r"^\d{12}$", resource_id):
                # The resource ID is an ECR registry ID
                registry_id = resource_id
                region_id = self.config.region
            elif re.match(
                r"^([a-z0-9]+([._-][a-z0-9]+)*/)*[a-z0-9]+([._-][a-z0-9]+)*$",
                resource_id,
            ):
                # Assume the resource ID is an ECR repository name
                region_id = self.config.region
                registry_name = resource_id
            else:
                raise ValueError(
                    f"Invalid resource ID for a ECR registry: {resource_id}. "
                    f"Supported formats are:\n"
                    f"ECR repository ARN: arn:aws:ecr:[region]:[account-id]:repository/[repository-name]\n"
                    f"ECR repository URI: [https://][account-id].dkr.ecr.[region].amazonaws.com/[repository-name]\n"
                    f"ECR registry ID: [account-id]\n"
                    f"ECR repository name: [repository-name]"
                )

            # If the connector is configured with a region and the resource ID
            # is an ECR repository ARN or URI that specifies a different region
            # we raise an error
            if (
                self.config.region
                and region_id
                and region_id != self.config.region
            ):
                raise AuthorizationException(
                    f"The AWS region for the {resource_id} ECR registry "
                    f"({region_id}) does not match the region configured in "
                    f"the connector ({self.config.region})."
                )

            if not region_id:
                raise ValueError(
                    f"The AWS region for the ECR registry was not configured "
                    f"in the connector and could not be determined from the "
                    f"provided resource ID: {resource_id}"
                )

            client = session.client("ecr", region_name=self.config.region)

            if registry_name:
                # Get the registry ID from the repository name
                try:
                    repositories = client.describe_repositories(
                        repositoryNames=[
                            registry_name,
                        ]
                    )
                except ClientError as e:
                    raise AuthorizationException(
                        f"Failed to get ECR registry ID from ECR repository name: {e}"
                    ) from e

                registry_id = repositories["repositories"][0]["registryId"]

            try:
                auth_token = client.get_authorization_token(
                    registryIds=[
                        registry_id,
                    ]
                )
            except ClientError as e:
                raise AuthorizationException(
                    f"Failed to get authorization token from ECR: {e}"
                ) from e

            token = auth_token["authorizationData"][0]["authorizationToken"]
            endpoint = auth_token["authorizationData"][0]["proxyEndpoint"]
            # The token is base64 encoded and has the format
            # "username:password"
            username, token = (
                base64.b64decode(token).decode("utf-8").split(":")
            )

            docker_client = DockerClient.from_env()
            docker_client.login(
                username=username,
                password=token,
                registry=endpoint,
                reauth=True,
            )
            return docker_client

        if resource_type == KUBERNETES_RESOURCE_TYPE:
            from kubernetes import client as k8s_client

            resource_id = resource_id or self.resource_id
            if not resource_id:
                raise ValueError(
                    "The AWS connector was not configured with an EKS "
                    "cluster ID and one was not provided at runtime."
                )

            # The resource ID could mean different things:
            #
            # - an EKS cluster ARN
            # - an EKS cluster ID
            #
            # We need to extract the cluster name and region ID from the
            # provided resource ID
            cluster_name: Optional[str] = None
            if re.match(
                r"^arn:aws:eks:[a-z0-9-]+:\d{12}:cluster/.+$",
                resource_id,
            ):
                # The resource ID is an EKS cluster ARN
                cluster_name = resource_id.split("/")[-1]
                region_id = resource_id.split(":")[3]
            elif re.match(
                r"^[a-z0-9]+[a-z0-9_-]*$",
                resource_id,
            ):
                # Assume the resource ID is an EKS cluster name
                region_id = self.config.region
                registry_name = resource_id
            else:
                raise ValueError(
                    f"Invalid resource ID for a EKS cluster: {resource_id}. "
                    f"Supported formats are:\n"
                    f"EKS cluster ARN: arn:aws:eks:[region]:[account-id]:cluster/[cluster-name]\n"
                    f"ECR cluster name: [cluster-name]"
                )

            # If the connector is configured with a region and the resource ID
            # is an EKS registry ARN or URI that specifies a different region
            # we raise an error
            if (
                self.config.region
                and region_id
                and region_id != self.config.region
            ):
                raise AuthorizationException(
                    f"The AWS region for the {resource_id} EKS cluster "
                    f"({region_id}) does not match the region configured in "
                    f"the connector ({self.config.region})."
                )

            region_id = self.config.region
            cluster_name = resource_id

            if not region_id:
                raise ValueError(
                    f"The AWS region for the ECR registry was not configured "
                    f"in the connector and could not be determined from the "
                    f"provided resource ID: {resource_id}"
                )

            client = session.client("eks", region_name=self.config.region)
            try:
                cluster = client.describe_cluster(name=cluster_name)
            except ClientError as e:
                raise AuthorizationException(
                    f"Failed to get EKS cluster {cluster_name}: {e}"
                ) from e

            try:
                token = self._get_eks_bearer_token(
                    session=session,
                    cluster_id=cluster_name,
                    region=region_id,
                )
            except ClientError as e:
                raise AuthorizationException(
                    f"Failed to get EKS bearer token: {e}"
                ) from e

            # get cluster details
            cluster_cert = cluster["cluster"]["certificateAuthority"]["data"]
            cluster_ep = cluster["cluster"]["endpoint"]

            # TODO: choose a more secure location for the temporary file
            # and use the right permissions

            with tempfile.NamedTemporaryFile(delete=False) as fp:
                ca_filename = fp.name
                cert_bs = base64.urlsafe_b64decode(
                    cluster_cert.encode("utf-8")
                )
                fp.write(cert_bs)

            conf = k8s_client.Configuration()
            conf.host = cluster_ep
            conf.api_key["authorization"] = token
            conf.api_key_prefix["authorization"] = "Bearer"
            conf.ssl_ca_cert = ca_filename

            return k8s_client.ApiClient(conf)

        if not resource_type:
            # If no AWS resource type is specified, return the generic boto3
            # session
            return session

        return session.client(
            resource_type,
            region_name=self.config.region,
            endpoint_url=self.config.endpoint_url,
        )

    def _configure_local_client(
        self,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Configure a local client to authenticate and connect to a resource.

        This method uses the connector's configuration to configure a local
        client or SDK installed on the localhost for the indicated resource.

        Args:
            resource_type: The type of resource to connect to. Can be different
                than the resource type that the connector is configured to
                access if alternative resource types or arbitrary
                resource types are allowed by the connector configuration.
            resource_id: The ID of the resource to connect to. Omitted if the
                configured resource type does not allow multiple instances.
                Can be different than the resource ID that the connector is
                configured to access if resource ID aliases or wildcards
                are supported.
            kwargs: Additional implementation specific keyword arguments to use
                to configure the client.

        Raises:
            AuthorizationException: If authentication failed.
            NotImplementedError: If the connector instance does not support
                local configuration for the indicated resource type or client
                type.
        """
        # # # build the cluster config hash
        # cluster_config = {
        #         "apiVersion": "v1",
        #         "kind": "Config",
        #         "clusters": [
        #             {
        #                 "cluster": {
        #                     "server": str(cluster_ep),
        #                     "certificate-authority-data": str(cluster_cert)
        #                 },
        #                 "name": "kubernetes"
        #             }
        #         ],
        #         "contexts": [
        #             {
        #                 "context": {
        #                     "cluster": "kubernetes",
        #                     "user": "aws"
        #                 },
        #                 "name": "aws"
        #             }
        #         ],
        #         "current-context": "aws",
        #         "preferences": {},
        #         "users": [
        #             {
        #                 "name": "aws",
        #                 "user": {
        #                     "exec": {
        #                         "apiVersion": "client.authentication.k8s.io/v1alpha1",
        #                         "command": "heptio-authenticator-aws",
        #                         "args": [
        #                             "token", "-i", cluster_name
        #                         ]
        #                     }
        #                 }
        #             }
        #         ]
        #     }

    @classmethod
    def _auto_configure(
        cls,
        auth_method: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        region_name: Optional[str] = None,
        profile_name: Optional[str] = None,
        **kwargs: Any,
    ) -> "AWSServiceConnector":
        """Auto-configure the connector.

        Instantiate an AWS connector with a configuration extracted from the
        authentication configuration available in the environment (e.g.
        environment variables or local AWS client/SDK configuration files).

        Args:
            auth_method: The particular authentication method to use. If not
                specified, the connector implementation must decide which
                authentication method to use or raise an exception.
            resource_type: The type of resource to configure. The implementation
                may choose to either require or ignore this parameter if it
                does not support or is able to detect a resource type and the
                connector specification does not allow arbitrary resource types.
            resource_id: The ID of the resource to configure. The
                implementation may choose to either require or ignore this
                parameter if it does not support or detect an resource type that
                supports multiple instances.
            region_name: The name of the AWS region to use. If not specified,
                the implicit region is used.
            profile_name: The name of the AWS profile to use. If not specified,
                the implicit profile is used.
            kwargs: Additional implementation specific keyword arguments to use.

        Returns:
            An AWS connector instance configured with authentication credentials
            automatically extracted from the environment.
        """
        # Initialize an AWS session with the default configuration loaded
        # from the environment.
        session = boto3.Session(
            profile_name=profile_name, region_name=region_name
        )

        # Extract the AWS credentials from the session and store them in
        # the connector secrets.
        credentials = session.get_credentials()
        auth_method = AWSAuthenticationMethods.SECRET_KEY
        auth_config: AWSBaseConfig
        if credentials.token:
            auth_method = AWSAuthenticationMethods.STS_TOKEN
            auth_config = STSTokenConfig(
                region=session.region_name,
                endpoint_url=session._session.get_config_variable(
                    "endpoint_url"
                ),
                aws_access_key_id=credentials.access_key,
                aws_secret_access_key=credentials.secret_key,
                aws_session_token=credentials.token,
            )
        else:
            auth_config = AWSSecretKeyConfig(
                region=session.region_name,
                endpoint_url=session._session.get_config_variable(
                    "endpoint_url"
                ),
                aws_access_key_id=credentials.access_key,
                aws_secret_access_key=credentials.secret_key,
            )

        return cls(
            auth_method=auth_method,
            resource_type=resource_type or AWS_RESOURCE_TYPE,
            resource_id=resource_id,
            config=auth_config,
        )
