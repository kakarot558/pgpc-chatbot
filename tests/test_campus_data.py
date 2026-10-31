from app.database import campus_data


def test_constants_and_positions():
    assert campus_data.MAIN == "White Building"
    assert len(campus_data.POSITIONS) >= 20
    assert any("Registrar" in p for p in campus_data.POSITIONS)


def test_offices_have_building_and_rooms_listed():
    names = [o[0] for o in campus_data.OFFICES]
    assert "Office of the Registrar" in names
    assert any("Lecture Room" in str(r) or "LR" in str(r) for r in campus_data.ROOMS)


def test_admission_description_text_does_not_mention_registrar():
    adm = [o for o in campus_data.OFFICES if o[0] == "Admission Office"][0]
    assert "Registrar" not in (adm[4] or "")      # only the shared-room sentence may name it (kept out of search)
    assert adm[3] == "the Office of the Registrar"


def test_buildings_are_named_white_and_yellow():
    assert campus_data.MAIN == "White Building" and campus_data.BLDG2 == "Yellow Building"
    assert campus_data.GROUND == "1st floor"


def test_yellow_building_floors_follow_the_yellow_sheet():
    floors = {r[0]: r[3] for r in campus_data.ROOMS if r[2] == campus_data.BLDG2}
    for first in ("Crime Lab 1", "Ballistic Room", "Com Lab 1", "Com Lab 2"):
        assert floors[first] == campus_data.GROUND
    for second in ("Dark Room", "Interrogation Room", "Observation Room", "Moot Court", "DEPTAC"):
        assert floors[second] == campus_data.SECOND
    offices = {o[0]: o[2] for o in campus_data.OFFICES if o[1] == campus_data.BLDG2}
    assert set(offices.values()) == {campus_data.GROUND}


def test_directory_titles_match_the_personnel_directory():
    titles = {last: t for last, _f, t, _o in campus_data.ASSIGNMENTS}
    assert titles["Sebuc"] == "Program Chair of BSCS"
    assert "Program Chair of BECEd" not in campus_data.POSITIONS
    assert titles["Manalo"] == "OIC College President" and titles["Diaz"].startswith("Vice President for Administration")
    assert titles["Benedicto"] == titles["Sulabo"] == "Utility Staff"


def test_lecture_rooms_2_to_6_are_on_the_second_floor():
    floors = {r[0]: r[3] for r in campus_data.ROOMS}
    assert floors["LR 1"] == campus_data.GROUND
    assert all(floors[f"LR {n}"] == campus_data.SECOND for n in "23456")
    assert floors["C.R Male"] == campus_data.GROUND and floors["C.R Female (2nd floor)"] == campus_data.SECOND


def test_apply_migrates_an_older_database():
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    import app.models  # noqa: F401
    from app.database.database import Base
    from app.models import Office, Room
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        db.add_all([
            Office(name="Office of the Registrar", building="Main Building", floor="Ground floor", description="x"),
            Office(name="Guidance Office", building="Building 2", floor="2nd floor", description="x"),
            Room(room_number="Crime Lab 1", building="Building 2", floor="2nd floor"),
            Room(room_number="LR 3", building="Main Building", floor="Ground floor"),
            Room(room_number="CR (Building 2)", building="Building 2", floor="2nd floor"),
        ])
        db.commit()
        campus_data.apply(db); db.commit()
        reg = db.scalar(select(Office).where(Office.name == "Office of the Registrar"))
        assert (reg.building, reg.floor, reg.room_number) == ("White Building", "1st floor", "Registrar Office & Admission Office")
        g = db.scalar(select(Office).where(Office.name == "Guidance Office"))
        assert (g.building, g.floor) == ("Yellow Building", "1st floor")
        crime = db.scalar(select(Room).where(Room.room_number == "Crime Lab 1"))
        assert (crime.building, crime.floor) == ("Yellow Building", "1st floor")
        lr3 = db.scalar(select(Room).where(Room.room_number == "LR 3"))
        assert (lr3.building, lr3.floor) == ("White Building", "2nd floor")
        assert db.scalar(select(Room).where(Room.room_number == "CR (Building 2)")) is None
        before = campus_data.apply(db)
        assert before["rooms"] == 0 and before["rooms_moved"] == 0          # running it again changes nothing
