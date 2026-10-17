"""The fixed question set must keep passing: it catches regressions after any change."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import seed
from app.database.database import Base
from app.models import HandbookSection
from app.services import retrieval as rv
from app.services.answer_generator import generate_answer
import csv
from ml.evaluation.run_answer_eval import FILE


@pytest.fixture(scope="module")
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        for r in seed.parse_handbook(seed.HANDBOOK_FILE.read_text(encoding="utf-8", errors="replace")):
            s.add(HandbookSection(source_document=seed.HANDBOOK_SOURCE, **r))
        seed.seed_employees(s)
        seed.seed_offices(s)
        s.commit()
        rv.clear_index_cache()
        yield s
    rv.clear_index_cache()


def test_every_question_in_the_fixed_set_still_gets_its_expected_answer(db):
    rows = list(csv.DictReader(FILE.open(encoding="utf-8")))
    assert len(rows) >= 30
    wrong = [r["question"] for r in rows if r["expected"].lower() not in generate_answer(db, r["question"]).text.lower()]
    assert wrong == [], f"regressions: {wrong}"
