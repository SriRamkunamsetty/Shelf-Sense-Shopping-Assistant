"""Shopper-facing copy in English, Hindi and Telugu (used by the deterministic engine and by
outreach). Gemini writes its own wording in the shopper's language when the LLM path is active."""

from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "greeting": "Hi {name}! I'm ShelfSense, the store's shopping assistant. Tell me what you're looking for — in English, हिंदी or తెలుగు — and add a budget if you like (e.g. “wireless earbuds under 1000”).",
        "in_stock": "Yes — we have it! {items}",
        "out_of_stock": "{items} is out of stock right now. Want me to message you the moment it's back?",
        "over_budget": "We have {items}, but it's above your ₹{budget:.0f} budget. Want me to let you know if a cheaper option or an offer comes up?",
        "partial": "We don't have exactly “{need}” yet. Closest in stock: {items}. I've passed your request to the store owner. Want me to message you if we get it?",
        "not_carried": "We don't stock “{need}” yet — I've passed your request to the store owner. Want me to message you if it arrives?",
        "alt": "Meanwhile, similar items in stock: {items}.",
        "waitlisted": "Done — you're on the list. I'll message you as soon as “{need}” is available. You can opt out anytime.",
        "declined": "No problem! Ask me anything else.",
        "no_pending": "Got it. What else can I help you find?",
    },
    "hi": {
        "greeting": "नमस्ते {name}! मैं ShelfSense हूँ, दुकान का शॉपिंग असिस्टेंट। बताइए आपको क्या चाहिए — हिंदी, English या తెలుగు में — चाहें तो बजट भी बताएँ (जैसे “wireless earbuds 1000 से कम”)।",
        "in_stock": "जी हाँ, उपलब्ध है! {items}",
        "out_of_stock": "{items} अभी स्टॉक में नहीं है। वापस आते ही क्या मैं आपको संदेश भेज दूँ?",
        "over_budget": "{items} उपलब्ध है, लेकिन आपके ₹{budget:.0f} के बजट से ज़्यादा है। सस्ता विकल्प या ऑफर आने पर बताऊँ?",
        "partial": "“{need}” बिल्कुल वैसा अभी नहीं है। सबसे नज़दीकी विकल्प: {items}। मैंने आपकी माँग दुकान मालिक तक पहुँचा दी है। मिलने पर क्या मैं आपको बता दूँ?",
        "not_carried": "“{need}” अभी हमारे पास नहीं है — आपकी माँग दुकान मालिक तक पहुँचा दी है। आने पर क्या मैं आपको संदेश भेजूँ?",
        "alt": "तब तक, मिलते-जुलते उपलब्ध सामान: {items}।",
        "waitlisted": "ठीक है — आप सूची में हैं। “{need}” आते ही मैं आपको संदेश भेजूँगा। आप कभी भी मना कर सकते हैं।",
        "declined": "कोई बात नहीं! कुछ और चाहिए तो बताइए।",
        "no_pending": "ठीक है। और क्या ढूँढ़ने में मदद करूँ?",
    },
    "te": {
        "greeting": "నమస్తే {name}! నేను ShelfSense, స్టోర్ షాపింగ్ అసిస్టెంట్‌ని. మీకు ఏం కావాలో చెప్పండి — తెలుగు, हिंदी లేదా English లో — బడ్జెట్ కూడా చెప్పవచ్చు (ఉదా. “wireless earbuds 1000 లోపు”).",
        "in_stock": "అవును, అందుబాటులో ఉంది! {items}",
        "out_of_stock": "{items} ప్రస్తుతం స్టాక్‌లో లేదు. మళ్లీ వచ్చిన వెంటనే మీకు మెసేజ్ పంపమంటారా?",
        "over_budget": "{items} ఉంది, కానీ మీ ₹{budget:.0f} బడ్జెట్ కంటే ఎక్కువ. తక్కువ ధరలో ఎంపిక లేదా ఆఫర్ వస్తే చెప్పమంటారా?",
        "partial": "“{need}” సరిగ్గా అదే ఇంకా లేదు. దగ్గరగా ఉన్నవి: {items}. మీ అభ్యర్థనను స్టోర్ యజమానికి పంపాను. వస్తే మీకు చెప్పమంటారా?",
        "not_carried": "“{need}” ఇంకా మా వద్ద లేదు — మీ అభ్యర్థనను స్టోర్ యజమానికి పంపాను. వస్తే మీకు మెసేజ్ పంపమంటారా?",
        "alt": "ఈలోగా, ఇలాంటివి స్టాక్‌లో ఉన్నాయి: {items}.",
        "waitlisted": "సరే — మీరు జాబితాలో ఉన్నారు. “{need}” అందుబాటులోకి రాగానే మెసేజ్ పంపుతాను. ఎప్పుడైనా వద్దని చెప్పవచ్చు.",
        "declined": "పర్వాలేదు! ఇంకేమైనా కావాలంటే అడగండి.",
        "no_pending": "సరే. ఇంకేం వెతకాలి?",
    },
}


def msg(lang: str, key: str, **kw: object) -> str:
    table = MESSAGES.get(lang) or MESSAGES["en"]
    return (table.get(key) or MESSAGES["en"][key]).format(**kw)
