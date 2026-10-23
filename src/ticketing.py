"""Structured support-ticket workflow, routing, deduplication and SLA (Task 3)."""
from __future__ import annotations
import hashlib,re
from dataclasses import dataclass,asdict,field
from datetime import datetime,timedelta
from typing import Any
from .advanced_config import advanced_settings
from .security import mask_sensitive_data

ORDER=re.compile(r'(?i)\border(?:\s*id)?\s*[:#-]?\s*([A-Z0-9-]{4,30})')
EMAIL=re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}')
PRODUCT=re.compile(r'(?i)\b(?:product|item|course)\s*[:#-]?\s*([^\n,;]{2,80})')
HIGH=('account compromised','hacked','duplicate payment','charged twice','legal','fraud','safety')

@dataclass
class Ticket:
    ticket_id:str; customer:str=''; order_id:str=''; product:str=''; issue:str=''; evidence:list[str]=field(default_factory=list); contact:str=''; priority:str='normal'; status:str='open'; queue:str='general'; created_at:str=''; related:list[str]=field(default_factory=list); handoff_summary:str=''

class TicketWorkflow:
    def __init__(self): self.tickets:dict[str,Ticket]={}; self.agents:list[dict[str,Any]]=[]
    def extract(self,text:str,customer:str='',evidence:list[str]|None=None)->dict[str,Any]:
        o=ORDER.search(text); e=EMAIL.search(text); p=PRODUCT.search(text)
        issue=re.sub(EMAIL,'[EMAIL]',text).strip()
        return {'customer':customer,'order_id':o.group(1) if o else '','product':p.group(1).strip() if p else '','issue':issue,'evidence':evidence or [],'contact':e.group(0) if e else ''}
    def missing(self,d): return [k for k in ('customer','issue','contact') if not d.get(k)]
    def priority(self,text:str,sentiment='neutral',waiting_minutes=0,impact=1,sla_minutes=240):
        t=text.lower(); score=impact+(3 if any(x in t for x in HIGH) else 0)+(2 if sentiment in {'urgent','frustrated'} else 1 if sentiment=='negative' else 0)+(2 if waiting_minutes>=.75*sla_minutes else 0)
        return 'critical' if score>=6 else 'high' if score>=4 else 'normal' if score>=2 else 'low'
    def fingerprint(self,d): return hashlib.sha256('|'.join([d.get('customer','').lower(),d.get('order_id','').lower(),re.sub(r'\W+',' ',d.get('issue','').lower())[:120]]).encode()).hexdigest()
    def create(self,text:str,customer='',evidence=None,now:datetime|None=None,**kw):
        d=self.extract(text,customer,evidence); missing=self.missing(d)
        if missing:return {'status':'needs_information','missing':missing,'prompt':'Please provide: '+', '.join(missing)+'.'}
        fp=self.fingerprint(d)
        for t in self.tickets.values():
            if getattr(t,'_fp','')==fp:return {'status':'duplicate','ticket_id':t.ticket_id}
        tid='TKT-'+hashlib.sha256((fp+str(len(self.tickets))).encode()).hexdigest()[:8].upper(); now=now or datetime.now()
        pr=self.priority(text,kw.get('sentiment','neutral'),kw.get('waiting_minutes',0),kw.get('impact',1),kw.get('sla_minutes',240))
        ticket=Ticket(tid,**d,priority=pr,created_at=now.isoformat()); ticket._fp=fp; ticket.queue=self.route(ticket,now); ticket.handoff_summary=mask_sensitive_data(f"Customer {ticket.customer}; order {ticket.order_id or 'not provided'}; product {ticket.product or 'not provided'}; issue: {ticket.issue}; evidence: {', '.join(ticket.evidence) or 'none'}; priority {ticket.priority}.")
        self.tickets[tid]=ticket; return {'status':'created','ticket':asdict(ticket)}
    def route(self,ticket:Ticket,now:datetime):
        required='payments' if any(x in ticket.issue.lower() for x in ('payment','refund','charged')) else 'security' if any(x in ticket.issue.lower() for x in ('hacked','compromised','fraud')) else 'general'
        business=now.weekday() not in advanced_settings.weekends and advanced_settings.business_start_hour<=now.hour<advanced_settings.business_end_hour
        eligible=[a for a in self.agents if a.get('available') and required in a.get('skills',[]) ]
        if not business:return 'on-call' if ticket.priority in {'critical','high'} else 'next-working-day'
        if not eligible:return 'overflow'
        return min(eligible,key=lambda a:a.get('workload',0)).get('name','overflow')
    @staticmethod
    def business_minutes(start:datetime,end:datetime,holidays=None,weekends=None):
        holidays=set(holidays or advanced_settings.holidays); weekends=set(weekends or advanced_settings.weekends); cur=start; mins=0
        while cur<end:
            nxt=min(end,cur+timedelta(minutes=1))
            if cur.weekday() not in weekends and cur.date().isoformat() not in holidays and advanced_settings.business_start_hour<=cur.hour<advanced_settings.business_end_hour: mins+=1
            cur=nxt
        return mins
    def sla_status(self,created:datetime,now:datetime,allowed_minutes:int):
        used=self.business_minutes(created,now); ratio=used/max(1,allowed_minutes)
        return {'used_minutes':used,'allowed_minutes':allowed_minutes,'warning':.75<=ratio<1,'breached':ratio>=1,'fraction':ratio,'action':'escalate' if ratio>=1 else 'warn' if ratio>=.75 else 'none'}

    def group_related(self,ticket_ids:list[str])->list[list[str]]:
        """Group related requests by order/product; unrelated issues remain separate."""
        groups=[]
        for tid in ticket_ids:
            t=self.tickets[tid]; placed=False
            for g in groups:
                x=self.tickets[g[0]]
                if (t.order_id and t.order_id==x.order_id) or (t.product and t.product.lower()==x.product.lower()): g.append(tid); placed=True; break
            if not placed: groups.append([tid])
        return groups
