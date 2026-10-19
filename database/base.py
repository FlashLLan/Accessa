from sqlalchemy import MetaData
from sqlalchemy.orm import declarative_base

# Kept separate from db.py so tools that only need the models' metadata
# (Alembic) can import it without creating the application's engine.
#
# Deterministic constraint names, so migrations and `\d <table>` are readable
# and constraints can be dropped by name later.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

Base = declarative_base(metadata=MetaData(naming_convention=NAMING_CONVENTION))
