from __future__ import annotations

import os

import boto3
import pytest
from moto import mock_aws


@pytest.fixture(autouse=True)
def aws_credentials():
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


@pytest.fixture
def aws(aws_credentials):
    with mock_aws():
        yield


@pytest.fixture
def tables(aws):
    os.environ["SESSIONS_TABLE"] = "Sessions"
    os.environ["PRODUCTS_TABLE"] = "Products"
    os.environ["RESERVATIONS_TABLE"] = "Reservations"
    os.environ["ORDERS_TABLE"] = "Orders"

    ddb = boto3.resource("dynamodb", region_name="us-east-1")

    ddb.create_table(
        TableName="Sessions",
        KeySchema=[{"AttributeName": "session_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "session_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.create_table(
        TableName="Products",
        KeySchema=[{"AttributeName": "product_id", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "product_id", "AttributeType": "S"},
            {"AttributeName": "catalog_pk", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[{
            "IndexName": "catalog-index",
            "KeySchema": [{"AttributeName": "catalog_pk", "KeyType": "HASH"}],
            "Projection": {"ProjectionType": "ALL"},
        }],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.create_table(
        TableName="Reservations",
        KeySchema=[{"AttributeName": "reservation_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "reservation_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.create_table(
        TableName="Orders",
        KeySchema=[{"AttributeName": "order_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "order_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb


@pytest.fixture
def admin_secret(aws):
    os.environ["ADMIN_SECRET_PARAM"] = "/botdef/admin-secret"
    client = boto3.client("ssm", region_name="us-east-1")
    client.put_parameter(Name="/botdef/admin-secret", Value="test-secret", Type="SecureString")
    return "test-secret"
