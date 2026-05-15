-- ============================================================
-- MECHANIC SHOP APP — SUPABASE SCHEMA (No Twilio Version)
-- Run this entire file in your Supabase SQL Editor
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── JOBS TABLE ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS jobs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_number          TEXT UNIQUE NOT NULL,

    customer_name       TEXT NOT NULL,
    customer_phone      TEXT NOT NULL,

    vehicle_number      TEXT NOT NULL,
    vehicle_make        TEXT,
    vehicle_model       TEXT,
    vehicle_pic_url     TEXT,

    complaint           TEXT NOT NULL,
    diagnosis           TEXT,
    work_done           TEXT,
    parts_used          TEXT,

    status TEXT NOT NULL DEFAULT 'received'
        CHECK (status IN (
            'received','diagnosing','waiting_parts',
            'in_progress','quality_check','ready','delivered'
        )),

    estimated_cost      NUMERIC(10,2),
    final_cost          NUMERIC(10,2),
    estimated_delivery  DATE,
    actual_delivery     TIMESTAMP WITH TIME ZONE,

    assigned_mechanic   TEXT,
    notes               TEXT,

    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ── JOB UPDATES TIMELINE ────────────────────────────────────
CREATE TABLE IF NOT EXISTS job_updates (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id          UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    status          TEXT NOT NULL,
    message         TEXT NOT NULL,
    updated_by      TEXT DEFAULT 'Admin',
    notification_sent BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ── NOTIFICATION LOG ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS notification_log (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id          UUID REFERENCES jobs(id) ON DELETE SET NULL,
    phone_number    TEXT NOT NULL,
    message_type    TEXT,
    message_body    TEXT,
    status          TEXT DEFAULT 'pending',
    error_message   TEXT,
    sent_at         TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ── AUTO job_number ──────────────────────────────────────────
CREATE OR REPLACE FUNCTION generate_job_number()
RETURNS TRIGGER AS $$
DECLARE seq INTEGER;
BEGIN
    SELECT COUNT(*) + 1 INTO seq FROM jobs
     WHERE EXTRACT(YEAR FROM created_at) = EXTRACT(YEAR FROM NOW());
    NEW.job_number := 'JOB-' || TO_CHAR(NOW(),'YYYY') || '-' || LPAD(seq::TEXT,4,'0');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_job_number ON jobs;
CREATE TRIGGER trg_job_number
    BEFORE INSERT ON jobs
    FOR EACH ROW EXECUTE FUNCTION generate_job_number();

CREATE OR REPLACE FUNCTION touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_updated_at ON jobs;
CREATE TRIGGER trg_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- ── RLS ──────────────────────────────────────────────────────
ALTER TABLE jobs           ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_updates    ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "all_jobs" ON jobs;
DROP POLICY IF EXISTS "all_updates" ON job_updates;
DROP POLICY IF EXISTS "all_notification_log" ON notification_log;

CREATE POLICY "all_jobs"         ON jobs         FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "all_updates"      ON job_updates  FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "all_notification_log" ON notification_log FOR ALL USING (true) WITH CHECK (true);