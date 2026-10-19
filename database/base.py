from sqlalchemy.orm import declarative_base

# Kept separate from db.py so tools that only need the models' metadata
# (Alembic) can import it without creating the application's engine.
Base = declarative_base()
