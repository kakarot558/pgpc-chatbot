"""Words students use that differ from the words used in PGPC documents.

TF-IDF only matches identical words, so "attendance" would never find the handbook section titled
"Absences and Tardiness". Each line below says: a question word -> handbook / record words that mean
the same thing. Matching ANY of them counts as matching the question word.

Keep it short and based on real PGPC wording (check the handbook before adding a line). Words must be
written in their lemmatized, lower-case form (singular: "absence", not "Absences").
"""
SYNONYMS: dict[str, list[str]] = {
    "attendance": ["absence", "absent", "tardiness", "tardy", "late"],
    "absent": ["absence", "attendance", "tardiness"],
    "cheat": ["dishonesty", "dishonest", "plagiarism", "copying"],
    "cheating": ["dishonesty", "dishonest", "plagiarism"],
    "plagiarize": ["plagiarism", "dishonesty"],
    "dress": ["uniform", "attire"],
    "attire": ["uniform", "dress"],
    "uniform": ["dress", "attire"],
    "penalty": ["sanction", "offense", "violation", "punishment"],
    "punishment": ["sanction", "penalty", "offense"],
    "rule": ["policy", "regulation", "guideline"],
    "regulation": ["rule", "policy"],
    "fail": ["failing", "failure", "drp", "inc"],
    "passing": ["pass", "passed"],
    "tuition": ["fee", "payment"],
    "fee": ["tuition", "payment"],
    "enrol": ["enrollment", "matriculation", "admission"],
    "enroll": ["enrollment", "matriculation", "admission"],
    "enrolment": ["enrollment", "matriculation"],
    "teacher": ["faculty", "instructor", "professor", "adviser"],
    "professor": ["faculty", "instructor", "teacher"],
    "instructor": ["faculty", "teacher", "professor"],
    "staff": ["personnel", "employee"],
    "employee": ["personnel", "staff"],
    "honor": ["honors", "latin", "awards", "awardee", "laude"],
    "graduate": ["graduation", "graduating"],
    "graduating": ["graduation", "graduate"],
    "shift": ["shifting", "transfer", "change"],
    "drop": ["dropping", "drp", "withdrawal"],
    "internship": ["practicum", "ojt", "training"],
    "ojt": ["practicum", "internship", "training"],
    "wifi": ["internet", "network"],
    "internet": ["wifi", "network"],
    "borrow": ["loan", "lending", "circulation"],
    "book": ["library", "collection"],
    "mission": ["vision", "objective"],
    "founded": ["establishment", "established", "establish"],
    "founder": ["establishment", "established"],
    "history": ["establishment", "background", "purpose"],
    "logo": ["seal", "emblem"],
    "phone": ["contact", "telephone", "number"],
    "contact": ["telephone", "phone", "email"],
    "cr": ["comfort", "restroom"],
    "restroom": ["comfort", "cr"],
    # "What time does the clinic open?" -> records that list hours (e.g. "Clinic Hours", operating_hours)
    "open": ["hour", "schedule"],
    "close": ["hour", "schedule"],
    "time": ["hour", "schedule"],
    "schedule": ["hour"],
}


# Added after real chat logs showed students using words the handbook does not (haircut vs "hair cut", ...).
_EXTRA = {
    "haircut": ["hair", "cut", "grooming"],
    "hair": ["haircut", "grooming"],
    "grooming": ["hair", "haircut", "appearance"],
    "enrollment": ["enroll", "registration", "matriculation", "register"],
    "register": ["registration", "enrollment", "enroll"],
    "registration": ["register", "enrollment", "matriculation"],
    "procedure": ["process", "step", "requirement"],
    "process": ["procedure", "step"],
    "step": ["procedure", "process"],
    "chair": ["chairperson", "chairman", "head", "coordinator"],
    "grade": ["grading", "gwa", "rating"],
    "gwa": ["grade", "average"],
    "scholarship": ["scholar", "financial", "assistance"],
    "late": ["tardiness", "tardy", "absence"],
    "id": ["identification"],
}
for _k, _v in _EXTRA.items():
    SYNONYMS.setdefault(_k, _v)
