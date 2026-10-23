"""Language detection, mixed-language support and isolated session management (Task 6)."""
from __future__ import annotations
import re,uuid
from dataclasses import dataclass,field
from datetime import datetime,timedelta
from .advanced_config import advanced_settings
DEV=re.compile(r'[\u0900-\u097f]'); LATIN=re.compile(r'[A-Za-z]')
HINDI_LATIN={'kya','hai','nahi','mera','meri','mujhe','mujko','kr','kar','kaise','abhi','jaldi','order','paisa','refund','chahiye'}
ES={'hola','gracias','pedido','reembolso','problema','por','favor','necesito'}; FR={'bonjour','merci','commande','remboursement','problème','besoin','svp'}
PRESERVE=re.compile(r'\b(?:[A-Z]{2,}[A-Z0-9-]*|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|[A-Z0-9]{4,}-[A-Z0-9-]+)\b')

def detect_language(text: str):
    toks = set(re.findall(r"[\w'-]+", text.lower()))

    scores = {
        'hi': len(toks & HINDI_LATIN) + (3 if DEV.search(text) else 0),
        'es': len(toks & ES),
        'fr': len(toks & FR),
        'en': 0
    }

    # English gets a baseline score only when no stronger
    # Hindi/Spanish/French evidence exists.
    if LATIN.search(text):
        scores['en'] = 1

    # Common English words give stronger evidence for English.
    english_words = {
    'hello', 'hi', 'with', 'my', 'your', 'the',
    'is', 'are', 'need', 'want', 'can', 'you',
    'where', 'what'
}

    scores['en'] += len(toks & english_words)

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    lang, top = ranked[0]

    total = sum(scores.values()) or 1

    mixed = [
        k for k, v in scores.items()
        if v > 0 and k != lang and
        (v >= 2 or (k == 'en' and top >= 2))
    ]

    conf = top / total if top else 0.0

    # Hindi + English mixed-language message
    if DEV.search(text) and LATIN.search(text):
        mixed = list(set(mixed + ['hi', 'en']))
        conf = max(conf, 0.75)

    return {
        'language': lang,
        'confidence': round(conf, 3),
        'mixed_with': mixed,
        'supported': lang in advanced_settings.supported_languages
    }

def preserved_tokens(text): return PRESERVE.findall(text)

@dataclass
class Session:
    session_id:str; customer_id:str; created_at:datetime; last_active:datetime; messages:list[dict]=field(default_factory=list); summary:str=''; active:bool=True

class SessionManager:
    def __init__(self): self.sessions:dict[str,Session]={}; self.customer_last:dict[str,str]={}
    def start_or_restore(self,customer_id:str,now:datetime|None=None):
        now=now or datetime.now(); sid=self.customer_last.get(customer_id); old=self.sessions.get(sid) if sid else None
        if old:
            idle=now-old.last_active
            if idle<=timedelta(minutes=advanced_settings.session_inactivity_minutes): return old,'active'
            old.active=False; old.summary=self._summary(old)
            if idle<=timedelta(hours=advanced_settings.session_restore_hours):
                s=Session(str(uuid.uuid4()),customer_id,now,now,summary=old.summary); self.sessions[s.session_id]=s; self.customer_last[customer_id]=s.session_id; return s,'restored'
        s=Session(str(uuid.uuid4()),customer_id,now,now); self.sessions[s.session_id]=s; self.customer_last[customer_id]=s.session_id; return s,'new'
    def add(self,session_id:str,role:str,text:str,now:datetime|None=None):
        s=self.sessions[session_id]; s.messages.append({'role':role,'text':text}); s.messages=s.messages[-advanced_settings.context_messages:]; s.last_active=now or datetime.now(); return s
    def _summary(self,s): return ' | '.join(m['text'] for m in s.messages[-advanced_settings.context_messages:])[-1500:]
    def expire(self,now:datetime|None=None):
        now=now or datetime.now(); n=0
        for s in self.sessions.values():
            if s.active and now-s.last_active>timedelta(minutes=advanced_settings.session_inactivity_minutes): s.active=False;s.summary=self._summary(s);n+=1
        return n
