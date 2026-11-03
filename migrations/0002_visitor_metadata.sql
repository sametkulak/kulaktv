ALTER TABLE visitor_sessions ADD COLUMN device_type TEXT;
ALTER TABLE visitor_sessions ADD COLUMN browser TEXT;
ALTER TABLE visitor_sessions ADD COLUMN os TEXT;
ALTER TABLE visitor_sessions ADD COLUMN screen_resolution TEXT;
ALTER TABLE visitor_sessions ADD COLUMN language TEXT;
ALTER TABLE visitor_sessions ADD COLUMN platform TEXT;
ALTER TABLE visitor_sessions ADD COLUMN standalone INTEGER NOT NULL DEFAULT 0;
ALTER TABLE visitor_sessions ADD COLUMN country TEXT;
ALTER TABLE visitor_sessions ADD COLUMN city TEXT;
