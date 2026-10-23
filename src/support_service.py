"""Unified service façade integrating Tasks 1-6 without coupling the UI to internals."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from .chatbot import CustomerServiceChatbot
from .media_analysis import MediaAnalyzer
from .ticketing import TicketWorkflow
from .sentiment import escalation_decision
from .multilingual import SessionManager, detect_language
from .policy_rag import PolicyRAG
from .security import mask_sensitive_data

class SupportService:
    def __init__(self):
        self.chatbot=CustomerServiceChatbot(); self.media=MediaAnalyzer(); self.tickets=TicketWorkflow(); self.sessions=SessionManager(); self.policies=PolicyRAG()
    def handle_message(self,customer_id:str,message:str,now:datetime|None=None):
        now=now or datetime.now(); session,state=self.sessions.start_or_restore(customer_id,now); history=[m['text'] for m in session.messages if m['role']=='user']
        lang=detect_language(message)
        if not lang['supported'] or lang['confidence']<0.30:
            answer={'answer':'I am not confident about the language or intent. Please rephrase your request.','score':0.0,'escalated':False}
        else: answer=self.chatbot.answer(message)
        esc=escalation_decision(message,history,now)
        self.sessions.add(session.session_id,'user',message,now); self.sessions.add(session.session_id,'assistant',answer['answer'],now)
        return {'session_id':session.session_id,'session_state':state,'language':lang,'sentiment':esc['sentiment'],'escalation':esc,'answer':answer}
    def analyze_upload(self,path:Path,message:str=''): return self.media.analyze(path,message)
    def create_ticket(self,customer_id:str,message:str,**kwargs): return self.tickets.create(message,customer=customer_id,**kwargs)
