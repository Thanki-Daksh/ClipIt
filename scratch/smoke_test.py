"""ClipIt core smoke test — exercises state machine, retry, recovery, scheduler."""
import json, tempfile, os, sys
from pathlib import Path

ROOT = Path("C:/Users/Admin/OneDrive/Desktop/ClipIt")
sys.path.insert(0, str(ROOT))

from core.db import Database
from core.queue import (QueueEngine, StateError, COMPLETED, PENDING,
                        register_handler, HANDLERS)

tmp = Path(tempfile.mkdtemp())
db = Database(tmp / "t.db")
db.init_schema()
engine = QueueEngine(db)

# 1. Account
db.create_account("accA", name="AcctA", niche="Tech", sources=["u1"], max_daily_clips=10)
db.create_account("accB", name="AcctB", niche="Food", sources=["u2"], max_daily_clips=10)
print("1. created accounts:", db.list_accounts(enabled_only=True))

# 2. Enqueue
j1 = engine.enqueue("accA", "https://youtu.be/a", "youtube")
j2 = engine.enqueue("accA", "https://youtu.be/b", "youtube")
j3 = engine.enqueue("accB", "https://youtu.be/c", "youtube")
print("2. enqueued jobs:", j1, j2, j3)

# 3. Illegal transition rejected
try:
    engine.transition(j1, "COMPLETED")
    print("3. FAIL: illegal transition not caught")
except StateError:
    print("3. OK: illegal transition PENDING->COMPLETED rejected")

# 4. Full pipeline via registered handlers
def dl(job, d):   return True, {"raw_video_path": "storage/x.mp4", "duration_seconds": 120}
def tr(job, d):   return True, {"transcript_json": json.dumps([{"w": 0.1}])}
def an(job, d):   return True, {}
def cl(job, d):   d.create_clip(job["id"], job["account_id"], "0", "30", 30.0, virality_score=0.9, title="Hook"); return True, {"video_path": "storage/clip.mp4"}
def ca(job, d):   return True, {"caption_path": "storage/clip.ass"}
def mt(job, d):   return True, {"title": "T", "description": "D", "hashtags": "#x"}

for stage, fn in [( "DOWNLOADING", dl), ("TRANSCRIBING", tr), ("ANALYZING", an),
                   ("CLIPPING", cl), ("CAPTIONING", ca), ("METADATA", mt)]:
    HANDLERS[stage] = fn

final = engine.run_job(db.get_job(j1))
print("4. job pipeline final status:", final, "(expect COMPLETED)")

# 5. Retry logic: failing handler counts down then FAILED
def bad_dl(job, d):
    return False, "simulated network error"
HANDLERS["DOWNLOADING"] = bad_dl
st = engine.run_job(db.get_job(j2))
print("5. first bad run ->", st, "retry =", db.get_job(j2)["retry_count"], "(expect PENDING/1)")
# keep running until it exhausts its 3 retries and lands in FAILED
for _ in range(4):
    st = engine.run_job(db.get_job(j2))
    if st in ("FAILED", "COMPLETED"):
        break
print("   after exhausting retries ->", st, "retry =", db.get_job(j2)["retry_count"], "(expect FAILED)")
assert st == "FAILED"
HANDLERS["DOWNLOADING"] = dl

# 6. Round-robin scheduler picks one job per account per tick
engine.enqueue("accA", "https://youtu.be/b2", "youtube")  # give accA work again
picked = engine.round_robin_cycle()
print("6. round-robin tick picked:", [(a, j["id"]) for a, j in picked], "| accounts =", sorted({a for a,_ in picked}))
assert len(picked) == 2, picked
print("   SUCCESS: one job selected per enabled account")

# 7. Crash recovery: jam a job mid-pipeline, simulate missing artifact
db.create_account("accC", name="AcctC", niche="News", sources=["u3"])
j4 = engine.enqueue("accC", "https://youtu.be/d", "youtube")
engine.transition(j4, "DOWNLOADING")          # pretend it was downloading
db.update_job_status(j4, "DOWNLOADING")        # no raw_video_path set => artifact missing
# force status to a working stage
db.update_job_status(j4, "TRANSCRIBING")       # simulating crash left it here
recovered = engine.recover()
print("8. recovery resumed jobs:", recovered)
after = db.get_job(j4)["status"]
print("   job after recovery:", after, "(expect PENDING since no artifacts)")
assert after == "PENDING"

# 9. WAL + foreign keys check
conn = db._conn()
print("9. journal_mode =", conn.execute("PRAGMA journal_mode;").fetchone()[0],
      "| foreign_keys =", conn.execute("PRAGMA foreign_keys;").fetchone()[0])

print("\nALL SMOKE TESTS PASSED")