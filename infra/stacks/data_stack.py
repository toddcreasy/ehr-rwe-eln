import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_rds as rds
from aws_cdk import aws_s3 as s3
from constructs import Construct


class DataStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Isolated subnets hold Aurora: no NAT, no internet route. Local access goes through the
        # Data API. Public subnets hold the ECS Express load balancer and tasks (BackendStack).
        # Public is listed second so CDK keeps the isolated subnets' existing address ranges.
        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="isolated", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED, cidr_mask=24
                ),
                ec2.SubnetConfiguration(
                    name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24
                ),
            ],
        )

        self.cluster = rds.DatabaseCluster(
            self,
            "Database",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_17_9
            ),
            writer=rds.ClusterInstance.serverless_v2("writer"),
            serverless_v2_min_capacity=0,
            serverless_v2_max_capacity=1,
            credentials=rds.Credentials.from_generated_secret("postgres"),
            default_database_name="ehr_rwe_eln",
            enable_data_api=True,
            storage_encrypted=True,
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
        )

        self.documents_bucket = s3.Bucket(
            self,
            "DocumentsBucket",
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            lifecycle_rules=[
                s3.LifecycleRule(
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                            transition_after=cdk.Duration.days(30),
                        )
                    ]
                )
            ],
        )

        cdk.CfnOutput(self, "DatabaseSecretArn", value=self.cluster.secret.secret_arn)
        cdk.CfnOutput(self, "DatabaseClusterArn", value=self.cluster.cluster_arn)
        cdk.CfnOutput(self, "DocumentsBucketName", value=self.documents_bucket.bucket_name)
