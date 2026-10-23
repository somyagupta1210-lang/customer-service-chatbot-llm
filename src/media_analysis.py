"""Safe multimodal evidence analysis (Task 2). OCR dependencies are optional."""
from __future__ import annotations
import hashlib, re, time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from .advanced_config import advanced_settings
from .security import detect_prompt_injection, mask_sensitive_data

ORDER=[re.compile(r'(?i)\b(?:order(?:\s*id)?|order\s*#)\s*[:#-]?\s*([A-Z0-9-]{4,30})')]
AMOUNT=re.compile(r'(?i)(?:₹|rs\.?|inr|\$|usd|€)\s*([0-9][0-9,]*(?:\.\d{1,2})?)')
DATE=re.compile(r'\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b')
ERROR=re.compile(r'(?i)\b(?:error|code)\s*[:#-]?\s*([A-Z]{1,8}[-_]?[0-9]{2,8}|[0-9]{3,8})\b')
PRODUCT=re.compile(r'(?i)\b(?:product|item|course)\s*[:#-]?\s*([^\n,;]{2,80})')
HIDDEN_INJECTION=("ignore previous instructions","system prompt","developer message","reveal hidden","bypass safety","jailbreak")

@dataclass
class Evidence:
    order_ids:list[str]; dates:list[str]; amounts:list[str]; products:list[str]; error_codes:list[str]
    text:str=''; confidence:float=0.0
    def safe_dict(self):
        d=asdict(self); d['text']=mask_sensitive_data(d['text']); return d

def extract_fields(text:str)->Evidence:
    clean=text or ''
    orders=[]
    for p in ORDER: orders += p.findall(clean)
    vals=lambda xs:list(dict.fromkeys(x.strip() for x in xs if x.strip()))
    products=vals(PRODUCT.findall(clean))
    # prevent product regex from swallowing obvious labels on same line
    products=[re.split(r'(?i)\s+(?:amount|date|error|order)\s*:',p)[0].strip() for p in products]
    found=sum(bool(x) for x in (orders,DATE.findall(clean),AMOUNT.findall(clean),products,ERROR.findall(clean)))
    return Evidence(vals(orders),vals(DATE.findall(clean)),vals(AMOUNT.findall(clean)),vals(products),vals(ERROR.findall(clean)),clean,min(1.0,0.35+found*0.13) if clean.strip() else 0.0)

def compare_evidence(message:str,e:Evidence)->dict[str,Any]:
    m=extract_fields(message); conflicts=[]
    for key in ('order_ids','dates','amounts','error_codes'):
        a,b=set(getattr(m,key)),set(getattr(e,key))
        if a and b and a.isdisjoint(b): conflicts.append(key)
    if m.products and e.products and not any(a.lower() in b.lower() or b.lower() in a.lower() for a in m.products for b in e.products): conflicts.append('products')
    return {'conflicts':conflicts,'matches':not conflicts,'message_evidence':m.safe_dict(),'file_evidence':e.safe_dict()}

class MediaAnalyzer:
    def __init__(self, upload_dir:Path|None=None):
        from .config import settings
        self.upload_dir=upload_dir or settings.data_dir/'uploads'; self.upload_dir.mkdir(parents=True,exist_ok=True)
    def _validate(self,path:Path):
        if path.suffix.lower() not in advanced_settings.supported_upload_extensions: raise ValueError('Unsupported file type')
        if path.stat().st_size>advanced_settings.max_upload_mb*1024*1024: raise ValueError('File too large')
        if path.stat().st_size==0: raise ValueError('Empty file')
        head=path.read_bytes()[:32]
        if path.suffix.lower() in {'.png','.jpg','.jpeg','.webp'} and not (head.startswith(b'\x89PNG') or head.startswith(b'\xff\xd8') or head.startswith(b'RIFF')): raise ValueError('Invalid image file')
        if path.suffix.lower()=='.pdf' and not head.startswith(b'%PDF'): raise ValueError('Invalid PDF file')
    def _text(self,path:Path)->tuple[str,float]:
        ext=path.suffix.lower()
        if ext=='.txt': return path.read_text(encoding='utf-8',errors='strict'),1.0
        if ext=='.pdf':
            try:
                from pypdf import PdfReader
                txt='\n'.join((p.extract_text() or '') for p in PdfReader(str(path)).pages)
                if txt.strip(): return txt,0.95
            except Exception: pass
        try:
            from PIL import Image, ImageStat
            import pytesseract
            if ext=='.pdf':
                # no unsafe shell conversion: request clearer/text PDF if PDF has no text layer
                return '',0.0
            im=Image.open(path).convert('L')
            stat=ImageStat.Stat(im); contrast=stat.stddev[0]
            txt=pytesseract.image_to_string(im,config='--psm 6')
            quality=min(1.0,max(0.15,contrast/60.0)) if txt.strip() else 0.0
            return txt,quality
        except Exception:return '',0.0
    def analyze(self,path:Path,message:str='',simulate_delay:float=0)->dict[str,Any]:
        start=time.perf_counter(); self._validate(path)
        if simulate_delay>advanced_settings.media_background_after_seconds:
            return {'status':'queued','message':'Processing is taking longer than 30 seconds. Your file was moved to the background queue.','job_id':hashlib.sha256(str(path).encode()).hexdigest()[:12]}
        text,quality=self._text(path)
        lower=text.lower()
        if detect_prompt_injection(text) or any(x in lower for x in HIDDEN_INJECTION):
            return {'status':'rejected','reason':'Unsafe instructions detected inside uploaded evidence.'}
        ev=extract_fields(text); ev.confidence=min(ev.confidence,quality) if quality else ev.confidence
        comparison=compare_evidence(message,ev)
        if not text.strip() or quality<0.35:
            status='clarification'; reason='Image/file quality is too low for reliable extraction. Please upload a clearer file.'
        elif comparison['conflicts']:
            status='clarification'; reason='Uploaded evidence conflicts with the customer message for: '+', '.join(comparison['conflicts'])+'. Please clarify or upload the correct file.'
        else: status='ok'; reason='Evidence extracted successfully.'
        return {'status':status,'reason':reason,'evidence':ev.safe_dict(),'comparison':comparison,'quality':round(quality,3),'latency_ms':round((time.perf_counter()-start)*1000,2)}
    def purge_expired(self,now:datetime|None=None)->int:
        now=now or datetime.now(timezone.utc); n=0
        for p in self.upload_dir.glob('*'):
            try:
                age=now-datetime.fromtimestamp(p.stat().st_mtime,timezone.utc)
                if age>=timedelta(minutes=advanced_settings.upload_retention_minutes): p.unlink(); n+=1
            except FileNotFoundError: pass
        return n
