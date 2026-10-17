"""Builds data/training/intents.csv (training) and data/training/intents_test.csv (held-out test).

Only QUESTIONS are written here, never answers, so no PGPC facts are invented.
The test set uses different wording from the training set on purpose, so the evaluation
measures generalisation instead of memorisation.

Run:  python -m ml.training.build_intents
"""
import csv
import random
from pathlib import Path

from app.utils.text_cleaner import normalize_text

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "training"

# --------------------------------------------------------------------------- training
TRAIN = {
"greeting": """hi
hello
hello po
hey
hey there
good morning
good afternoon
good evening
hi pgpc smartguide
hello smartguide
kumusta
kumusta po
magandang umaga
magandang hapon
good day
hi there
yo
hello good morning
hi can you help me
hello is anyone there
hey bot
hi assistant
greetings
hello pgpc""",
"thanks": """thanks
thank you
thank you so much
thanks a lot
salamat
salamat po
maraming salamat
thank you po
ok thanks
okay thank you
thanks that helped
that was helpful thanks
great thank you
appreciate it
thanks for the help
thank you smartguide
got it thanks
perfect thanks
many thanks
thanks bot""",
"goodbye": """bye
goodbye
bye bye
see you
see you later
see you tomorrow
paalam
paalam po
that is all bye
im done thanks bye
have a nice day
take care
talk to you later
ok bye
goodbye smartguide
until next time
gotta go bye
i have to leave now
end chat
exit""",
"bot_info": """who are you
what are you
what is your name
what can you do
what can you help me with
how can you help me
what is pgpc smartguide
who made you
who created this chatbot
are you a real person
are you a robot
are you an ai
what questions can i ask you
how do you work
what is this chatbot for
tell me about yourself
introduce yourself
what can i ask here
are you human
what do you know""",
"employee_info": """who is the registrar
who is the school registrar
who is the head of the college
who is the college president
who is the dean
who is the dean of computer science
who is the guidance counselor
who is the librarian
who is the accountant
who is the cashier
who is the nurse
who handles scholarships
who is the professor of programming
who is the adviser of bscs
who teaches programming
who are the faculty members
list of faculty
list of professors
list of employees
list of administrative staff
who are the administrative personnel
who is joy abu
who is mr cruz
who is ms santos
who is maam reyes
who is sir dela cruz
tell me about professor garcia
what is the position of mr lopez
what is the job title of ms bautista
what department does sir ramos belong to
is there a faculty named mendoza
is sir torres a teacher here
which teacher handles database
who is the instructor for math
how many faculty does pgpc have
how many employees are there
who works in the registrars office
who is in charge of the library
who is the head of student affairs
who is the osa coordinator
who is the nstp coordinator
who is in charge of the clinic
what is the name of the vice president
who are the teachers
name of the school president
who is the campus director
find employee named santos
employee information
contact person for enrollment
who should i talk to about my grades
who do i ask about admission
what is the position of miss reyes
who is the secretary
who is the security guard""",
"office_location": """where is the registrar office
where can i find the registrar
where is the registrars office
where is the guidance office
where is the cashier
where do i pay tuition
where is the accounting office
where is the admission office
where do i enroll
where is the osa office
where is the office of student affairs
where is the dean office
where is the president office
where can i find the library office
where is the clinic
where is the nstp office
where is the saco office
where is the human resources office
where is the research office
where is the extension office
which office handles scholarships
which office should i go to for enrollment
what office issues the school id
what office do i go to for my transcript
what office handles clearance
where do i get my clearance signed
where do i submit my requirements
where do i get my certificate of enrollment
where can i request my grades
where is the student affairs office
where is the security office
how do i get to the registrar
how do i go to the cashier
directions to the guidance office
location of the registrar office
location of the admission office
office hours of the registrar
what are the office hours
what time does the cashier open
what time does the registrar close
is the registrar open today
list of offices
what offices are in pgpc
what offices does the college have
where is the mayors office
office of the president location
which office is for student organizations
where is the property custodian
where is the supply office""",
"room_location": """where is room 101
where is room 201
where is room 305
where is room 102 located
where is room 4
what building is room 202 in
which floor is room 301
which floor is room 203
where is the computer laboratory
where is the computer lab
where is the cs laboratory
where is the science laboratory
where is the lecture hall
where is the auditorium
where is the conference room
where is the faculty room
where is the faculty office
where is the comfort room
where is the restroom
where is the cr
where is the canteen
where is the cafeteria
where is the gym
where is the covered court
where is the lobby
where is the amphitheater
where is the multipurpose hall
where is the classroom for bscs
how do i find room 104
how many rooms are there
how many classrooms does pgpc have
list of rooms
list of classrooms
what rooms are in the first floor
what rooms are on the second floor
what is room 105 used for
what is the room number of the library
what is the room number of the registrar
which room is the computer lab
which building is the laboratory in
what floor is the library on
where is building a
where is the main building
where is the annex building
where are the classrooms
where do we have our class in programming
where is my classroom
where is the lab for networking
what rooms are available""",
"facility_info": """what facilities does pgpc have
what are the school facilities
list of facilities
facilities available in the college
does pgpc have a gym
does the school have a computer laboratory
does the campus have wifi
is there wifi in the school
is there free wifi
does pgpc have a canteen
does the school have a clinic
is there a basketball court
is there a parking area
does the campus have parking
what equipment is in the computer laboratory
how many computers are in the lab
what equipment is available in the laboratory
what time does the computer lab close
when does the canteen open
what are the laboratory hours
is there an air conditioned room
does the college have a reading room
do you have a science lab
what is available in the laboratory
tell me about the computer laboratory
tell me about the school facilities
facility hours
are there lockers
does the school have a chapel
do you have a student lounge
does the campus have a swimming pool
is there a gymnasium
what sports facilities does pgpc have
is there printing service
is there an internet cafe
what can i use in the laboratory""",
"handbook_policy": """what is the policy on attendance
what are the attendance rules
how many absences are allowed
what happens if i am absent too many times
what is the dress code
what is the uniform policy
do we need to wear id
what is the grading system
how are grades computed
what is the passing grade
what is the lowest passing grade
what is the grade for a dropped subject
what is an incomplete grade
how do i remove an incomplete grade
what is the policy on cheating
what is the penalty for cheating
what are the rules on student conduct
what are the grounds for suspension
what are the grounds for expulsion
what is the penalty for tardiness
what is the policy on late enrollment
how many units can i take
what is the maximum load
what is the student load policy
what is the retention policy
what are the requirements to stay in the program
what are the requirements for graduation
how do i graduate with honors
what are the latin honors requirements
what are the requirements for cum laude
what is the requirement for dean's list
what are the admission requirements
what are the requirements for new students
what are the requirements for transferees
what are the requirements for enrollment
what documents do i need to enroll
can i shift to another course
how do i shift programs
what is the shifting policy
what is the policy on leave of absence
how do i apply for a scholarship
what scholarships are available
what are the scholarship requirements
how do i keep my scholarship
what is financial assistance
what are the rules for online classes
what is the policy on face to face classes
what is the internet usage policy
what are the rules for using the school internet
what is the policy on practicum
what are the ojt requirements
how many hours of ojt are required
what is nstp
what are the rules for student organizations
how do i form a student organization
what are the rights of students
what are the duties of students
what is the policy on intellectual property
what is the vision of pgpc
what is the mission of pgpc
what are the core values of pgpc
what are the institutional objectives
what is the quality policy
what is the college mantra
what does the handbook say about uniforms
what does the student handbook say about discipline
according to the handbook what is the penalty for fighting
what is the policy on research publication
what is the policy on smoking
what is the policy on mobile phones in class
what are the rules on social media
what is the policy on id replacement
what is the policy on refunds
what is the policy on lost id
what are the college student government rules
how does the student council election work
what are the offenses and sanctions
what are the minor offenses
what are the major offenses
what is the policy on bullying""",
"school_history": """what is the history of pgpc
tell me the history of padre garcia polytechnic college
how was pgpc founded
when was pgpc established
when was the college founded
who founded pgpc
who established the college
why was pgpc established
what is the purpose of establishment of pgpc
when did pgpc open
how old is pgpc
what year was pgpc created
history of the school
school history
tell me about the founding of the college
what is the background of the college
how did pgpc start
origin of pgpc
who was the first president of pgpc
what is the story of pgpc
when did classes first start in pgpc
what is the history of padre garcia
who is the municipal mayor
who is the chairperson of the board of trustees
who are the board of trustees
who are the members of the board of trustees
what is the logo of pgpc
what is the meaning of the school logo
what is the school seal
what is the school hymn
what is the school song
what is the school motto
what does pgpc stand for
what is the full name of pgpc
what is pgpc
tell me about pgpc
give me an overview of pgpc
about the school
about pgpc""",
"enrollment_info": """what courses does pgpc offer
what programs are offered
what courses are available
list of courses
list of programs
what degree programs does pgpc have
what are the courses offered
does pgpc offer computer science
does pgpc offer criminology
does the college offer nursing
does pgpc have a public administration course
what is bscs
what is bscaim
what is bpa
what is bsma
what does bscs stand for
what does bsma mean
how many students are enrolled
how many students does pgpc have
what is the total enrollment
how many students are in bscs
how many students are in bpa
how many first year students are there
how many second year students are there
how many third year students are there
how many students are in third year
enrollment count per program
enrollment statistics
number of enrollees
total number of students
student population
how many students are in management accounting
how many bscaim students are there
which program has the most students
which course has the most students
which course has the least students
what is the largest program
how many students enrolled this year
when is the enrollment
when is the enrollment period
when does enrollment start
when is the enrollment schedule
how do i enroll
what are the steps in enrollment
how can i enroll in pgpc
how to enroll
how do i apply to pgpc
how do i apply for admission
is enrollment open
when is the deadline for enrollment
is there an entrance exam
is there an admission test
what is the tuition fee
how much is the tuition
is pgpc free tuition
how much is the enrollment fee
what is the cost of enrollment
what are the miscellaneous fees
what is the academic calendar
when does the semester start
when does the semester end
when is the first day of classes
when is the exam schedule
what are the class schedules
what is the semester schedule""",
"library_info": """does the college have a library
what books are available in the library
is there a book on programming
is there a book about accounting
do you have a book by author
who is the author of the book
who wrote the book
find a book about computer science
search for a book
book search
how do i borrow a book
how can i borrow books
how many books can i borrow
how long can i borrow a book
what is the borrowing period
what is the penalty for overdue books
what is the fine for a late book
what is the fine for a lost book
is the book available
is this book available in the library
do you have the book with isbn
what is the isbn of the book
what is the call number
how many books does the library have
what is the library collection
what are the library hours
what time does the library close
what time does the library open
what is the library location
where are the books located
which shelf is the book on
what are the library rules
can i reserve a book
can i renew a book
how do i get a library card
do i need an id to borrow
library services
what services does the library offer
is there an e library
does the library have thesis copies
where can i find thesis
library books list
list of books""",
"faq_general": """frequently asked questions
what are the faqs
common questions
what are the most common questions
how do i request a transcript of records
how do i get a certificate of good moral
how do i get a good moral certificate
how do i request a certificate of enrollment
how do i get my school id
how do i replace my lost id
how do i get a clearance
how do i apply for graduation
how do i drop a subject
how do i add a subject
how do i change my subjects
how do i apply for a leave of absence
how do i get my grades
how do i check my grades
how do i get my form 137
how do i get a diploma
how do i get a certification
how do i get my diploma
how do i request documents
how long does it take to process documents
how much is the certification fee
how do i pay my tuition
what are the payment options
can i pay in installments
can i pay by installment
what is the process for requesting documents
what is the process of shifting
how do i reset my password
how do i log in to the student portal
is there a student portal
how do i contact the school
how do i apply for a scholarship online
what should i do if i lost my id
what should i do if i failed a subject
what if i miss the exam
what if i cannot pay on time
how do i file a complaint
how do i report a problem
how do i join a student organization""",
"contact_info": """what is the contact number of pgpc
what is the phone number of the school
what is the telephone number
what is the email address of pgpc
what is the school email
what is the official email
what is the facebook page of pgpc
what is the school website
what is the website of pgpc
what is the address of pgpc
where is pgpc located
where is the school located
what is the school address
where is padre garcia polytechnic college
where is the campus
how do i get to pgpc
how can i contact the registrar
what is the registrars email
what is the registrars contact number
how can i reach the guidance office
how can i contact the admission office
contact details
contact information
phone number of the cashier
email of the dean
social media pages of pgpc
how do i send a message to the school
how to contact the college
how do i call the school
what is the mobile number of the school
is there a hotline
what is the school landline""",
"out_of_scope": """what is the weather today
what is the weather in manila
will it rain tomorrow
who is the president of the philippines
who is the current president
who won the basketball game
who won the nba finals
what is the capital of france
what is the capital of the philippines
how tall is mount everest
how far is the moon
what is the meaning of life
tell me a joke
tell me a story
sing me a song
write me a poem
write an essay about climate change
write my assignment
do my homework
solve this math problem
what is two plus two
what is the square root of 144
what is the derivative of x squared
translate this to spanish
translate hello to japanese
how do i cook adobo
give me a recipe for pancakes
what is a good movie to watch
recommend me a netflix show
who is the best singer
what is the best phone
how much is a bitcoin
what is the stock price of apple
how do i lose weight
how do i fix my laptop
how do i write a python function
write code for a calculator
explain quantum physics
explain photosynthesis
who invented the telephone
who is elon musk
who is taylor swift
what is the latest news
what is the exchange rate of the dollar
where is the nearest mall
where is the nearest hospital
where can i buy pizza
what is the best restaurant in batangas
how do i get to manila
how do i get a driver's license
what is the tax rate in the philippines
how do i apply for a passport
what is a good gift for my girlfriend
how do i make my crush like me
what is your favorite color
do you love me
are you single
how old are you
what is the score of the game
what time is it
what day is today
tell me about another university
where is the ust campus
what is the tuition of ateneo
how do i apply to up diliman
what is the history of the philippines
who is jose rizal
asdf
qwerty
blah blah
random words here
test test
what is the best programming language
how do i hack a wifi
how do i cheat in an exam""",
}

# ------------------------------------------------------------------------ test (held out)
TEST = {
"greeting": """hello good day
hi good morning po
hey hello
magandang gabi
good evening po
hi hello there
hello kumusta
hi smartguide""",
"thanks": """thank you very much
thanks po
salamat ha
okay thanks a lot
thank you that is helpful
thanks smartguide
salamat sa tulong""",
"goodbye": """see you around
goodbye po
bye for now
ok that is all thank you bye
im leaving now bye
paalam na po""",
"bot_info": """what is your purpose
are you a bot
what are you able to do
who built this assistant
what can this chatbot answer
tell me what you do""",
"employee_info": """who is the head of the registrar
who is the pgpc librarian
who is the faculty member named abu
who is sir mendoza
what is the position of maam gonzales
who teaches computer programming
who is the coordinator of student affairs
list the faculty members
who is the person in charge of scholarships
how many teachers does the college have
tell me about mr bautista
who is the head of the cashier""",
"office_location": """where can i find the cashier
where is the office of the registrar
where do i go to enroll
which office do i go to for good moral
where is the guidance counselor office
what time does the registrar office open
location of the cashier
how do i find the admission office
where do i process my clearance
what offices are there in the college
where do i submit my documents
where is the human resource office""",
"room_location": """where is room 103
what floor is room 205
which building is room 101 in
where is the computer lab located
where can i find the faculty room
where is the cr
how many classrooms are there
where is the school canteen
what rooms are on the third floor
where is the gym located""",
"facility_info": """what facilities are available
does the school have wifi
is there a gym in pgpc
what equipment does the computer laboratory have
does pgpc have a basketball court
is there a parking space
what are the laboratory operating hours
tell me about the facilities of the college""",
"handbook_policy": """what is the rule about absences
what is the dress code policy
how are the grades computed
what is the passing grade
what are the requirements for graduating with honors
what is the penalty for cheating in exams
how many units can a student take
what are the grounds for dismissal
what does the handbook say about attendance
what is the mission of the college
what are the core values
what is the policy for ojt
what is the scholarship requirement
what are the rules for shifting course
what is the policy on online classes
what are the major offenses""",
"school_history": """how did pgpc begin
when was padre garcia polytechnic college established
who founded the college
tell me the history of the school
why was the college created
what is the school logo about
who are the board of trustees
what does pgpc stand for""",
"enrollment_info": """what courses are offered in pgpc
how many students are enrolled in total
how many bscs students are there
what is bsma
when is the enrollment
how do i enroll in the college
how many students are in second year
which program has the most enrollees
how much is the tuition fee
does pgpc offer criminology
what is the enrollment count of bpa
when does the semester start""",
"library_info": """how can i borrow a book from the library
is there a book about programming
what is the fine for overdue books
how many books can a student borrow
who is the author of this book
what are the library borrowing rules
do you have thesis copies in the library
is the book available""",
"faq_general": """how do i request my transcript
how can i get a certificate of good moral character
what are the frequently asked questions
how do i replace my id
how do i drop a subject
how do i apply for graduation
how do i pay the tuition fee
can i pay in installments
how do i get my diploma""",
"contact_info": """what is the phone number of pgpc
what is the email of the school
what is the address of the college
where is the school located
how do i contact the registrar
what is the facebook page of the school
how can i reach the school""",
"out_of_scope": """what is the weather like today
who won the game last night
write an essay about my family
what is the capital of japan
tell me a joke please
how do i cook fried rice
what is the best phone to buy
who is the president of the united states
solve x plus 5 equals 10
translate this sentence to korean
how do i hack a facebook account
what is the price of gold
recommend a good movie
how do i get to the airport""",
}


def _lines(block: str) -> list[str]:
    return [l.strip() for l in block.strip().splitlines() if l.strip()]


def write(path: Path, data: dict, exclude: set | None = None) -> int:
    rows = []
    seen = set(exclude or ())
    for intent, block in data.items():
        for text in _lines(block):
            key = normalize_text(text)   # same wording after cleaning counts as a duplicate
            if key not in seen:
                seen.add(key)
                rows.append((text, intent))
    random.Random(42).shuffle(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["text", "intent"])
        w.writerows(rows)
    return len(rows)


def main() -> None:
    n_train = write(OUT_DIR / "intents.csv", TRAIN)
    # A test question that is also a training question would inflate the score, so it is dropped.
    train_texts = {normalize_text(t) for i, b in TRAIN.items() for t in _lines(b)}
    clean_test = {i: "\n".join(t for t in _lines(b) if normalize_text(t) not in train_texts) for i, b in TEST.items()}
    n_test = write(OUT_DIR / "intents_test.csv", clean_test)
    print(f"intents.csv: {n_train} rows | intents_test.csv: {n_test} rows | {len(TRAIN)} intents")


if __name__ == "__main__":
    main()
