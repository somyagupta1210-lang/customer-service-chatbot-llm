"""Configuration helpers for Tasks 2-6. Values are runtime-configurable via env."""
from __future__ import annotations
import os
from dataclasses import dataclass

def _i(n,d):
    try:return int(os.getenv(n,str(d)))
    except:return d

def _f(n,d):
    try:return float(os.getenv(n,str(d)))
    except:return d

def _csv(n,d): return tuple(x.strip() for x in os.getenv(n,d).split(',') if x.strip())

@dataclass(frozen=True)
class AdvancedSettings:
    upload_retention_minutes:int=_i('UPLOAD_RETENTION_MINUTES',60)
    media_background_after_seconds:int=_i('MEDIA_BACKGROUND_AFTER_SECONDS',30)
    max_upload_mb:int=_i('MAX_UPLOAD_MB',10)
    supported_upload_extensions:tuple[str,...]=_csv('SUPPORTED_UPLOAD_EXTENSIONS','.png,.jpg,.jpeg,.webp,.pdf,.txt')
    supported_languages:tuple[str,...]=_csv('SUPPORTED_LANGUAGES','en,hi,es,fr')
    language_confidence_threshold:float=_f('LANGUAGE_CONFIDENCE_THRESHOLD',0.55)
    intent_confidence_threshold:float=_f('INTENT_CONFIDENCE_THRESHOLD',0.45)
    session_inactivity_minutes:int=_i('SESSION_INACTIVITY_MINUTES',30)
    session_restore_hours:int=_i('SESSION_RESTORE_HOURS',24)
    context_messages:int=_i('CONTEXT_MESSAGES',10)
    business_start_hour:int=_i('BUSINESS_START_HOUR',9)
    business_end_hour:int=_i('BUSINESS_END_HOUR',18)
    weekends:tuple[int,...]=tuple(int(x) for x in _csv('WEEKEND_DAYS','5,6'))
    holidays:tuple[str,...]=_csv('HOLIDAYS','')
    negative_escalation_minutes:int=_i('NEGATIVE_ESCALATION_MINUTES',15)
    sla_warning_fraction:float=_f('SLA_WARNING_FRACTION',0.75)
advanced_settings=AdvancedSettings()
