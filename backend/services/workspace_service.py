from sqlalchemy.orm import Session

from backend.models.workspace import Workspace


def create_workspace(db: Session, name: str, slug: str) -> Workspace:
    """Create a workspace. public_id is a random UUIDv4 set by the model. Flushes but does not commit."""
    workspace = Workspace(name=name, slug=slug)
    db.add(workspace)
    db.flush()
    return workspace
