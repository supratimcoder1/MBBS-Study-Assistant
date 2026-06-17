"""
Query Pre-Filter Service
Lightweight rule-based screening layer that intercepts greetings, profanity,
and casual non-study chatter BEFORE they reach the Gemini API, preserving
API quota for actual medical study queries.
"""

import re
import logging

logger = logging.getLogger(__name__)

# ── Profanity word list (kept deliberately short – extend as needed) ────────
_PROFANITY_WORDS = {
    "fuck", "shit", "damn", "ass", "bitch", "bastard", "crap", "dick",
    "piss", "slut", "whore", "cock", "cunt", "wanker", "bollocks",
    "motherfucker", "asshole", "arsehole", "douchebag", "twat",
    "nigger", "faggot", "retard",
}

# Build a compiled regex that matches any profanity word as a whole token
_PROFANITY_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in _PROFANITY_WORDS) + r")\b",
    re.IGNORECASE,
)

# ── Greeting patterns (standalone) ──────────────────────────────────────────
_GREETING_PATTERNS = [
    r"^(?:hi|hello|hey|howdy|yo|sup|hiya|heya|hola|namaste|namaskar)[\s!.?]*$",
    r"^good\s+(?:morning|afternoon|evening|night|day)[\s!.?]*$",
    r"^(?:what'?s?\s+up|how\s+are\s+you|how\s+do\s+you\s+do)[\s!?.]*$",
    r"^(?:thanks?|thank\s+you|thx|ty)[\s!.?]*$",
    r"^(?:bye|goodbye|good\s*bye|see\s+you|later|cya|ttyl)[\s!.?]*$",
    r"^(?:ok|okay|k|kk|alright|sure|yep|yup|yes|no|nah|nope)[\s!.?]*$",
    r"^(?:gm|gn|gd\s*mrng|gd\s*nite?)[\s!.?]*$",
    r"^(?:hmm+|huh|meh|lol|lmao|rofl|haha|hehe|xd)[\s!.?]*$",
]

_GREETING_COMPILED = [re.compile(p, re.IGNORECASE) for p in _GREETING_PATTERNS]

# ── Casual / off-topic patterns ─────────────────────────────────────────────
_CASUAL_PATTERNS = [
    r"^who\s+are\s+you",
    r"^what\s+(?:is\s+your\s+name|are\s+you)",
    r"^tell\s+me\s+(?:a\s+joke|something\s+funny)",
    r"^(?:what(?:'s)?\s+the\s+)?weather",
    r"^(?:what(?:'s)?\s+the\s+)?time",
    r"^(?:what(?:'s)?\s+the\s+)?date",
    r"^(?:sing|rap|write\s+(?:a\s+)?poem|write\s+(?:a\s+)?song)",
    r"^(?:play\s+a\s+game|let'?s?\s+play)",
    r"^(?:i'?m?\s+bored|i\s+(?:am|feel)\s+(?:bored|tired|sleepy|sad|happy|angry|lonely))",
    r"^(?:do\s+you\s+(?:like|love|hate|know|think|feel|believe))",
    r"^(?:can\s+you\s+(?:sing|dance|cook|drive|fly))",
    r"^(?:how\s+old\s+are\s+you|where\s+(?:are|do)\s+you\s+(?:live|come\s+from))",
    r"^(?:are\s+you\s+(?:a\s+(?:bot|robot|ai|human|real)|alive|sentient|conscious))",
    r"^(?:what\s+(?:is|are)\s+(?:your\s+)?(?:hobbies|favorite|fav))",
]

_CASUAL_COMPILED = [re.compile(p, re.IGNORECASE) for p in _CASUAL_PATTERNS]

# ── Medical / study keyword safelist ────────────────────────────────────────
# If ANY of these appear in the query alongside a greeting, let it through.
_STUDY_KEYWORDS = re.compile(
    r"\b(?:"
    r"anatomy|physiology|biochemistry|pathology|pharmacology|microbiology|"
    r"forensic|medicine|surgery|pediatric|obstetric|gynaecology|gynecology|"
    r"ophthalmology|ent|orthopaedic|orthopedic|radiology|dermatology|"
    r"psychiatry|community|preventive|anesthesia|"
    r"cell|tissue|organ|bone|muscle|nerve|brain|heart|lung|liver|kidney|"
    r"blood|vessel|artery|vein|capillary|lymph|"
    r"disease|disorder|syndrome|symptom|sign|diagnosis|treatment|therapy|"
    r"drug|dose|mechanism|receptor|enzyme|hormone|protein|gene|dna|rna|"
    r"infection|bacteria|virus|fungi|parasite|immunity|antibody|antigen|"
    r"fracture|tumor|tumour|cancer|neoplasm|lesion|"
    r"clinical|patient|history|examination|investigation|differential|"
    r"physio|patho|pharma|micro|histo|embryo|"
    r"mitosis|meiosis|glycolysis|krebs|atp|hemoglobin|haemoglobin|"
    r"insulin|aldosterone|cortisol|thyroid|"
    r"explain|describe|define|differentiate|compare|mechanism|pathway|"
    r"chapter|textbook|section|page|study|exam|review|revise|"
    r"mcq|question|answer|mnemonics|flowchart"
    r")\b",
    re.IGNORECASE,
)

# ── The canned robotic response ─────────────────────────────────────────────
FILTERED_RESPONSE = (
    "**BEEP BOOP.** 🤖\n\n"
    "I am a specialized **MBBS Study Assistant**. "
    "Please query me about medical subjects, concepts, or textbook materials to begin.\n\n"
    "Try asking something like:\n"
    "- *Explain the mechanism of action of ACE inhibitors*\n"
    "- *What are the branches of the external carotid artery?*\n"
    "- *Describe the stages of mitosis*"
)


def screen_query(query: str) -> str | None:
    """
    Screen the user query BEFORE it reaches Gemini.

    Returns
    -------
    str | None
        A canned response string if the query should be blocked,
        or ``None`` if the query should proceed to the RAG pipeline.
    """
    text = query.strip()

    # Empty or very short non-medical queries
    if len(text) < 2:
        return FILTERED_RESPONSE

    # ── 1. Profanity check (always block, regardless of other content) ──────
    if _PROFANITY_PATTERN.search(text):
        logger.info("Query blocked by profanity filter: %s", text[:60])
        return FILTERED_RESPONSE

    # ── 2. If the message contains study keywords, let it through ───────────
    if _STUDY_KEYWORDS.search(text):
        return None  # Proceed to RAG pipeline

    # ── 3. Pure greeting check ──────────────────────────────────────────────
    for pattern in _GREETING_COMPILED:
        if pattern.match(text):
            logger.info("Query blocked by greeting filter: %s", text[:60])
            return FILTERED_RESPONSE

    # ── 4. Casual / off-topic check ─────────────────────────────────────────
    for pattern in _CASUAL_COMPILED:
        if pattern.search(text):
            logger.info("Query blocked by casual filter: %s", text[:60])
            return FILTERED_RESPONSE

    # All checks passed – let it through
    return None
