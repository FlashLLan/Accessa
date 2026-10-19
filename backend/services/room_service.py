from sqlalchemy.orm import Session

from backend.models.room import Room, generate_room_public_id


def create_room(db: Session, name: str) -> Room:
    """Create a room with a fresh random public id. Flushes but does not commit."""
    public_id = generate_room_public_id()
    while db.query(Room.id).filter(Room.public_id == public_id).first():
        public_id = generate_room_public_id()

    room = Room(name=name, public_id=public_id)
    db.add(room)
    db.flush()
    return room
