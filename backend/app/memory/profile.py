"""Profilo dell'utente: note stabili scritte dall'utente (chi è, preferenze, convenzioni dell'homelab).

È un unico testo, messo all'inizio della memoria di ogni turno in tutte le modalità: cambia di rado, quindi resta
nella parte del prompt che llama.cpp riusa da un turno all'altro.
"""
from app.memory import thread_store

MAX_CHARS = 4000  # ~1000 token, in ogni prompt


def init_profile_db() -> None:
    conn = thread_store._get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_profile (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                content TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    finally:
        conn.close()


def get_profile() -> dict:
    conn = thread_store._get_conn()
    try:
        row = conn.execute("SELECT content, updated_at FROM user_profile WHERE id = 1").fetchone()
    finally:
        conn.close()
    if not row:
        return {"content": "", "updated_at": None}
    return {"content": row[0], "updated_at": f"{str(row[1]).replace(' ', 'T')}+00:00"}


def save_profile(content: str) -> dict:
    conn = thread_store._get_conn()
    try:
        conn.execute(
            "INSERT INTO user_profile (id, content) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET content = excluded.content, updated_at = CURRENT_TIMESTAMP",
            (content.strip(),),
        )
        conn.commit()
    finally:
        conn.close()
    return get_profile()
