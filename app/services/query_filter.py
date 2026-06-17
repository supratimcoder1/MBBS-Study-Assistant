import re

# List of common profanities
SWEAR_WORDS = [
    r"\bfuck(ing|er|ed)?\b",
    r"\bshit(ty|head)?\b",
    r"\bbitch(es)?\b",
    r"\basshole(s)?\b",
    r"\bcunt(s)?\b",
    r"\bdick(head|s)?\b",
    r"\bpussy\b",
    r"\bcrap\b",
    r"\bbastard(s)?\b",
    r"\bfag(got)?\b",
    r"\bwhore(s)?\b",
    r"\bslut(s)?\b",
]

# Greetings and polite phrases (exact match after normalization or start/end match)
GREETINGS = {
    "hi", "hello", "hey", "yo", "sup", "greetings", "good morning", "good afternoon",
    "good evening", "good night", "howdy", "hola", "namaste", "wassup", "whats up",
    "thank you", "thanks", "thanks a lot", "thank you so much", "bye", "goodbye",
    "see you", "see ya", "welcome", "please"
}

# Casual / non-study questions and phrases (exact or subset matches)
CASUAL_PHRASES = [
    r"^who are you$",
    r"^what is your name$",
    r"^what's your name$",
    r"^who made you$",
    r"^who created you$",
    r"^are you (a )?human$",
    r"^are you (a )?bot$",
    r"^are you (an )?ai$",
    r"^are you real$",
    r"^how old are you$",
    r"^how are you$",
    r"^how's it going$",
    r"^how are you doing$",
    r"^tell me a joke$",
    r"^tell a joke$",
    r"^how's the weather$",
    r"^what's the weather$",
    r"^can you write code$",
    r"^write a story$",
    r"^what is the meaning of life$",
]

def check_study_filter(query: str) -> tuple[bool, str]:
    """
    Check if a query is a greeting, swear word, or casual conversation not related to study.
    Returns (is_filtered, robotic_response).
    """
    cleaned = query.strip().lower()
    
    # 1. Check if empty or too short (e.g. single character or just punctuation)
    alphanumeric_only = re.sub(r'[^a-zA-Z0-9\s]', '', cleaned).strip()
    if not alphanumeric_only or len(alphanumeric_only) <= 1:
        return True, "BEEP BOOP. I am a specialized MBBS Study Assistant. Please query me about medical subjects, concepts, or textbook materials to begin."

    # 2. Check for swear words (using regex word boundaries)
    for pattern in SWEAR_WORDS:
        if re.search(pattern, cleaned):
            return True, "BEEP BOOP. I am a specialized MBBS Study Assistant. Please query me about medical subjects, concepts, or textbook materials to begin."

    # 3. Check for exact greeting match
    # If the user's query is just a greeting like "hello" or "hi there"
    normalized_for_greeting = re.sub(r'[^a-zA-Z0-9\s]', '', cleaned).strip()
    if normalized_for_greeting in GREETINGS:
        return True, "BEEP BOOP. I am a specialized MBBS Study Assistant. Please query me about medical subjects, concepts, or textbook materials to begin."

    # 4. Check for casual phrases using regexes
    for pattern in CASUAL_PHRASES:
        if re.search(pattern, normalized_for_greeting):
            return True, "BEEP BOOP. I am a specialized MBBS Study Assistant. Please query me about medical subjects, concepts, or textbook materials to begin."

    return False, ""
