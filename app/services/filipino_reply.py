"""Answers in Filipino for students who ask in Filipino or Taglish.

Only the sentences the CHATBOT writes are translated (lead-ins, "Short answer", "Source", notes, "not found" replies).
Text copied from the handbook or the records is never translated: a translation of a rule could change its meaning.
Every translation is a fixed sentence checked in tests/test_filipino_reply.py, so nothing is guessed at run time.
Anything not listed stays in English. Pure function, no database.
"""
import re

CHECK = "check with the concerned PGPC office"
ASK_OFFICE = "Magtanong sa kinauukulang opisina ng PGPC."

# (regex for a whole line, replacement). First match wins.
RULES: list[tuple[str, str]] = [
    (r'^Here is what the PGPC Student Handbook says about "(.+?)":$', r'Narito ang nakasaad sa PGPC Student Handbook tungkol sa "\1":'),
    (r'^That is everything the handbook says about this topic\. For details it does not give, please ask the concerned '
     r'PGPC office, such as the Office of Student Affairs \(OSA\)\.$',
     'Iyan ang lahat ng nakasaad sa handbook tungkol sa paksang ito. Para sa mga detalyeng hindi nakasulat dito, '
     'magtanong sa kinauukulang opisina ng PGPC, tulad ng Office of Student Affairs (OSA).'),
    (r'^MINOR OFFENSES \(lighter violations\)$', 'MINOR OFFENSES (mas magagaang paglabag)'),
    (r'^MAJOR OFFENSES \(serious violations\)$', 'MAJOR OFFENSES (mabibigat na paglabag)'),
    (r'^Sanctions the handbook lists for (.+?):$', r'Mga parusang nakalista sa handbook para sa \1:'),
    (r'^These sanctions are listed once for the whole table of minor offenses; the handbook text does not say which '
     r'one applies to which rule\.$',
     'Isang beses lang nakalista ang mga parusang ito para sa buong talaan ng minor offenses; hindi sinasabi ng '
     'handbook kung alin ang para sa aling patakaran.'),
    (r'^The handbook lists these sanctions once for the whole category; the text does not say which one applies to '
     r'which rule\.$',
     'Isang beses lang nakalista ng handbook ang mga parusang ito para sa buong kategorya; hindi sinasabi kung alin '
     'ang para sa aling patakaran.'),
    (r'^The handbook text I have does not list a sanction for this part\.$',
     'Walang nakalistang parusa para sa bahaging ito sa handbook na hawak ko.'),
    (r'^RELATED APPEARANCE RULES in the same handbook tables$', 'MGA KAUGNAY NA PATAKARAN SA ITSURA sa parehong talaan ng handbook'),
    (r'^Note: the handbook lists related wording under both minor and major offenses, so the exact classification of '
     r'a case should be confirmed with the Office of Student Affairs \(OSA\)\.$',
     'Paalala: may magkahawig na nakasulat sa parehong minor at major offenses ng handbook, kaya dapat kumpirmahin '
     'sa Office of Student Affairs (OSA) ang eksaktong uri ng kaso.'),
    (r'^The handbook has no separate section for this topic\. It appears in the rules on Student Conduct and Discipline '
     r'\((.+?)\)\.$',
     r'Walang hiwalay na seksyon ang handbook para sa paksang ito. Makikita ito sa mga patakaran ng Student Conduct and Discipline (\1).'),
    (r'^According to "(.+?)":$', r'Ayon sa "\1":'),
    (r'^Here is what I found under "(.+?)":$', r'Ito ang nakita ko sa "\1":'),
    (r'^\(This is the part that best matches your question\. Check the full document for the rest\.\)$',
     '(Ito ang bahaging pinakaangkop sa tanong mo. Basahin ang buong dokumento para sa iba pa.)'),
    (r"^I'm not completely sure this is what you meant, but this is the closest match I found:$",
     'Hindi ako lubos na sigurado kung ito ang ibig mong sabihin, pero ito ang pinakamalapit na nakita ko:'),
    (r'^Note: some details for this record have not been added yet, so please confirm with the concerned PGPC office\.$',
     'Paalala: may mga detalye pang hindi naidaragdag sa talang ito, kaya makipag-ugnayan sa kinauukulang opisina ng PGPC.'),
    # not found
    (r'^I couldn\'t find anything about "(.+?)" in the PGPC Student Handbook or records\. It may not be covered, or it '
     r'may use different words, so try rephrasing it or check with the concerned PGPC office\. For example: (.+)$',
     r'Wala akong nakitang impormasyon tungkol sa "\1" sa PGPC Student Handbook o sa mga tala. Maaaring hindi ito saklaw, '
     r'o iba ang mga salitang ginamit, kaya subukang ibahin ang tanong o magtanong sa kinauukulang opisina ng PGPC. Halimbawa: \2'),
    (r"^I'm sorry, I couldn't find information about that in the PGPC knowledge base\. It may not have been added yet\. "
     r"Try asking with specific words \(an office name, a person's name or a handbook topic\), or check with the "
     r"concerned PGPC office\. For example: (.+)$",
     r'Pasensya na, wala akong nakitang impormasyon tungkol diyan sa kaalaman ng PGPC. Maaaring hindi pa ito naidaragdag. '
     r'Subukang gumamit ng mas tiyak na salita (pangalan ng opisina, pangalan ng tao o paksa ng handbook), o magtanong sa '
     r'kinauukulang opisina ng PGPC. Halimbawa: \1'),
    (r"^I couldn't find an exact answer to that, but these are the closest topics I have\. Try asking about one of them:$",
     'Wala akong nakitang eksaktong sagot diyan, pero ito ang pinakamalapit na paksa na mayroon ako. Subukang itanong ang isa sa mga ito:'),
    (r"^I couldn't find that person or position in the PGPC employee records\. It may not have been added yet, so please "
     r"check with the concerned PGPC office\. You can also ask me about an office, a facility or a handbook topic\.$",
     'Wala akong nakitang taong iyan o posisyon sa talaan ng empleyado ng PGPC. Maaaring hindi pa ito naidaragdag, kaya '
     'magtanong sa kinauukulang opisina ng PGPC. Maaari mo rin akong tanungin tungkol sa opisina, pasilidad o paksa ng handbook.'),
    (r"^I don't have the location of that room or area on file yet\. Please check with the concerned PGPC office\.$",
     'Wala pang naitalang lokasyon ng silid o lugar na iyan. ' + ASK_OFFICE),
    (r"^I don't have that office or its location on file yet\. Please check with the concerned PGPC office\.$",
     'Wala pang naitalang opisinang iyan o ang lokasyon nito. ' + ASK_OFFICE),
    (r"^I don't have details about that facility on file yet\. Please check with the concerned PGPC office\.$",
     'Wala pang naitalang detalye tungkol sa pasilidad na iyan. ' + ASK_OFFICE),
    (r"^I don't have that library detail \(for example its opening hours\) on file yet\. Please check with the concerned "
     r"PGPC office\.$",
     'Wala pang naitalang detalyeng iyan tungkol sa library (halimbawa ang oras ng bukas nito). ' + ASK_OFFICE),
    (r"^I don't have that contact detail on file yet\. Please check with the concerned PGPC office\.$",
     'Wala pang naitalang contact detail na iyan. ' + ASK_OFFICE),
    (r'^I can help with these, for example: (.+)$', r'Matutulungan kita sa mga ito, halimbawa: \1'),
    # people
    (r'^(.+) is the (College President) of PGPC\.$', r'Si \1 ang \2 ng PGPC.'),
    (r'^(.+) is the (?!College President of PGPC)(.+)\.$', r'Si \1 ang \2.'),
    (r'^Also listed as: (.+)\.$', r'Nakalista rin bilang: \1.'),
    (r'^The handbook says: (.+)\.$', r'Ayon sa handbook: \1.'),
    (r'^Employee record: (.+)\.$', r'Talaan ng empleyado: \1.'),
    (r'^The PGPC Student Handbook lists these people for "(.+?)":$', r'Nakalista sa PGPC Student Handbook ang mga taong ito para sa "\1":'),
    (r"^I don't have an email address for (.+) on file yet\. Please check with the concerned PGPC office\.$",
     r'Wala pang naitalang email address para kay \1. ' + ASK_OFFICE),
    (r"^I don't have a contact number for (.+) on file yet\. Please check with the concerned PGPC office\.$",
     r'Wala pang naitalang contact number para kay \1. ' + ASK_OFFICE),
    (r"^I don't have the email or contact number of (.+) on file yet\. Please check with the concerned PGPC office\.$",
     r'Wala pang naitalang email o contact number para kay \1. ' + ASK_OFFICE),
    (r'^Here is what I do have:$', 'Narito ang mayroon ako:'),
    (r'^Here is what I have on (.+):$', r'Narito ang mayroon ako tungkol kay \1:'),
    (r"^I don't have a record of who heads the (.+) yet\. You can ask me where it is, or check with the concerned PGPC "
     r"office\.$",
     r'Wala pang naitalang kung sino ang namumuno sa \1. Maaari mo akong tanungin kung nasaan ito, o magtanong sa kinauukulang opisina ng PGPC.'),
    (r'^Ask about one of them by name for more details\.$', 'Magtanong tungkol sa isa sa kanila gamit ang pangalan para sa mga detalye.'),
    (r'^The roster records names and groups only; ask about a person by name for more\.$',
     'Pangalan at grupo lang ang nasa talaan; magtanong tungkol sa isang tao gamit ang pangalan para sa iba pa.'),
    (r'^(.+?) \((\d+) people listed in the PGPC employee records\):$', r'\1 (\2 katao sa talaan ng empleyado ng PGPC):'),
    (r'^The PGPC employee records list (\d+) people under (.+)\.$', r'Nakalista sa talaan ng empleyado ng PGPC ang \1 katao sa ilalim ng \2.'),
    (r'^I found (\d+) people for "(.+?)":$', r'May nakita akong \1 katao para sa "\2":'),
    # links
    (r'^You can enroll online through the official PGPC enrollment link:$', 'Maaari kang mag-enroll online gamit ang opisyal na PGPC enrollment link:'),
    (r'^Open the link to start your enrollment\. For the requirements listed in the Student Handbook, you can ask me: "(.+)"$',
     r'Buksan ang link para simulan ang iyong enrollment. Para sa mga requirement na nakasulat sa Student Handbook, itanong mo sa akin: "\1"'),
    (r'^To enroll online, use the official PGPC enrollment link:$', 'Para mag-enroll online, gamitin ang opisyal na PGPC enrollment link:'),
    (r'^Here is the official link for (.+):$', r'Narito ang opisyal na link para sa \1:'),
    # small talk
    (r"^You're welcome! Feel free to ask anything else about PGPC\.$", 'Walang anuman! Magtanong lang ng iba pa tungkol sa PGPC.'),
    (r'^Goodbye! Come back anytime you have a question about PGPC\.$', 'Paalam! Bumalik ka anumang oras na may tanong ka tungkol sa PGPC.'),
    (r'^Source: (.+)$', r'Pinagmulan: \1'),
]
_COMPILED = [(re.compile(p), r) for p, r in RULES]


def _which(group: str) -> str:
    found = [name for word, name in (("major", "major offenses"), ("minor", "minor offenses")) if word in group]
    return " at ".join(found) if found else "offenses"


def _line(line: str) -> str:
    s = line.rstrip()
    m = re.match(r"^Short answer: no\. The handbook lists this under (.+?), so it is not allowed\. The details and the "
                 r"sanctions are below\.$", s)
    if m:
        return (f"Maikling sagot: hindi. Nakalista ito sa {_which(m.group(1))} ng handbook, kaya hindi ito pinapayagan. "
                "Nasa ibaba ang mga detalye at ang mga parusa.")
    m = re.match(r"^Short answer: the handbook lists this under (.+?), so there are sanctions\. The sanctions are below\.$", s)
    if m:
        return f"Maikling sagot: nakalista ito sa {_which(m.group(1))} ng handbook, kaya may parusa. Nasa ibaba ang mga parusa."
    for pattern, repl in _COMPILED:
        new, n = pattern.subn(repl, s)
        if n:
            return new
    return line


def localize(text: str) -> str:
    """Filipino version of the sentences the chatbot wrote. Handbook text is left exactly as it is."""
    return "\n".join(_line(x) for x in (text or "").split("\n"))
