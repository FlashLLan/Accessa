import re

from sqlalchemy.orm import Session

from backend.models.workspace import SLUG_MAX_LENGTH, SLUG_MIN_LENGTH, Workspace

# Same rule as the ck_workspaces_slug_format CHECK constraint in the database.
SLUG_PATTERN = re.compile(rf"^[a-z0-9][a-z0-9-]{{{SLUG_MIN_LENGTH - 2},{SLUG_MAX_LENGTH - 2}}}[a-z0-9]$")

# Slugs that would collide with application routes or look official.
RESERVED_SLUGS = frozenset({
    "admin", "api", "login", "signup", "w", "www", "static", "assets", "health", "docs",
})


def normalize_slug(raw: str) -> str:
    return raw.strip().lower()


def slug_error(slug: str) -> str | None:
    """Return a human-readable reason why `slug` is not allowed, or None if it is valid."""
    if not SLUG_PATTERN.match(slug):
        return (
            f"Workspace address must be {SLUG_MIN_LENGTH}-{SLUG_MAX_LENGTH} characters of "
            "lowercase letters, digits and '-', and cannot start or end with '-'."
        )
    if slug in RESERVED_SLUGS:
        return "This workspace address is reserved. Please choose another one."
    return None


def get_workspace_by_slug(db: Session, slug: str) -> Workspace | None:
    return db.query(Workspace).filter(Workspace.slug == normalize_slug(slug)).first()


def create_workspace(db: Session, name: str, slug: str) -> Workspace:
    """Create a workspace. public_id is a random UUIDv4 set by the model. Flushes but does not commit."""
    workspace = Workspace(name=name, slug=slug)
    db.add(workspace)
    db.flush()
    return workspace
