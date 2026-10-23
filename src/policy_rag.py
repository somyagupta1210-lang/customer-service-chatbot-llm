"""Metadata-aware, citation-required policy RAG (Task 4)."""
from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from .security import detect_prompt_injection

@dataclass
class PolicyDoc:
    doc_id:str; text:str; version:int=1; product:str='*'; region:str='*'; access_level:str='public'; effective_date:str='1900-01-01'; expiry_date:str|None=None; source:str='unknown'

class PolicyRAG:
    def __init__(self,docs=None): self.docs=list(docs or [])
    def add(self,doc:PolicyDoc):
        if detect_prompt_injection(doc.text): raise ValueError('Prompt-injected document rejected')
        self.docs.append(doc)
    def retrieve(self,query:str,product='*',region='*',access_levels=('public',),as_of:date|None=None):
        target=as_of or date.today(); q=set(re.findall(r'[a-z0-9]+',query.lower())); out=[]
        for d in self.docs:
            if d.access_level not in access_levels or d.product not in ('*',product) or d.region not in ('*',region): continue
            eff=date.fromisoformat(d.effective_date); exp=date.fromisoformat(d.expiry_date) if d.expiry_date else None
            if not (eff<=target and (exp is None or target<=exp)): continue
            if detect_prompt_injection(d.text): continue
            words=set(re.findall(r'[a-z0-9]+',d.text.lower())); score=len(q&words)/max(1,len(q))
            if score: out.append((score,d))
        out.sort(key=lambda x:(x[0],date.fromisoformat(x[1].effective_date),x[1].version),reverse=True)
        # latest applicable version wins for same logical doc id/source
        chosen=[]; seen=set()
        for score,d in out:
            key=(d.doc_id,d.product,d.region)
            if key not in seen: chosen.append((score,d)); seen.add(key)
        return chosen
    def answer(self,query:str,**kwargs):
        hits=self.retrieve(query,**kwargs)
        if not hits:return {'status':'clarification','answer':'I cannot verify that from authorised, applicable sources. Please clarify or provide an approved source.','citations':[],'grounded':False}
        top_score,doc=hits[0]
        if top_score<0.15:return {'status':'clarification','answer':'The available evidence is ambiguous, so I cannot make a factual claim yet.','citations':[],'grounded':False}
        # extract best sentence, never generate unsupported facts
        sents=[s.strip() for s in re.split(r'(?<=[.!?])\s+',doc.text) if s.strip() and not detect_prompt_injection(s)]
        q=set(re.findall(r'[a-z0-9]+',query.lower()))
        best=max(sents,key=lambda s:len(q&set(re.findall(r'[a-z0-9]+',s.lower()))),default=doc.text[:500])
        citation=f"[{doc.source} | v{doc.version} | effective {doc.effective_date}]"
        return {'status':'ok','answer':best+' '+citation,'citations':[citation],'grounded':True,'doc_id':doc.doc_id}
