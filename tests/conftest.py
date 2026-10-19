"""Test setup: every test runs against a real PostgreSQL database.

- TEST_DATABASE_URL (required) decides *where* the tests run: host, port and
  database. The app connects there as the application role (accessa_app), so the
  same grants apply as in production, including the append-only audit_logs.
- The schema-owner role is used to create, migrate and truncate the test
  database. Only its username and password are taken from MIGRATION_DATABASE_URL
  (or TEST_MIGRATION_DATABASE_URL); host, port and database always come from
  TEST_DATABASE_URL. Creating/dropping the test database goes through the
  server's built-in "postgres" database on that same host.
- A connection guard on every SQLAlchemy engine (the app's, the tests', Alembic's)
  refuses any connection that is not to that host/port/test database, so a test
  run can never reach the development or production database.
- At session start the test database is dropped, re-created and built with
  `alembic upgrade head`; before each test all tables are truncated (as the owner;
  the app role may not TRUNCATE audit_logs) and identities restart.
"""
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from itertools import count
from pathlib import Path

import pytest
from dotenv import load_dotenv
from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Integer, String, Text, create_engine, event, insert, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    raise RuntimeError("TEST_DATABASE_URL is not set (see .env.example).")

_test_url = make_url(TEST_DATABASE_URL)
_owner_credentials_url = make_url(os.getenv("TEST_MIGRATION_DATABASE_URL") or os.environ["MIGRATION_DATABASE_URL"])
# Location from TEST_DATABASE_URL only; credentials from the owner URL.
_owner_test_url = _test_url.set(username=_owner_credentials_url.username, password=_owner_credentials_url.password)
_maintenance_url = _owner_test_url.set(database="postgres")

# The development database, remembered only so a test can prove it is unreachable.
DEV_DATABASE_URL = os.getenv("DATABASE_URL")

if not _test_url.drivername.startswith("postgresql"):
    raise RuntimeError("TEST_DATABASE_URL must point at PostgreSQL.")
# The test database is dropped and re-created: never let it be a real database.
if "test" not in (_test_url.database or "") or (
    DEV_DATABASE_URL and make_url(DEV_DATABASE_URL).database == _test_url.database
):
    raise RuntimeError(
        f"Refusing to use '{_test_url.database}' as the test database; "
        "its name must contain 'test' and differ from the main database."
    )

# --- connection guard -------------------------------------------------------------
_TEST_HOST = _test_url.host or "localhost"
_TEST_PORT = _test_url.port or 5432
_allowed_databases = {_test_url.database}


class ForbiddenDatabaseConnection(RuntimeError):
    pass


def _check_target(host, port, dbname):
    if host != _TEST_HOST or int(port or 5432) != _TEST_PORT or dbname not in _allowed_databases:
        raise ForbiddenDatabaseConnection(
            f"Tests may only connect to {_TEST_HOST}:{_TEST_PORT}/{_test_url.database}, "
            f"not {host}:{port or 5432}/{dbname}"
        )


@event.listens_for(Engine, "do_connect")
def _refuse_before_connecting(dialect, conn_rec, cargs, cparams):
    # Runs before the network connection is opened: a forbidden target is never contacted.
    _check_target(cparams.get("host"), cparams.get("port"), cparams.get("dbname"))


@event.listens_for(Engine, "connect")
def _verify_after_connecting(dbapi_connection, connection_record):
    # Second check on what the driver actually connected to (e.g. PG* env defaults).
    info = dbapi_connection.info
    try:
        _check_target(info.host, info.port, info.dbname)
    except ForbiddenDatabaseConnection:
        dbapi_connection.close()
        raise


@contextmanager
def _maintenance_connection():
    """Short-lived connection to the server's 'postgres' database, only to create
    or drop the test database."""
    _allowed_databases.add("postgres")
    engine = create_engine(_maintenance_url.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            yield conn
    finally:
        engine.dispose()
        _allowed_databases.discard("postgres")


# The application and Alembic only ever see the test database.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["MIGRATION_DATABASE_URL"] = _owner_test_url.render_as_string(hide_password=False)

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.core.dependencies import get_current_user  # noqa: E402
from backend.models.change_request import ChangeRequest  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.models.role import Role  # noqa: E402
from backend.models.workspace import Workspace  # noqa: E402
from backend.models.approval import Approval  # noqa: E402,F401
from backend.models.enums import RequestStatus, RequestType, EnvironmentType, RiskLevel  # noqa: E402
from database.db import Base, get_db  # noqa: E402

DEFAULT_WORKSPACE_SLUG = "default-test"

app_engine = create_engine(TEST_DATABASE_URL)
owner_engine = create_engine(_owner_test_url.render_as_string(hide_password=False))
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=app_engine)


def _run_migrations():
    from alembic import command
    from alembic.config import Config

    # alembic/env.py reads MIGRATION_DATABASE_URL, set above to the test database.
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")


@pytest.fixture(scope="session", autouse=True)
def test_database():
    name = _test_url.database
    with _maintenance_connection() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))

    _run_migrations()
    yield

    # Close every pool (including the application's own engine) so no session of
    # the app role is left that the owner would have to terminate.
    from database.db import engine as application_engine

    for engine in (app_engine, owner_engine, application_engine):
        engine.dispose()
    with _maintenance_connection() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def _truncate_all_tables():
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with owner_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="function")
def db():
    _truncate_all_tables()

    session = TestingSessionLocal()
    # Every test gets a default workspace; identities were reset, so it is id 1 and
    # users created without an explicit workspace land in it.
    default = Workspace(slug=DEFAULT_WORKSPACE_SLUG, name="Default Test Workspace")
    session.add(default)
    session.commit()
    assert default.id == 1
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def app_db_engine():
    """Engine connected as the application role, for database-level tests that
    bypass the API (composite FKs, audit_logs privileges)."""
    return app_engine


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
        return datetime.now(timezone.utc)

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
def create_workspace():
    def _create_workspace(db, name, slug):
        workspace = Workspace(name=name, slug=slug)
        db.add(workspace)
        db.commit()
        db.refresh(workspace)
        return workspace
    return _create_workspace


@pytest.fixture
def create_user():
    def _create_user(db, *, role, label, workspace=None):
        user = _insert_row(
            db,
            User,
            overrides={"role_id": role.id, "workspace_id": workspace.id if workspace else 1},
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
            workspace_id=db.get(User, creator_id).workspace_id,
        )
        db.add(req)
        db.commit()
        db.refresh(req)
        return req
    return _seed_change_request