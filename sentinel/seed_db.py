"""Seed past incidents for RAG. Run once before demo. Comprehensive corpus for semantic search."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import psycopg
from app.rag import create_incidents_table, insert_incident

DB_URI = os.getenv("SENTINEL_DB_URI", "postgresql://user:pass@postgres:5432/sentinel_db")

INCIDENTS = [
    # --- HIGH CPU / CPU BURN / LOOP (main demo scenario) ---
    ("High CPU usage, container stuck in loop, POST /break/cpu", "Restart container"),
    ("Prometheus HighCPUUsage alert for victim_service. cAdvisor reports container_cpu_usage_seconds_total rate > 0.85 for 10 seconds.", "Restart victim_service container via docker restart"),
    ("HighCPUUsage alert: victim_service CPU exceeded 85% threshold. Container burning CPU in tight loop.", "Restart container"),
    ("Container CPU spike above 85% for 10+ seconds. Process stuck in CPU-intensive loop, name=victim_service.", "Restart container"),
    ("victim_service high CPU from POST /break/cpu endpoint. cAdvisor reporting container_cpu_usage_seconds_total > 0.85.", "Restart victim_service container"),
    ("Docker container CPU usage sustained above 0.85, name victim_service. Prometheus firing HighCPUUsage.", "Restart container"),
    ("CPU usage alert from cAdvisor for victim_service. rate(container_cpu_usage_seconds_total) > 0.85 for 30s.", "Restart container"),
    ("Severity critical: HighCPUUsage. Labels: name=victim_service. Stats: CPU ~87%, memory stable.", "Restart container"),
    ("Alert HighCPUUsage fired. victim_service container in CPU burn state, logs show math.sqrt loop or similar.", "Restart container"),
    ("Process burning CPU at 85%+ sustained. victim_service container, daemon thread running tight loop.", "Restart container"),
    ("Container stuck in loop consuming CPU. CPU: ~85%, Memory: normal. Alert: HighCPUUsage.", "Restart container"),
    ("High CPU utilization on victim_service. cAdvisor rate > 0.85. Thread doing compute-bound work indefinitely.", "Restart container"),
    ("CPU spike on victim_service. /break/cpu was invoked, now burning CPU in background thread.", "Restart container"),
    ("victim_service CPU > 85%. Prometheus alert HighCPUUsage. Container needs restart to kill runaway thread.", "Restart container"),
    ("Rate of container_cpu_usage_seconds_total for victim_service exceeds 0.85. Infinite loop or CPU burn.", "Restart container"),
    ("Critical: victim_service CPU above threshold. Stats CPU ~85%+. Recommend restart to clear CPU burn.", "Restart container"),
    # --- OOM / MEMORY ---
    ("Error: Out of Memory. Container killed by OOM killer.", "Restart container"),
    ("Container killed: Out of Memory. Memory usage exceeded limit.", "Restart container"),
    ("OOMKilled. victim_service ran out of memory. Kubernetes or Docker OOM killer terminated process.", "Restart container"),
    ("Memory usage spike, container OOM. Stats show memory_stats.usage near limit.", "Restart container"),
    ("Process killed due to memory exhaustion. OOM error in container logs.", "Restart container"),
    ("Container memory limit exceeded. Out of memory error, process terminated.", "Restart container"),
    # --- HANG / FREEZE / ZOMBIE ---
    ("Service frozen. Health check hanging. /break/freeze was called.", "Restart container"),
    ("Container health check timeout. Service is zombie, not responding.", "Restart container"),
    ("victim_service stuck, health check failing. Process in sleep(300) or blocking state.", "Restart container"),
    ("Zombie process: service returns 200 but blocks on health check. state health=False.", "Restart container"),
    ("Service hung. Health endpoint times out. Break/freeze left service in blocking state.", "Restart container"),
    ("Container unresponsive. Health check never returns. Victim service in zombie state.", "Restart container"),
    # --- DB CONNECTION (do NOT restart) ---
    ("Error: DB Connection Refused. postgres unreachable.", "Do NOT restart container. Check Postgres connectivity, credentials, and network."),
    ("Connection refused to PostgreSQL. Database down or unreachable.", "Check Postgres. Verify postgres container is running and credentials are correct."),
    ("psycopg.OperationalError: connection refused. Cannot connect to database.", "Check Postgres service. Do not restart app until DB is reachable."),
    ("Database connection refused. App cannot reach postgres:5432.", "Verify Postgres is up. Check docker network. Do NOT restart app."),
    ("DB Connection Refused. SENTINEL_DB_URI or postgres host unreachable.", "Check Postgres. Ensure postgres container healthy before restarting app."),
    # --- 500 / BAD DEPLOY → ROLLBACK ---
    ("Error: 500 Internal Server Error. Application crash in request handler.", "Rollback recent deploy. Check application logs for stack trace."),
    ("500 Internal Server Error. Unhandled exception in FastAPI endpoint.", "Inspect logs for traceback. Recommend ROLLBACK if recent deploy."),
    ("Recurring 500 errors. Application throwing exceptions. Bad deploy detected.", "ROLLBACK to previous image. Do not blindly restart."),
    ("HighErrorRate alert. app_failures_total increasing. Bad deploy or broken release.", "ROLLBACK container to previous image."),
    ("Bad deploy mode. victim_service reporting application failures. /break/bad_deploy was triggered.", "ROLLBACK to previous image."),
    ("app_failures_total counter increasing. Service returning 500s after deploy.", "ROLLBACK container to last known good image."),
    # --- NETWORK FLOOD → NETWORK_DISCONNECT ---
    ("HighNetworkTx alert. victim_service transmitting at high rate. Network flood or noisy neighbour.", "NETWORK_DISCONNECT to contain. Isolate container from network first."),
    ("Container network transmit bytes rate very high. Possible network abuse or bug.", "NETWORK_DISCONNECT to stop blast radius. Then investigate."),
    ("HighNetworkTx fired. victim_service flooding network. Contain before fixing.", "NETWORK_DISCONNECT. Isolate container from network."),
    # --- MEMORY PRESSURE → UPDATE_RESOURCES ---
    ("HighMemoryUsage alert. victim_service memory above threshold. OOM risk.", "UPDATE_RESOURCES: memory=256 or restart to clear leak."),
    ("Container memory usage high. Near limit. Stats show memory_stats.usage growing.", "UPDATE_RESOURCES: memory=256 to raise limit, or RESTART if leak."),
    ("Memory pressure on victim_service. container_memory_usage_bytes > 40MB. OOM possible.", "UPDATE_RESOURCES: memory=256. Increase container memory limit."),
    # --- NETWORK / TIMEOUT ---
    ("Connection timeout. Service cannot reach external API.", "Check network, firewall, DNS. Restart only if service is stuck."),
    ("Read timeout on database connection. Slow queries or DB overload.", "Check Postgres performance. Consider connection pool tuning."),
    ("Network unreachable. Container cannot resolve or connect to dependent service.", "Verify network config. Check if dependent service is up."),
    # --- DISK / IO ---
    ("Disk full. Container cannot write. No space left on device.", "Clear disk space. Restart may not help until disk is freed."),
    ("IO error: too many open files. File descriptor limit exceeded.", "Restart container to release handles. Consider ulimit increase."),
    ("Read-only file system. Container cannot write to expected path.", "Check volume mounts. Fix permissions or mount config."),
    # --- REDIS / QUEUE ---
    ("Redis connection failed. Celery cannot connect to broker.", "Check Redis container. Ensure redis is running before worker."),
    ("Celery broker connection refused. Redis unreachable.", "Verify Redis is up. Worker depends on redis for task queue."),
    # --- RESTART FAILURES ---
    ("Docker restart failed. Container in bad state.", "Try docker stop then docker start. Or docker compose down/up."),
    ("Container restart loop. Keeps crashing on startup.", "Check startup logs. Fix root cause before restart helps."),
]


def main():
    with psycopg.connect(DB_URI) as conn:
        create_incidents_table(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM incidents")
            count = cur.fetchone()[0]
        if count > 0:
            print(f"Incidents table already has {count} rows. Skipping seed.")
            return
        for error, fix in INCIDENTS:
            insert_incident(conn, error, fix)
    print(f"Seeded {len(INCIDENTS)} past incidents.")


if __name__ == "__main__":
    main()
