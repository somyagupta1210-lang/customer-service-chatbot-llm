"""Knowledge-base ingestion, change detection, duplicate handling and versioning."""
from __future__ import annotations
import hashlib, json, shutil
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import pandas as pd
from .config import settings
from .retrieval import LocalRetriever, normalize_text, save_index
from .storage import get_active_version, save_version, get_document, upsert_document

ALLOWED_EXTENSIONS = {".csv", ".txt", ".md", ".json"}

@dataclass
class DocumentRecord:
    path: str
    sha256: str
    normalized_sha256: str
    status: str
    reason: str = ""
    changed: bool = True

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def normalized_content_hash(text: str) -> str:
    return sha256_bytes(" ".join(text.lower().split()).encode("utf-8"))

def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "cp1252", "latin1"):
        try: return raw.decode(encoding)
        except UnicodeDecodeError: pass
    raise ValueError("File could not be decoded as UTF-8, Windows-1252 or Latin-1.")

def _rows_from_file(path: Path) -> list[tuple[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        from io import StringIO
        df = pd.read_csv(StringIO(_read_text(path)))
        required = {"prompt", "response"}
        missing = required - set(df.columns)
        if missing: raise ValueError(f"CSV is missing required columns: {sorted(missing)}")
        rows=[]
        for row in df[["prompt","response"]].dropna().itertuples(index=False):
            q=str(row.prompt).strip(); a=str(row.response).strip()
            if q and a: rows.append((q,a))
        if not rows: raise ValueError("CSV contains no valid question/answer rows.")
        return rows
    text=_read_text(path).strip()
    if not text: raise ValueError("Document is empty.")
    if suffix == ".json":
        try: data=json.loads(text)
        except json.JSONDecodeError as exc: raise ValueError(f"Invalid JSON: {exc.msg}") from exc
        if isinstance(data,dict): data=data.get("items",data.get("faqs",[]))
        if not isinstance(data,list): raise ValueError("JSON must contain a list of FAQ objects.")
        rows=[]
        for item in data:
            if not isinstance(item,dict) or not item.get("prompt") or not item.get("response"):
                raise ValueError("Every JSON FAQ must contain prompt and response.")
            rows.append((str(item["prompt"]).strip(),str(item["response"]).strip()))
        if not rows: raise ValueError("JSON contains no valid FAQ rows.")
        return rows
    rows=[]
    for line in text.splitlines():
        if "|" in line:
            q,a=line.split("|",1)
            if q.strip() and a.strip(): rows.append((q.strip(),a.strip()))
    if not rows: raise ValueError("TXT/MD must contain FAQ rows in 'question | answer' format.")
    return rows

class KnowledgeBaseManager:
    def __init__(self):
        self.retriever=LocalRetriever(); self._ensure_directories()
    def _ensure_directories(self):
        for d in (settings.incoming_dir,settings.versions_dir,settings.quarantine_dir,settings.runtime_dir): d.mkdir(parents=True,exist_ok=True)
    def source_files(self):
        files=[]
        if settings.dataset_path.exists(): files.append(settings.dataset_path)
        if settings.incoming_dir.exists(): files.extend(sorted(p for p in settings.incoming_dir.iterdir() if p.is_file()))
        return files
    def inspect_documents(self):
        records=[]; all_rows=[]; seen_hashes=set(); seen_norm=set()
        for path in self.source_files():
            raw=path.read_bytes(); digest=sha256_bytes(raw); norm_digest=normalized_content_hash(_read_text(path))
            old=get_document(str(path)); unchanged=bool(old and old["sha256"]==digest and old["normalized_sha256"]==norm_digest and old["status"] in {"accepted","unchanged"})
            if path.suffix.lower() not in ALLOWED_EXTENSIONS:
                records.append(DocumentRecord(str(path),digest,norm_digest,"quarantined","Unsupported file type",not unchanged)); self._quarantine(path,"unsupported_type"); upsert_document(str(path),digest,norm_digest,"quarantined","Unsupported file type",[]); continue
            if len(raw)>settings.max_document_size_mb*1024*1024:
                records.append(DocumentRecord(str(path),digest,norm_digest,"quarantined","File is too large",not unchanged)); self._quarantine(path,"too_large"); upsert_document(str(path),digest,norm_digest,"quarantined","File is too large",[]); continue
            if unchanged:
                rows=[tuple(x) for x in json.loads(old["rows_json"])]
                records.append(DocumentRecord(str(path),digest,norm_digest,"unchanged","No content change detected",False))
                for q,a in rows:
                    key=(normalize_text(q),normalize_text(a))
                    if key not in {(normalize_text(x),normalize_text(y)) for x,y in all_rows}: all_rows.append((q,a))
                seen_hashes.add(digest); seen_norm.add(norm_digest); continue
            if digest in seen_hashes or norm_digest in seen_norm:
                records.append(DocumentRecord(str(path),digest,norm_digest,"duplicate","Duplicate content detected",True)); upsert_document(str(path),digest,norm_digest,"duplicate","Duplicate content detected",[]); continue
            try: rows=_rows_from_file(path)
            except Exception as exc:
                records.append(DocumentRecord(str(path),digest,norm_digest,"quarantined",str(exc),True));
                if path.parent==settings.incoming_dir: self._quarantine(path,"invalid_document")
                upsert_document(str(path),digest,norm_digest,"quarantined",str(exc),[]); continue
            seen_hashes.add(digest); seen_norm.add(norm_digest)
            records.append(DocumentRecord(str(path),digest,norm_digest,"accepted","",True)); upsert_document(str(path),digest,norm_digest,"accepted","",rows)
            all_rows.extend(rows)
        unique=[]; seen_rows=set()
        for q,a in all_rows:
            key=(normalize_text(q),normalize_text(a))
            if key not in seen_rows: seen_rows.add(key); unique.append((q,a))
        return records,unique
    def _quarantine(self,path,reason):
        if path.parent!=settings.incoming_dir: return
        stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ%f"); shutil.move(str(path),str(settings.quarantine_dir/f"{stamp}_{reason}_{path.name}"))
    def build_candidate(self,rows,records):
        if not rows: raise ValueError("No valid documents were found for the candidate knowledge base.")
        index=self.retriever.build([q for q,_ in rows],[a for _,a in rows])
        version_id="v"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        version_dir=settings.versions_dir/version_id; version_dir.mkdir(parents=True,exist_ok=False); save_index(index,version_dir/"knowledge_base.json")
        manifest={"version_id":version_id,"created_at":datetime.now(timezone.utc).isoformat(),"documents":[asdict(r) for r in records if r.status in {"accepted","unchanged"}],"changed_documents":[asdict(r) for r in records if r.changed and r.status=="accepted"],"faq_count":len(rows),"retrieval_format":index["format"]}
        (version_dir/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
        save_version(version_id,"candidate",manifest,parent_version=get_active_version()); return version_id,manifest
    def load_version(self,version_id):
        from .retrieval import load_index
        return load_index(settings.versions_dir/version_id/"knowledge_base.json")
    def activate_version(self,version_id): (settings.runtime_dir/"active_version.txt").write_text(version_id,encoding="utf-8")
    def active_version(self):
        p=settings.runtime_dir/"active_version.txt"; return p.read_text(encoding="utf-8").strip() if p.exists() and p.read_text(encoding="utf-8").strip() else get_active_version()
    def load_active_index(self):
        version=self.active_version()
        if not version: raise FileNotFoundError("No active knowledge base. Run the update pipeline first.")
        return self.load_version(version)
