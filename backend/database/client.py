import lancedb
import os
import logging

logger = logging.getLogger(__name__)

if os.environ.get("MNESIS_APPDATA_DIR"):
    DATA_DIR = os.path.join(os.environ["MNESIS_APPDATA_DIR"], "data")
elif os.name == 'nt':
    DATA_DIR = os.path.join(os.environ['APPDATA'], 'Mnesis', 'data')
else:
    DATA_DIR = os.path.join(os.path.expanduser('~'), '.mnesis', 'data')

DB_PATH = os.path.join(DATA_DIR, "lancedb")

_db = None

def get_db():
    global _db
    if _db is None:
        os.makedirs(DB_PATH, exist_ok=True)
        _db = lancedb.connect(DB_PATH)
    return _db

def init_tables():
    db = get_db()
    from .schema import Memory, MemoryVersion, Conversation, Message, Conflict, Session
    
    # Create tables if not exist
    # Note: LanceDB create_table with exist_ok=True and schema
    
    if "memories" not in db.table_names():
        db.create_table("memories", schema=Memory)
    
    if "memory_versions" not in db.table_names():
        db.create_table("memory_versions", schema=MemoryVersion)
        
    if "conversations" not in db.table_names():
        db.create_table("conversations", schema=Conversation)

    if "messages" not in db.table_names():
        db.create_table("messages", schema=Message)

    if "conflicts" not in db.table_names():
        db.create_table("conflicts", schema=Conflict)

    if "sessions" not in db.table_names():
        db.create_table("sessions", schema=Session)

    # Run pending migrations (schema upgrades for existing installs)
    try:
        from backend.migrations import run_migrations
        run_migrations(db)
    except Exception as e:
        logger.warning(f"Migration step failed (non-fatal for new installs): {e}")
