"""Multilingual text helpers: tokenising, light stemming, synonym canonicalisation, language
detection, budget parsing and PII scrubbing.

Deliberately dependency-free so it behaves identically in tests, on Cloud Run and in the
offline fallback mode. Telugu / Devanagari are handled by keeping Unicode combining marks
inside tokens (``str.isalnum`` alone would split Indic words apart).
"""

from __future__ import annotations

import re
import unicodedata

# --------------------------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------------------------

PHRASES = {
    "gluten free": "glutenfree",
    "gluten-free": "glutenfree",
    "sugar free": "sugarfree",
    "sugar-free": "sugarfree",
    "t-shirt": "tshirt",
    "t shirt": "tshirt",
    "tee shirt": "tshirt",
    "power bank": "powerbank",
    "wi-fi": "wifi",
    "dry fruits": "dryfruit",
    "dry fruit": "dryfruit",
}

_SYNONYMS_RAW = {
    # English
    "earphone": "earbud",
    "earphones": "earbud",
    "headset": "earbud",
    "cookie": "biscuit",
    "cookies": "biscuit",
    "mobile": "phone",
    "cellphone": "phone",
    "smartphone": "phone",
    "tee": "tshirt",
    "pants": "jeans",
    "trouser": "jeans",
    "trousers": "jeans",
    "ragi": "millet",
    "jowar": "millet",
    "bajra": "millet",
    "millets": "millet",
    "atta": "flour",
    "aata": "flour",
    "wheat": "wheat",
    "lentils": "lentil",
    "pulses": "lentil",
    "dal": "lentil",
    "daal": "lentil",
    "cooking": "",
    "edible": "",
    # Hindi (romanised)
    "chawal": "rice",
    "chini": "sugar",
    "cheeni": "sugar",
    "doodh": "milk",
    "dahi": "curd",
    "chai": "tea",
    "namak": "salt",
    "tel": "oil",
    "sabun": "soap",
    "paani": "water",
    "pani": "water",
    "gehu": "wheat",
    "nariyal": "coconut",
    "shahad": "honey",
    "dhaniya": "coriander",
    # Telugu (romanised)
    "biyyam": "rice",
    "annam": "rice",
    "pappu": "lentil",
    "paalu": "milk",
    "palu": "milk",
    "nune": "oil",
    "uppu": "salt",
    "panchadara": "sugar",
    "perugu": "curd",
    "teneyi": "honey",
    # Native script
    "चावल": "rice",
    "दाल": "lentil",
    "दूध": "milk",
    "चीनी": "sugar",
    "नमक": "salt",
    "तेल": "oil",
    "चाय": "tea",
    "आटा": "flour",
    "दही": "curd",
    "शहद": "honey",
    "साबुन": "soap",
    "पानी": "water",
    "బియ్యం": "rice",
    "పప్పు": "lentil",
    "పాలు": "milk",
    "చక్కెర": "sugar",
    "ఉప్పు": "salt",
    "నూనె": "oil",
    "టీ": "tea",
    "పిండి": "flour",
    "పెరుగు": "curd",
    "తేనె": "honey",
    "సబ్బు": "soap",
    "నీళ్లు": "water",
    "పాస్తా": "pasta",
    "బిస్కెట్లు": "biscuit",
    "బిస్కెట్": "biscuit",
    "ఇయర్‌బడ్స్": "earbud",
    "చార్జర్": "charger",
}

STOPWORDS = {
    "a",
    "an",
    "the",
    "i",
    "me",
    "my",
    "we",
    "our",
    "you",
    "your",
    "want",
    "need",
    "needs",
    "needed",
    "looking",
    "look",
    "for",
    "show",
    "find",
    "get",
    "buy",
    "do",
    "does",
    "have",
    "has",
    "any",
    "is",
    "are",
    "was",
    "there",
    "please",
    "some",
    "with",
    "to",
    "of",
    "in",
    "on",
    "and",
    "or",
    "at",
    "it",
    "this",
    "that",
    "under",
    "below",
    "less",
    "than",
    "within",
    "upto",
    "up",
    "max",
    "maximum",
    "budget",
    "rs",
    "inr",
    "rupee",
    "rupees",
    "cheap",
    "cheaper",
    "best",
    "good",
    "nice",
    "one",
    "about",
    "can",
    "could",
    "would",
    "like",
    "sell",
    "selling",
    "stock",
    "available",
    "availability",
    "price",
    "cost",
    "tell",
    "give",
    "send",
    "order",
    "bring",
    "store",
    "shop",
    "hello",
    "hi",
    "hey",
    "s",
    "mujhe",
    "chahiye",
    "chahie",
    "hai",
    "hain",
    "kya",
    "ka",
    "ki",
    "ke",
    "ko",
    "se",
    "mein",
    "aur",
    "kam",
    "andar",
    "tak",
    "dikhao",
    "dikhaiye",
    "milega",
    "milegi",
    "hoga",
    "hogi",
    "mere",
    "liye",
    "naku",
    "kavali",
    "kavalani",
    "undi",
    "unda",
    "unnaya",
    "ledu",
    "lo",
    "lopu",
    "ela",
    "entha",
    "cheppandi",
    "chupinchandi",
    "dorukutunda",
    "मुझे",
    "चाहिए",
    "है",
    "हैं",
    "क्या",
    "का",
    "की",
    "के",
    "को",
    "से",
    "में",
    "और",
    "कम",
    "अंदर",
    "तक",
    "मेरे",
    "लिए",
    "दिखाओ",
    "मिलेगा",
    "నాకు",
    "కావాలి",
    "ఉందా",
    "ఉంది",
    "లోపు",
    "లో",
    "కి",
    "ఏమైనా",
    "ఉన్నాయా",
    "లేదు",
    "చూపించండి",
}

_AFFIRM = {
    "yes",
    "yeah",
    "yep",
    "yup",
    "sure",
    "ok",
    "okay",
    "please",
    "ya",
    "yess",
    "definitely",
    "alright",
    "haan",
    "han",
    "ha",
    "haa",
    "ji",
    "theek",
    "thik",
    "zaroor",
    "hanji",
    "avunu",
    "avunandi",
    "sare",
    "sari",
    "हाँ",
    "हां",
    "जी",
    "ठीक",
    "जरूर",
    "అవును",
    "సరే",
    "అవునండి",
}
_NEGATE = {
    "no",
    "nope",
    "nah",
    "nahi",
    "nahin",
    "never",
    "later",
    "vaddu",
    "kadu",
    "ledu",
    "వద్దు",
    "కాదు",
    "नहीं",
    "नही",
    "मत",
    "లేదు",
}
_GREET = {
    "hi",
    "hello",
    "hey",
    "hola",
    "namaste",
    "namaskaram",
    "namaskar",
    "help",
    "start",
    "नमस्ते",
    "नमस्कार",
    "నమస్తే",
    "నమస్కారం",
    "హలో",
    "హాయ్",
}

_ROMAN_HI = {
    "chahiye",
    "chahie",
    "hai",
    "hain",
    "mujhe",
    "kya",
    "milega",
    "milegi",
    "dikhao",
    "aur",
    "nahi",
    "haan",
    "ka",
    "ki",
    "ke",
}
_ROMAN_TE = {
    "kavali",
    "kavalani",
    "undi",
    "unda",
    "unnaya",
    "naku",
    "ledu",
    "avunu",
    "sare",
    "cheppandi",
    "dorukutunda",
    "lopu",
}

_KEEP_SHORT = {"m", "l", "xl", "xs"}


def _stem(tok: str) -> str:
    if not tok.isascii() or len(tok) <= 3:
        return tok
    if tok.endswith("ies") and len(tok) > 4:
        return tok[:-3] + "y"
    if tok.endswith(("ss", "us", "is")):
        return tok
    if tok.endswith("s"):
        return tok[:-1]
    return tok


SYNONYMS = {_stem(k): v for k, v in _SYNONYMS_RAW.items()}
SYNONYMS.update({k: v for k, v in _SYNONYMS_RAW.items() if not k.isascii()})


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    cur: list[str] = []
    for ch in text.lower():
        if ch.isalnum() or unicodedata.category(ch).startswith("M"):
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


def normalize_tokens(text: str) -> list[str]:
    """Canonical tokens for matching: phrase-merged, stemmed, synonym-mapped, stop-word free."""
    low = text.lower()
    for src, dst in PHRASES.items():
        low = low.replace(src, dst)
    out: list[str] = []
    for tok in tokenize(low):
        if tok in STOPWORDS:
            continue
        tok = _stem(tok)
        tok = SYNONYMS.get(tok, tok)
        if not tok or tok in STOPWORDS:
            continue
        if len(tok) == 1 and tok not in _KEEP_SHORT and tok.isascii():
            continue
        out.append(tok)
    return out


def need_key(tokens: list[str]) -> str:
    return " ".join(sorted(set(tokens)))


# --------------------------------------------------------------------------------------------
# Budget
# --------------------------------------------------------------------------------------------

_NUM = r"(\d[\d,]*(?:\.\d+)?)"
_CUE_BEFORE = re.compile(
    r"(?:under|below|less than|within|upto|up to|max(?:imum)?|budget(?: of)?|around|<=?)\s*(?:rs\.?|inr|₹)?\s*"
    + _NUM,
    re.I,
)
_CUE_AFTER = re.compile(
    _NUM + r"\s*(?:rs\.?|rupees|₹)?\s*(?:se kam|ke andar|ke neeche|tak|lopu|లోపు|से कम|के अंदर|तक)", re.I
)
_CURRENCY = re.compile(r"(?:₹|rs\.?|inr)\s*" + _NUM, re.I)


def parse_budget(text: str) -> tuple[float | None, str]:
    """Extract a price ceiling. Returns (budget, text-without-budget-phrase)."""
    for rx in (_CUE_BEFORE, _CUE_AFTER, _CURRENCY):
        m = rx.search(text)
        if m:
            try:
                val = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            return val, (text[: m.start()] + " " + text[m.end() :]).strip()
    return None, text


# --------------------------------------------------------------------------------------------
# Language, intent
# --------------------------------------------------------------------------------------------


def detect_language(text: str) -> str:
    te = sum(1 for c in text if "ఀ" <= c <= "౿")
    hi = sum(1 for c in text if "ऀ" <= c <= "ॿ")
    if te > hi and te >= 2:
        return "te"
    if hi >= 2:
        return "hi"
    toks = set(tokenize(text))
    if toks & _ROMAN_TE:
        return "te"
    if toks & _ROMAN_HI:
        return "hi"
    return "en"


def is_affirmative(text: str) -> bool:
    toks = tokenize(text)
    return 0 < len(toks) <= 5 and bool(set(toks) & _AFFIRM) and not (set(toks) & _NEGATE)


def is_negative(text: str) -> bool:
    toks = tokenize(text)
    return 0 < len(toks) <= 5 and bool(set(toks) & _NEGATE)


def is_greeting(text: str) -> bool:
    toks = tokenize(text)
    return 0 < len(toks) <= 3 and bool(set(toks) & _GREET)


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\s-]?){10,13}(?!\d)")


def scrub_pii(text: str) -> str:
    """Mask e-mail addresses and phone numbers before anything is persisted or logged."""
    text = _EMAIL.sub("[email]", text)
    return _PHONE.sub("[phone]", text)


def sanitize_user_text(text: str, limit: int = 400) -> str:
    """Strip control characters and cap length (first line of defence against abusive input)."""
    cleaned = "".join(ch for ch in text if ch == "\n" or ch >= " ")
    return cleaned.strip()[:limit]
