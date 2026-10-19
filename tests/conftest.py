from datetime import datetime
from itertools import count

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Integer, String, Text, create_engine, insert
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.core.dependencies import get_current_user
from backend.models.change_request import ChangeRequest
from backend.models.user import User
from backend.models.role import Role
from backend.models.room import Room
from backend.models.approval import Approval
from backend.models.enums import RequestStatus, RequestType, EnvironmentType, RiskLevel
from database.db import Base, get_db

TEST_DB_URL = "sqlite://"

engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    session = TestingSessionLocal()
    # Every test gets a default room (id=1); users without an explicit room land in it.
    session.add(Room(id=1, public_id="100000000001", name="Default Test Room"))
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.state.limiter.enabled = False
    with TestClient(app) as test_client:
        yield test_client
    app.state.limiter.enabled = True
    app.dependency_overrides.clear()


_unique = count(1)


def _guess_required_value(column_name, column_type, *, label="x", role_id=None):
    idx = next(_unique)
    name = column_name.lower()

    if role_id is not None and name == "role_id":
        return role_id

    if isinstance(column_type, Boolean):
        return True

    if isinstance(column_type, DateTime):
        return datetime.utcnow()

    if isinstance(column_type, Integer):
        return 1

    if isinstance(column_type, SAEnum):
        enum_class = getattr(column_type, "enum_class", None)
        if enum_class is not None:
            return next(iter(enum_class))
        return column_type.enums[0]

    if "email" in name:
        return f"{label}{idx}@example.com"
    if "username" in name:
        return f"{label}_{idx}"
    if "full_name" in name or name == "name":
        return f"{label.capitalize()} {idx}"
    if "password" in name or "hash" in name:
        return "hashed_password_for_tests"
    if "description" in name:
        return f"{label} description {idx}"
    if isinstance(column_type, (String, Text)):
        return f"{label}_{column_name}_{idx}"

    return f"{label}_{idx}"


def _insert_row(db, model, *, overrides=None, label="x"):
    overrides = overrides or {}
    table = model.__table__

    values = {}
    for column in table.columns:
        if column.name in overrides:
            values[column.name] = overrides[column.name]
            continue

        if column.primary_key and column.autoincrement:
            continue

        if column.default is not None or column.server_default is not None:
            continue

        if column.nullable:
            continue

        values[column.name] = _guess_required_value(
            column.name,
            column.type,
            label=label,
            role_id=overrides.get("role_id"),
        )

    result = db.execute(insert(table).values(**values))
    db.commit()

    pk = result.inserted_primary_key[0]
    return db.get(model, pk)


@pytest.fixture
def create_role():
    def _create_role(db, name, level=1):
        return _insert_row(db, Role, overrides={"name": name, "level": level}, label=name)
    return _create_role


@pytest.fixture
def create_room():
    def _create_room(db, name, public_id):
        room = Room(name=name, public_id=public_id)
        db.add(room)
        db.commit()
        db.refresh(room)
        return room
    return _create_room


@pytest.fixture
def create_user():
    def _create_user(db, *, role, label, room=None):
        user = _insert_row(
            db,
            User,
            overrides={"role_id": role.id, "room_id": room.id if room else 1},
            label=label,
        )
        db.refresh(user)
        return user
    return _create_user


def login_as(user):
    app.dependency_overrides[get_current_user] = lambda: user


@pytest.fixture
def login_user():
    return login_as


@pytest.fixture
def seed_change_request():
    def _seed_change_request(
        db,
        *,
        creator_id,
        reviewer_id,
        status=RequestStatus.DRAFT,
        title="Seeded request",
        risk_level=RiskLevel.LOW,
    ):
        req = ChangeRequest(
            title=title,
            description="Seeded description",
            request_type=next(iter(RequestType)),
            target_system="server-1",
            environment=next(iter(EnvironmentType)),
            risk_level=risk_level,
            status=status,
            created_by=creator_id,
            assigned_reviewer_id=reviewer_id,
            room_id=db.get(User, creator_id).room_id,
        )
        db.add(req)
        db.commit()
        db.refresh(req)
        return req
    return _seed_change_request