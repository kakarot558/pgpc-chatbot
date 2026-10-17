import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.database.database import Base
from app.models import Employee, Office, Position, Room


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_all_tables_exist():
    expected = {"users", "employees", "positions", "offices", "rooms", "facilities", "handbook_sections",
                "school_history", "faqs", "library_books", "documents", "knowledge_chunks",
                "chat_sessions", "chat_messages"}
    assert expected <= set(Base.metadata.tables)


def test_employee_links_to_position(db):
    pos = Position(name="Test Position")
    db.add(pos); db.flush()
    db.add(Employee(first_name="A", last_name="B", position_id=pos.id)); db.commit()
    assert db.query(Employee).one().position.name == "Test Position"


def test_duplicate_office_name_rejected(db):
    db.add(Office(name="X")); db.commit()
    db.add(Office(name="X"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_duplicate_room_in_same_building_rejected(db):
    db.add(Room(room_number="101", building="A")); db.commit()
    db.add(Room(room_number="101", building="A"))
    with pytest.raises(IntegrityError):
        db.commit()
