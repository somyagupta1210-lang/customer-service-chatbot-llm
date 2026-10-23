"""Lightweight multilingual/mixed-language sentiment + escalation policy (Task 5)."""
from __future__ import annotations
import re
from datetime import datetime,timedelta
from .advanced_config import advanced_settings
POS=('thanks','thank you','great','good','awesome','dhanyavad','shukriya','gracias','merci','अच्छा','धन्यवाद')
NEG=('bad','terrible','angry','upset','not working','bekar','bakwas','pareshan','gussa','mauvais','horrible','खराब','गुस्सा')
FRU=('again','still','already told','kitni baar','bar bar','baar baar','fed up','frustrated','encore','otra vez')
URG=('urgent','immediately','asap','abhi','jaldi','turant','urgente','immédiatement','तुरंत','जल्दी')
RISK=('account compromised','hacked','duplicate payment','charged twice','legal action','lawyer','fraud','unauthorised transaction')
SARCASTIC=(r'(?i)great[,. ]+(?:another|still|just)',r'(?i)wow[,. ]+.*(?:broken|failed|not)',r'(?i)thanks for nothing',r'(?i)kya baat hai.*(?:nahi|fail|band)')

def analyze_sentiment(message:str,history=None):
    history=history or []; t=message.lower(); scores={'positive':sum(x in t for x in POS),'negative':sum(x in t for x in NEG),'frustrated':sum(x in t for x in FRU),'urgent':sum(x in t for x in URG),'sarcastic':sum(bool(re.search(p,message)) for p in SARCASTIC)}
    if scores['sarcastic']: label='sarcastic'
    elif scores['urgent']:label='urgent'
    elif scores['frustrated'] or sum(any(x in h.lower() for x in NEG) for h in history[-4:])>=2:label='frustrated'
    elif scores['negative']:label='negative'
    elif scores['positive']:label='positive'
    else:label='neutral'
    mx=max(scores.values()); conf=.55 if label=='neutral' else min(.98,.62+.1*mx)
    return {'label':label,'confidence':conf,'scores':scores}

def escalation_decision(message:str,history=None,now:datetime|None=None,negative_since:datetime|None=None):
    now=now or datetime.now(); s=analyze_sentiment(message,history); reasons=[]; t=message.lower()
    risk=[x for x in RISK if x in t]
    if risk: reasons.append('high-risk issue: '+', '.join(risk))
    neg_count=sum(analyze_sentiment(h)['label'] in {'negative','frustrated','sarcastic','urgent'} for h in (history or [])[-4:])+int(s['label'] in {'negative','frustrated','sarcastic','urgent'})
    if neg_count>=3: reasons.append('repeated negative messages')
    if negative_since and now-negative_since>=timedelta(minutes=advanced_settings.negative_escalation_minutes): reasons.append('negative conversation unresolved for more than 15 minutes')
    business=now.weekday() not in advanced_settings.weekends and advanced_settings.business_start_hour<=now.hour<advanced_settings.business_end_hour
    if reasons:
        queue='on-call' if (not business and (s['label']=='urgent' or risk)) else 'escalation'
    elif not business and s['label'] in {'negative','frustrated'}: queue='next-working-day'
    else: queue='none'
    return {'escalate':bool(reasons),'queue':queue,'reason':'; '.join(reasons),'activated_condition':reasons,'sentiment':s,'conversation_summary':' | '.join((history or [])[-4:]+[message])[-1000:]}
