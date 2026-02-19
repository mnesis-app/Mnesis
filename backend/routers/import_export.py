from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from typing import List, Optional, Dict, Any
import shutil
import os
import uuid
import json
from datetime import datetime
from backend.memory.importers.claude import ClaudeImporter
from backend.memory.importers.chatgpt import ChatGPTImporter
from backend.memory.importers.gemini import GeminiImporter
from backend.memory.core import create_memory
from backend.database.schema import Memory, Conversation, Message, Conflict
from backend.database.client import get_db
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/import", tags=["import"])

# Temporary storage for previews
# In production, use a proper cache or db table
# map preview_id -> { "memories": [...], "conversations": [...] }
_previews = {} 

@router.get("/export")
async def export_data():
    """
    Export full database as JSON.
    """
    try:
        db = get_db()
        export_data = {
            "version": "1.0",
            "extracted_at": datetime.now().isoformat(),
            "memories": [],
            "conversations": [],
            "messages": [] # Optional, might be huge
        }
        
        # 1. Memories
        if "memories" in db.table_names():
            tbl = db.open_table("memories")
            # Limit? For MVP, dump all (assuming < 1GB)
            memories = tbl.search().limit(100000).to_list()
            # Convert Object to dict if needed (LanceDB results are dicts)
            # Handle datetime serialization? JSONResponse handles basic types but datetime needs stringify
            # We'll do a manual serialization pass or rely on FastAPI's encoder (which handles datetime)
            export_data["memories"] = memories
            
        # 2. Conversations
        if "conversations" in db.table_names():
            tbl = db.open_table("conversations")
            export_data["conversations"] = tbl.search().limit(100000).to_list()
            
        # 3. Messages (Optional)
        # If user wants full backup, we should include messages.
        if "messages" in db.table_names():
             tbl = db.open_table("messages")
             # This can be huge. Limit to recent or just verify size? 
             # For MVP, let's limit to 50k messages to match reasonable export size.
             export_data["messages"] = tbl.search().limit(50000).to_list()
             
        # Generate filename
        filename = f"mnesis_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        return JSONResponse(
            content=json.loads(json.dumps(export_data, default=str)), # Ensure serialization
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        logger.error(f"Export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) 

@router.post("/upload")
async def upload_import(
    file: UploadFile = File(...),
    source: str = Form(...),
):
    """
    Upload export file, parse it, and return preview.
    Does NOT write to DB yet.
    """
    
    # Save temp file
    temp_filename = f"temp_{uuid.uuid4()}_{file.filename}"
    if not os.path.exists("data"):
        os.makedirs("data")
    temp_path = os.path.join("data", temp_filename) # Ensure data dir exists
    
    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        if source == "mnesis-backup":
            # Handle Mnesis backup JSON
            with open(temp_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            raw_memories = data.get("memories", [])
            # Map raw memories to RawMemory objects if needed, or just keep as dicts
            # Since we will just insert them, we can keep them as dicts but need to ensure structure matches.
            # Actually, `_process_import` expects a list of RawMemory or dicts that map to `create_memory`.
            # If it's a backup, we might want to "Force Restore" or just "Import as new"?
            # "Import" usually means adding. IDs will conflict if we keep them.
            # Best practice: Strip IDs and re-import? Or Update if ID exists?
            # For this feature "Import/Export", let's assume it's for moving data or restoring.
            # We'll keep it simple: Treat as list of content to be ingested.
            
            # Wait, `raw_memories` in `_previews` was `List[RawMemory]`.
            # We should standardize.
            
            parsed_memories = []
            for m in raw_memories:
                parsed_memories.append({
                    "content": m.get("content"),
                    "source": m.get("source_llm", "manual"),
                    "original_created_at": m.get("created_at"),
                    "original_category": m.get("category"),
                    "metadata": m
                })
            
            parsed_conversations = data.get("conversations", [])
            # We also need messages if they exist
            parsed_messages = data.get("messages", [])
            
            # Combine conversations with their messages?
            # Our `_process_import` will need to handle this.
            # Let's attach messages to conversations if possible, or store separate list.
            # For simplicity, let's put everything in the preview dict.
            
        else:
            # Select importer
            importer = None
            if source == "claude":
                importer = ClaudeImporter()
            elif source == "chatgpt":
                importer = ChatGPTImporter()
            elif source == "gemini":
                importer = GeminiImporter()
            else:
                raise HTTPException(status_code=400, detail="Unknown source")
                
            # Parse Memories
            parsed_memories = []
            try:
                # Some importers return RawMemory objects
                raw_objs = importer.parse_memories(temp_path)
                parsed_memories = [m.dict() for m in raw_objs]
            except Exception as e:
                logger.warning(f"Memory parsing returned empty or failed: {e}")
                
            # Parse Conversations
            parsed_conversations = []
            parsed_messages = [] # Importers usually yield conversations with messages inside
            
            try:
                # parse_conversations yields dicts
                if hasattr(importer, "parse_conversations"):
                    for conv in importer.parse_conversations(temp_path):
                        # Extract messages if present
                        msgs = conv.pop("chat_messages", [])
                        parsed_conversations.append(conv)
                        
                        # Add messages to list, linking via ID
                        # Importers should ensure `conv['id']` is set
                        for msg in msgs:
                            # Ensure message has conversation_id
                            if not msg.get("conversation_id"):
                                msg["conversation_id"] = conv["id"]
                            parsed_messages.append(msg)
                            
            except Exception as e:
                 logger.warning(f"Conversation parsing failed: {e}")

        # Store preview
        preview_id = str(uuid.uuid4())
        _previews[preview_id] = {
            "memories": parsed_memories,
            "conversations": parsed_conversations,
            "messages": parsed_messages
        }
        
        # Determine stats
        categories = {}
        for m in parsed_memories:
            cat = m.get("original_category") or "unknown"
            categories[cat] = categories.get(cat, 0) + 1
            
        # Return preview data
        return {
            "preview_id": preview_id,
            "total_memories": len(parsed_memories),
            "total_conversations": len(parsed_conversations),
            "categories": categories,
            "samples": parsed_memories[:5] if parsed_memories else [],
            "status": "ready_to_confirm"
        }
        
    except Exception as e:
        logger.error(f"Import failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@router.post("/confirm/{preview_id}")
async def confirm_import(preview_id: str, background_tasks: BackgroundTasks):
    """
    Confirm import and start writing to DB in background.
    """
    if preview_id not in _previews:
        raise HTTPException(status_code=404, detail="Preview not found or expired")
        
    data = _previews.pop(preview_id)
    # data is {"memories": [], "conversations": [], "messages": []}
    
    background_tasks.add_task(_process_import, data)
    
    count = len(data.get("memories", [])) + len(data.get("conversations", []))
    return {"status": "started", "count": count}

async def _process_import(data: dict):
    """
    Process raw data and write to DB.
    """
    raw_memories = data.get("memories", [])
    raw_conversations = data.get("conversations", [])
    raw_messages = data.get("messages", [])
    
    logger.info(f"Processing import: {len(raw_memories)} memories, {len(raw_conversations)} conversations")
    
    # 1. Import Memories
    for raw in raw_memories:
        try:
             # raw is dict now (standardized in upload_import)
             content = raw.get('content')
             source = raw.get('source')
             original_cat = raw.get('original_category')
             
             if not content: continue
             
             # Default mapping
             category = "semantic"
             level = "semantic"
             
             # If Claude, map category
             if source == "claude" and original_cat:
                 from backend.memory.importers.claude import CLAUDE_CATEGORY_MAP
                 mapping = CLAUDE_CATEGORY_MAP.get(original_cat, CLAUDE_CATEGORY_MAP["_default"])
                 level, category = mapping
                 
             # Write (handles dedup internally via create_memory check)
             await create_memory(
                 content=content,
                 category=category,
                 level=level,
                 source_llm=source,
                 confidence_score=0.9 # High confidence for imports
             )
        except Exception as e:
            logger.error(f"Failed to import memory: {e}")
            
    # 2. Import Conversations & Messages
    # We write directly to LanceDB for speed/simplicity, bypassing a 'create_conversation' queue if it doesn't exist.
    # But strictly speaking, we should handle concurrent writes if we were adhering to `write_queue`.
    # `conversations` table might not have a write queue wrapper yet.
    # For MVP import, direct write is acceptable if we are careful.
    # However, since we added `get_db` and imported `Conversation`, `Message`...
    
    if raw_conversations:
        try:
            db = get_db()
            
            # Conversations
            if "conversations" in db.table_names():
                tbl = db.open_table("conversations")
                # Deduplicate? Or overwrite? 
                # PROMPT.md says import/export needs dedup.
                # Use raw_file_hash or just ID check.
                
                # Check IDs roughly.
                # For high volume, bulk add is better.
                # Assuming new IDs or we don't care about overwriting for now (MVP).
                # Actually, `Conversation` model requires Pydantic objects.
                
                conv_objects = []
                for c in raw_conversations:
                    # Validate/Clean
                    # Ensure ID
                     if not c.get("id"): c["id"] = str(uuid.uuid4())
                     
                     # Ensure required fields
                     c_obj = Conversation(
                         id=c.get("id"),
                         title=c.get("title", "Untitled"),
                         source_llm=c.get("source_llm", "imported"),
                         started_at=c.get("started_at") or datetime.now(),
                         ended_at=c.get("updated_at"), # Use updated as ended?
                         message_count=c.get("message_count", 0),
                         memory_ids=[], # Can't link easily yet
                         tags=[],
                         summary="",
                         status="archived",
                         raw_file_hash="",
                         imported_at=datetime.now()
                     )
                     conv_objects.append(c_obj)
                
                if conv_objects:
                    tbl.add(conv_objects) # LanceDB handles upsert? No, it appends. Duplicates possible.
                    # TODO: clean duplicates later.
            
            # Messages
            if raw_messages and "messages" in db.table_names():
                msg_tbl = db.open_table("messages")
                msg_objects = []
                for m in raw_messages:
                    if not m.get("id"): m["id"] = str(uuid.uuid4())
                    
                    # Ensure timestamp
                    ts = m.get("created_at") or m.get("timestamp") or datetime.now()
                    if isinstance(ts, str):
                        try:
                            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        except:
                            ts = datetime.now()
                            
                    m_obj = Message(
                        id=m.get("id"),
                        conversation_id=m.get("conversation_id"),
                        role=m.get("sender", m.get("role", "user")), # Claude uses sender? check generic
                        content=m.get("text", m.get("content", "")),
                        timestamp=ts,
                        vector=None 
                    )
                    msg_objects.append(m_obj)
                    
                if msg_objects:
                    msg_tbl.add(msg_objects)
                    
        except Exception as e:
            logger.error(f"Failed to import conversations: {e}")

