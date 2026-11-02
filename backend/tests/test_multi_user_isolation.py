import os
import re

import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database.base import Base
from app.database.dependencies import get_db

# Import models so SQLAlchemy registers their tables.
from app.models.user import User
from app.models.dataset import Dataset
from app.models.query_history import QueryHistory


# --------------------------------------------------
# TEST DATABASE CONFIGURATION
# --------------------------------------------------

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:password@localhost:5433/insightflow_test",
)

# Safety check: never run destructive test setup against
# the development or production database.
if not TEST_DATABASE_URL.rsplit("/", 1)[-1].split("?")[0] == "insightflow_test":
    raise RuntimeError(
        "Tests must use the dedicated insightflow_test database."
    )

test_engine = create_engine(
    TEST_DATABASE_URL,
    pool_pre_ping=True,
)

TestingSessionLocal = sessionmaker(
    bind=test_engine,
    autoflush=False,
    autocommit=False,
)


# --------------------------------------------------
# FIXTURES
# --------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """
    Create database tables before tests and remove them
    after the test session.
    """

    Base.metadata.create_all(bind=test_engine)

    yield

    # Drop dynamically generated dataset tables.
    inspector = inspect(test_engine)

    with test_engine.begin() as connection:
        for table_name in inspector.get_table_names():
            if re.fullmatch(r"dataset_[1-9]\d*", table_name):
                connection.execute(
                    text(
                        f'DROP TABLE IF EXISTS "{table_name}" CASCADE'
                    )
                )

    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


@pytest.fixture
def client():
    """
    Override FastAPI's database dependency so API requests
    use the isolated test database.
    """

    def override_get_db():
        db = TestingSessionLocal()

        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


# --------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------

def register_user(client, email, password):
    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": password,
        },
    )

    assert response.status_code == 201, response.text

    return response.json()


def login_user(client, email, password):
    response = client.post(
        "/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    assert response.status_code == 200, response.text

    token = response.json()["access_token"]

    return {
        "Authorization": f"Bearer {token}"
    }


# --------------------------------------------------
# MULTI-USER DATA ISOLATION TEST
# --------------------------------------------------

def test_multi_user_dataset_isolation(client):

    # ----------------------------------------------
    # 1. Register two users
    # ----------------------------------------------

    user_a_email = "user_a_test@example.com"
    user_b_email = "user_b_test@example.com"

    password = "StrongTestPassword123!"

    register_user(
        client,
        user_a_email,
        password,
    )

    register_user(
        client,
        user_b_email,
        password,
    )

    # ----------------------------------------------
    # 2. Login both users
    # ----------------------------------------------

    user_a_headers = login_user(
        client,
        user_a_email,
        password,
    )

    user_b_headers = login_user(
        client,
        user_b_email,
        password,
    )

    # ----------------------------------------------
    # 3. User A uploads a CSV dataset
    # ----------------------------------------------

    csv_content = (
        "product,region,revenue\n"
        "Laptop,North,50000\n"
        "Phone,South,30000\n"
        "Tablet,East,20000\n"
    )

    upload_response = client.post(
        "/datasets/upload",
        headers=user_a_headers,
        files={
            "file": (
                "sales.csv",
                csv_content,
                "text/csv",
            )
        },
    )

    assert upload_response.status_code == 200, upload_response.text

    upload_data = upload_response.json()

    dataset_id = upload_data["dataset_id"]

    assert upload_data["filename"] == "sales.csv"

    # ----------------------------------------------
    # 4. Verify owner_id in database
    # ----------------------------------------------

    db = TestingSessionLocal()

    try:
        dataset = (
            db.query(Dataset)
            .filter(Dataset.id == dataset_id)
            .first()
        )

        user_a = (
            db.query(User)
            .filter(User.email == user_a_email)
            .first()
        )

        user_b = (
            db.query(User)
            .filter(User.email == user_b_email)
            .first()
        )

        assert dataset is not None
        assert user_a is not None
        assert user_b is not None

        assert dataset.owner_id == user_a.id
        assert dataset.owner_id != user_b.id

    finally:
        db.close()

    # ----------------------------------------------
    # 5. User A accesses their own dataset
    # ----------------------------------------------

    owner_response = client.get(
        f"/datasets/{dataset_id}/preview",
        headers=user_a_headers,
    )

    assert owner_response.status_code == 200, owner_response.text

    # ----------------------------------------------
    # 6. User B attempts to access User A's dataset
    # ----------------------------------------------

    unauthorized_response = client.get(
        f"/datasets/{dataset_id}/preview",
        headers=user_b_headers,
    )

    assert unauthorized_response.status_code == 404

    assert unauthorized_response.json()["detail"] == (
        "Dataset not found."
    )

    # ----------------------------------------------
    # 7. Unauthenticated access is rejected
    # ----------------------------------------------

    unauthenticated_response = client.get(
        f"/datasets/{dataset_id}/preview"
    )

    assert unauthenticated_response.status_code == 401

        # ----------------------------------------------
    # 8. Schema isolation
    # ----------------------------------------------

    owner_schema_response = client.get(
        f"/datasets/{dataset_id}/schema",
        headers=user_a_headers,
    )

    assert owner_schema_response.status_code == 200, owner_schema_response.text

    other_user_schema_response = client.get(
        f"/datasets/{dataset_id}/schema",
        headers=user_b_headers,
    )

    assert other_user_schema_response.status_code == 404

    # ----------------------------------------------
    # 9. Profile isolation
    # ----------------------------------------------

    owner_profile_response = client.get(
        f"/datasets/{dataset_id}/profile",
        headers=user_a_headers,
    )

    assert owner_profile_response.status_code == 200, owner_profile_response.text

    other_user_profile_response = client.get(
        f"/datasets/{dataset_id}/profile",
        headers=user_b_headers,
    )

    assert other_user_profile_response.status_code == 404

    # ----------------------------------------------
    # 10. SQL query isolation
    # ----------------------------------------------

    query_payload = {
        "sql": f"SELECT * FROM dataset_{dataset_id}",
        "limit": 10,
    }

    owner_query_response = client.post(
        f"/datasets/{dataset_id}/query",
        headers=user_a_headers,
        json=query_payload,
    )

    assert owner_query_response.status_code == 200, owner_query_response.text

    other_user_query_response = client.post(
        f"/datasets/{dataset_id}/query",
        headers=user_b_headers,
        json=query_payload,
    )

    assert other_user_query_response.status_code == 404

    # ----------------------------------------------
    # 11. AI question isolation
    # ----------------------------------------------

    ask_payload = {
        "question": "What is the total revenue?",
        "limit": 10,
    }

    other_user_ask_response = client.post(
        f"/datasets/{dataset_id}/ask",
        headers=user_b_headers,
        json=ask_payload,
    )

    assert other_user_ask_response.status_code == 404

    # ----------------------------------------------
    # 12. Query history isolation
    # ----------------------------------------------

    owner_history_response = client.get(
        f"/datasets/{dataset_id}/history",
        headers=user_a_headers,
    )

    assert owner_history_response.status_code == 200, owner_history_response.text

    other_user_history_response = client.get(
        f"/datasets/{dataset_id}/history",
        headers=user_b_headers,
    )

    assert other_user_history_response.status_code == 404