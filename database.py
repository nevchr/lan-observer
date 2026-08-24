import sqlite3
from datetime import datetime

DB_NAME = "devices.db"


def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def set_last_scan(timestamp):
    conn = get_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.execute("""
        INSERT INTO app_state (key, value)
        VALUES ('last_scan', ?)
        ON CONFLICT(key)
        DO UPDATE SET value = excluded.value
    """, (timestamp,))

    conn.commit()
    conn.close()


def get_last_scan():
    conn = get_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    row = conn.execute("""
        SELECT value
        FROM app_state
        WHERE key = 'last_scan'
    """).fetchone()

    conn.close()

    if row:
        return row["value"]

    return None

def update_device(mac, nickname, known):
    conn = get_connection()

    conn.execute("""
        UPDATE devices
        SET nickname = ?,
            known = ?,
            is_new = CASE
                WHEN ? = 1 THEN 0
                ELSE is_new
            END
        WHERE mac = ?
    """, (
        nickname,
        known,
        known,
        mac
    ))

    conn.commit()
    conn.close()

def init_database():
    conn = get_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mac TEXT UNIQUE,
            ip TEXT,
            hostname TEXT,
            vendor TEXT,
            nickname TEXT,
            known INTEGER DEFAULT 0,
            first_seen TEXT,
            last_seen TEXT,
            online INTEGER DEFAULT 0
        )
    """)

    try:
        conn.execute("""
            ALTER TABLE devices
            ADD COLUMN vendor TEXT
        """)
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute("""
            ALTER TABLE devices
            ADD COLUMN is_new INTEGER DEFAULT 0
        """)
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()


def save_scan(devices):
    conn = get_connection()

    # Assume everything is offline until this scan proves otherwise
    conn.execute("""
        UPDATE devices
        SET online = 0
    """)

    now = datetime.now().isoformat(timespec="seconds")

    for device in devices:
        mac = device["mac"]

        # Skip devices where we couldn't get a MAC
        if mac == "Unknown":
            continue

        existing = conn.execute(
            "SELECT * FROM devices WHERE mac = ?",
            (mac,)
        ).fetchone()

        if existing:
            conn.execute("""
    UPDATE devices
    SET ip = ?,
        hostname = ?,
        vendor = ?,
        last_seen = ?,
        online = 1
    WHERE mac = ?
""", (
    device["ip"],
    device["hostname"],
    device["vendor"],
    now,
    mac
))

        else:
            conn.execute("""
    INSERT INTO devices (
        mac,
        ip,
        hostname,
        vendor,
        first_seen,
        last_seen,
        online,
        is_new
    )
    VALUES (?, ?, ?, ?, ?, ?, 1, 1)
""", (
    mac,
    device["ip"],
    device["hostname"],
    device["vendor"],
    now,
    now
))

    conn.commit()
    conn.close()


def get_devices():
    conn = get_connection()

    rows = conn.execute("""
        SELECT *
        FROM devices
        ORDER BY online DESC, last_seen DESC
    """).fetchall()

    conn.close()

    return [dict(row) for row in rows]


if __name__ == "__main__":
    init_database()
    
    print("Database created successfully.")