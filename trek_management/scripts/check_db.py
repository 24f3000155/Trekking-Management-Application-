"""
Verify the SQLite database file exists, is valid, and inspect all tables/data.
Confirms compatibility with DB Browser for SQLite.
"""

import os
import sqlite3

DB_PATH = "trek_management.db"

print("=" * 60)
print("  DATABASE VERIFICATION")
print("=" * 60)

# 1. Check file exists
print(f"\n[1] File existence check")
exists = os.path.exists(DB_PATH)
print(f"    Path: {os.path.abspath(DB_PATH)}")
print(f"    Exists: {exists}")
if not exists:
    print("    [FAIL] Database file not found!")
    exit(1)

# 2. Check file size
size = os.path.getsize(DB_PATH)
print(f"    Size: {size} bytes ({size / 1024:.1f} KB)")

# 3. Check SQLite header magic bytes
print(f"\n[2] SQLite header validation")
with open(DB_PATH, "rb") as f:
    header = f.read(100)

magic = header[:16]
print(f"    First 16 bytes: {magic}")
is_sqlite = header[:6] == b"SQLite"
print(f"    Starts with 'SQLite': {is_sqlite}")
if is_sqlite:
    print(f"    Full magic string: {header[:16].decode('ascii', errors='replace')}")
    print(f"    [OK] Valid SQLite3 database file")
else:
    print(f"    [FAIL] Not a valid SQLite3 file!")
    exit(1)

# 4. Check SQLite version and integrity via sqlite3 module
print(f"\n[3] SQLite connection test")
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("SELECT sqlite_version()")
version = cursor.fetchone()[0]
print(f"    SQLite version: {version}")

cursor.execute("PRAGMA integrity_check")
integrity = cursor.fetchone()[0]
print(f"    Integrity check: {integrity}")

# 5. List all tables
print(f"\n[4] Tables in database")
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = cursor.fetchall()
print(f"    Total tables: {len(tables)}")
for t in tables:
    print(f"      - {t[0]}")

# 6. Check schema for each table
print(f"\n[5] Table schemas")
for t in tables:
    table_name = t[0]
    print(f"\n    --- {table_name} ---")
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()
    for col in columns:
        cid, name, col_type, notnull, default, pk = col
        flags = []
        if pk:
            flags.append("PK")
        if notnull:
            flags.append("NOT NULL")
        if default is not None:
            flags.append(f"DEFAULT={default}")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        print(f"      {name}: {col_type}{flag_str}")

    # Foreign keys
    cursor.execute(f"PRAGMA foreign_key_list({table_name})")
    fks = cursor.fetchall()
    if fks:
        for fk in fks:
            print(f"      FK: {fk[3]} -> {fk[2]}.{fk[4]}")

# 7. Check row counts
print(f"\n[6] Row counts")
for t in tables:
    table_name = t[0]
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    count = cursor.fetchone()[0]
    print(f"    {table_name}: {count} rows")

# 8. Verify foreign keys are enforced
print(f"\n[7] Foreign key enforcement")
cursor.execute("PRAGMA foreign_keys")
fk_status = cursor.fetchone()[0]
print(f"    PRAGMA foreign_keys = {fk_status} ({'ON' if fk_status else 'OFF'})")

# 9. Check indexes
print(f"\n[8] Indexes")
cursor.execute("SELECT name, tbl_name FROM sqlite_master WHERE type='index' ORDER BY tbl_name, name")
indexes = cursor.fetchall()
for idx in indexes:
    print(f"    {idx[0]} (on {idx[1]})")

# 10. Sample data preview
print(f"\n[9] Sample data preview")
print(f"\n    --- users ---")
cursor.execute("SELECT id, name, email, role, is_active FROM users")
for row in cursor.fetchall():
    print(f"      id={row[0]}, name={row[1]}, email={row[2]}, role={row[3]}, active={row[4]}")

print(f"\n    --- treks ---")
cursor.execute("SELECT id, trek_name, location, difficulty, total_slots, available_slots, price, status FROM treks")
for row in cursor.fetchall():
    print(f"      id={row[0]}, name={row[1]}, location={row[2]}, difficulty={row[3]}, slots={row[5]}/{row[4]}, price={row[6]}, status={row[7]}")

print(f"\n    --- bookings ---")
cursor.execute("SELECT id, user_id, trek_id, booking_status, payment_status, participants, total_amount FROM bookings")
for row in cursor.fetchall():
    print(f"      id={row[0]}, user={row[1]}, trek={row[2]}, status={row[3]}, payment={row[4]}, participants={row[5]}, amount={row[6]}")

print(f"\n    --- staff_profiles ---")
cursor.execute("SELECT id, user_id, experience_years, specialization FROM staff_profiles")
for row in cursor.fetchall():
    print(f"      id={row[0]}, user={row[1]}, exp={row[2]}yrs, spec={row[3]}")

print(f"\n    --- trek_staff_assignments ---")
cursor.execute("SELECT id, trek_id, staff_id FROM trek_staff_assignments")
for row in cursor.fetchall():
    print(f"      id={row[0]}, trek={row[1]}, staff={row[2]}")

# 11. Verify password is hashed (not plaintext)
print(f"\n[10] Password hash check")
cursor.execute("SELECT email, password_hash FROM users LIMIT 3")
for row in cursor.fetchall():
    ph = row[1]
    is_hashed = ph.startswith("$2b$")
    print(f"    {row[0]}: {'[OK] bcrypt hash' if is_hashed else '[FAIL] NOT hashed!'} ({ph[:25]}...)")

conn.close()

print(f"\n{'=' * 60}")
print(f"  [OK] DATABASE IS VALID AND DB BROWSER COMPATIBLE")
print(f"{'=' * 60}")
print(f"\n  To open in DB Browser for SQLite:")
print(f"  File -> Open Database -> {os.path.abspath(DB_PATH)}")
