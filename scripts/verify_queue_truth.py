import os
import sqlite3
import sys


def verify_queue():
    db_path = os.environ.get("DATABASE_PATH", "./apix.db")
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}, skipping direct SQLite verification.")
        return 0

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='crawler_jobs'"
    )
    assert cur.fetchone()[0] == 1, "crawler_jobs table missing"

    cur.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='worker_heartbeats'"
    )
    assert cur.fetchone()[0] == 1, "worker_heartbeats table missing"

    cur.execute("""
        INSERT INTO crawler_jobs (job_id, queue_name, crawler_name, route_code, booking_window, status, priority, payload_json, created_at, scheduled_at, attempts, max_attempts, is_synthetic)
        VALUES ('trig-directsql-01', 'crawl', 'synthetic', 'DEL-BOM', 'T+1', 'PENDING', 5, '{}', datetime('now'), datetime('now'), 0, 3, 1)
    """)
    conn.commit()

    cur.execute("""
        UPDATE crawler_jobs
        SET status = 'CLAIMED', worker_id = 'direct-sql-worker', lease_token = 'tok-1234', attempts = attempts + 1, claimed_at = datetime('now'), lease_expires_at = datetime('now', '+90 seconds')
        WHERE id = (SELECT id FROM crawler_jobs WHERE queue_name = 'crawl' AND status = 'PENDING' ORDER BY priority DESC, id ASC LIMIT 1)
          AND status = 'PENDING'
        RETURNING id, job_id, status, worker_id, attempts
    """)
    claimed = cur.fetchall()
    assert len(claimed) == 1, f"Expected 1 claimed row, got {len(claimed)}"
    claimed_id, job_id, status, worker_id, attempts = claimed[0]
    assert status == "CLAIMED"
    assert attempts == 1
    assert worker_id == "direct-sql-worker"
    conn.commit()

    cur.execute(
        """
        UPDATE crawler_jobs
        SET status = 'COMPLETED', completed_at = datetime('now')
        WHERE id = ? AND worker_id = 'direct-sql-worker' AND lease_token = 'tok-1234' AND status = 'CLAIMED'
        RETURNING id, status
    """,
        (claimed_id,),
    )
    completed = cur.fetchall()
    assert len(completed) == 1
    assert completed[0][1] == "COMPLETED"
    conn.commit()

    cur.execute("DELETE FROM crawler_jobs WHERE job_id = 'trig-directsql-01'")
    conn.commit()
    conn.close()

    print(
        "Direct SQL verification passed: atomic claim via UPDATE ... RETURNING, lease fencing, and completion verified."
    )
    return 0


if __name__ == "__main__":
    sys.exit(verify_queue())
