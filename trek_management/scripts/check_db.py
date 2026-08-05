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

# 6. Check row counts
print(f"\n[5] Row counts")
for t in tables:
    table_name = t[0]
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    count = cursor.fetchone()[0]
    print(f"    {table_name}: {count} rows")

# 7. Sample data preview
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
cursor.execute("SELECT id, user_id, trek_id, booking_status, participants, total_amount FROM bookings")
for row in cursor.fetchall():
    print(f"      id={row[0]}, user={row[1]}, trek={row[2]}, status={row[3]}, participants={row[4]}, amount={row[5]}")

print(f"\n    --- staff_profiles ---")
cursor.execute("SELECT id, user_id, experience_years, specialization FROM staff_profiles")
for row in cursor.fetchall():
    print(f"      id={row[0]}, user={row[1]}, exp={row[2]}yrs, spec={row[3]}")

print(f"\n    --- trek_staff_assignments ---")
cursor.execute("SELECT id, trek_id, staff_id FROM trek_staff_assignments")
for row in cursor.fetchall():
    print(f"      id={row[0]}, trek={row[1]}, staff={row[2]}")

print(f"\n    --- audit_logs ---")
cursor.execute("SELECT id, entity_type, entity_id, action, details FROM audit_logs")
for row in cursor.fetchall():
    print(f"      id={row[0]}, entity={row[1]}#{row[2]}, action={row[3]}, details={row[4]}")

conn.close()
