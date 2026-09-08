def init_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS hotkey_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            hotkey TEXT NOT NULL,
            action_type TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
            ,deleted_at TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_id INTEGER,
            name TEXT NOT NULL,
            action_type TEXT NOT NULL,
            result TEXT NOT NULL,
            executed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(hotkey_actions)")}
    if "deleted_at" not in columns:
        conn.execute("ALTER TABLE hotkey_actions ADD COLUMN deleted_at TEXT NOT NULL DEFAULT ''")
    conn.commit()
