"""Production-style knowledge-base release pipeline."""
from __future__ import annotations
import hashlib,json,uuid
from datetime import datetime,timedelta
from pathlib import Path
from typing import Any
from .config import settings
from .evaluator import compare_quality,evaluate_index
from .knowledge_base import KnowledgeBaseManager
from .security import User,require_admin
from .storage import get_version_status,record_audit,save_version,set_active_version,update_version_status,list_versions,init_database,get_previous_version

def _fingerprint(records):
    items=sorted((r.path,r.sha256,r.normalized_sha256) for r in records if r.status in {"accepted","unchanged"})
    return hashlib.sha256(json.dumps(items,sort_keys=True).encode()).hexdigest()

class UpdatePipeline:
    def __init__(self):
        init_database(); self.kb=KnowledgeBaseManager(); self.kb._ensure_directories()
    @staticmethod
    def _parse_clock(value): return tuple(map(int,value.split(":")))
    @staticmethod
    def is_maintenance_window(now=None):
        now=now or datetime.now(); sh,sm=UpdatePipeline._parse_clock(settings.maintenance_start); eh,em=UpdatePipeline._parse_clock(settings.maintenance_end)
        start=now.replace(hour=sh,minute=sm,second=0,microsecond=0); end=now.replace(hour=eh,minute=em,second=0,microsecond=0)
        return start<=now<=end if start<=end else now>=start or now<=end
    @staticmethod
    def is_scheduled_time(now=None):
        now=now or datetime.now(); h,m=UpdatePipeline._parse_clock(settings.scheduled_update_time); return now.hour==h and now.minute==m
    def scan(self):
        records,rows=self.kb.inspect_documents(); return {"records":records,"rows":rows,"accepted":[r for r in records if r.status in {"accepted","unchanged"}],"changed":[r for r in records if r.changed and r.status=="accepted"],"duplicates":[r for r in records if r.status=="duplicate"],"quarantined":[r for r in records if r.status=="quarantined"],"fingerprint":_fingerprint(records)}
    def _evaluation_set(self,index): return [{"question":q,"answer":a} for q,a in zip(index["questions"],index["responses"])]
    def stage_candidate(self):
        scan=self.scan()
        if not scan["accepted"]: raise ValueError("No valid documents are available.")
        manifest_file=settings.runtime_dir/"source_fingerprint.txt"
        if manifest_file.exists() and manifest_file.read_text(encoding="utf-8")==scan["fingerprint"]: return {"status":"unchanged",**scan}
        version_id,manifest=self.kb.build_candidate(scan["rows"],scan["records"]); return {"status":"staged","version_id":version_id,**scan,"manifest":manifest}
    def quality_gate(self,candidate_version):
        candidate=self.kb.load_version(candidate_version); active=self.kb.active_version()
        if not active:
            report=evaluate_index(candidate,self._evaluation_set(candidate)); passed=report.passed
            update_version_status(candidate_version,"approved" if passed else "rejected",{**report.details,"accuracy":report.accuracy,"grounding":report.grounding})
            return {"passed":passed,"candidate":report}
        baseline=self.kb.load_version(active); evaluation=self._evaluation_set(baseline)
        base_report=evaluate_index(baseline,evaluation); cand_report=evaluate_index(candidate,evaluation)
        comparison=compare_quality(base_report,cand_report,settings.quality_accuracy_tolerance,settings.quality_grounding_tolerance)
        update_version_status(candidate_version,"approved" if comparison.passed else "rejected",{**comparison.details,"accuracy":comparison.accuracy,"grounding":comparison.grounding})
        return {"passed":comparison.passed,"baseline":base_report,"candidate":comparison}
    def _write_health_pending(self,version,previous,activated_at):
        data={"version":version,"previous_version":previous,"activated_at":activated_at,"deadline":(datetime.fromisoformat(activated_at)+timedelta(minutes=settings.health_check_minutes)).isoformat()}
        (settings.runtime_dir/"health_pending.json").write_text(json.dumps(data,indent=2),encoding="utf-8")
    def activate(self,candidate_version,now=None,health_ok=True,user:User|None=None):
        if user is not None: require_admin(user)
        if get_version_status(candidate_version)!="approved": return {"status":"blocked","reason":"Only a quality-approved version can be activated."}
        if not self.is_maintenance_window(now): return {"status":"blocked","reason":"Activation is only allowed during the maintenance window."}
        previous=self.kb.active_version(); self.kb.activate_version(candidate_version); set_active_version(candidate_version)
        activated_at=(now or datetime.now()).isoformat(); self._write_health_pending(candidate_version,previous,activated_at)
        record_audit("activate_version","success",details={"version":candidate_version,"previous_version":previous,"health_window_minutes":settings.health_check_minutes})
        if not health_ok: return self.complete_health_check(candidate_version,False)
        return {"status":"active","version":candidate_version,"health_check_due_at":json.loads((settings.runtime_dir/"health_pending.json").read_text())["deadline"]}
    def rollback(self,version_id=None,reason="Manual rollback",user:User|None=None):
        if user is not None: require_admin(user)
        target=version_id or get_previous_version()
        if not target: record_audit("rollback","failed",details={"reason":"No previous version available"}); return None
        self.kb.activate_version(target); set_active_version(target); record_audit("rollback","success",details={"version":target,"reason":reason})
        p=settings.runtime_dir/"health_pending.json"
        if p.exists(): p.unlink()
        return target
    def complete_health_check(self,activated_version,healthy):
        p=settings.runtime_dir/"health_pending.json"; pending=json.loads(p.read_text()) if p.exists() else {}
        if pending.get("version") and pending["version"]!=activated_version: return {"status":"blocked","reason":"Health check does not match the pending release."}
        if healthy:
            if p.exists(): p.unlink()
            record_audit("post_activation_health_check","success",details={"version":activated_version,"window_minutes":settings.health_check_minutes}); return {"status":"healthy","version":activated_version}
        previous=pending.get("previous_version") or get_previous_version(exclude=activated_version)
        rolled=self.rollback(previous,reason=f"Automatic rollback after failed health checks within {settings.health_check_minutes} minutes") if previous else None
        return {"status":"rolled_back" if rolled else "rollback_failed","version":rolled,"reason":f"Health checks failed within {settings.health_check_minutes} minutes."}
    def run(self,now=None,health_ok=True):
        staged=self.stage_candidate()
        if staged["status"]=="unchanged": return {"status":"unchanged","message":"No new or modified documents detected."}
        quality=self.quality_gate(staged["version_id"])
        if not quality["passed"]:
            record_audit("quality_gate","rejected",details={"version":staged["version_id"],"quality":quality["candidate"].details}); return {"status":"rejected","quality":quality}
        now=now or datetime.now()
        if not self.is_maintenance_window(now):
            record_audit("activation","deferred",details={"version":staged["version_id"]}); return {"status":"approved_waiting_for_maintenance","version":staged["version_id"]}
        result=self.activate(staged["version_id"],now=now,health_ok=health_ok)
        if result.get("status") in {"active","healthy","rolled_back"}:
            (settings.runtime_dir/"source_fingerprint.txt").write_text(staged["fingerprint"],encoding="utf-8")
        return {"status":result["status"],"version":result.get("version"),"quality":quality}
    def retry_times(self,failed_at=None):
        failed_at=failed_at or datetime.now(); elapsed=0; times=[]
        for delay in settings.retry_delays: elapsed+=delay; times.append(failed_at+timedelta(minutes=elapsed))
        return times
