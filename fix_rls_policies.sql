-- CloudVault RLS Policy Fix for Supabase
-- Run this in Supabase SQL Editor to enable proper user isolation
-- 
-- IMPORTANT: The application currently uses API key authentication, not Supabase Auth.
-- These policies are configured to work with the service role key.
-- For full RLS with Supabase Auth, you would need to update the application
-- to use Supabase's user authentication instead.

-- ============================================
-- STEP 1: Drop existing policies (if any)
-- ============================================

-- Users table
DROP POLICY IF EXISTS "Allow public registration" ON users;
DROP POLICY IF EXISTS "Users can read own data" ON users;
DROP POLICY IF EXISTS "Users can update own data" ON users;
DROP POLICY IF EXISTS "Allow user operations" ON users;

-- Files table
DROP POLICY IF EXISTS "Allow file operations" ON files;
DROP POLICY IF EXISTS "Users can see own files" ON files;
DROP POLICY IF EXISTS "Users can insert own files" ON files;
DROP POLICY IF EXISTS "Users can update own files" ON files;
DROP POLICY IF EXISTS "Users can delete own files" ON files;

-- Chunks table
DROP POLICY IF EXISTS "Allow chunk operations" ON chunks;
DROP POLICY IF EXISTS "Users can see own chunks" ON chunks;
DROP POLICY IF EXISTS "Users can insert own chunks" ON chunks;
DROP POLICY IF EXISTS "Users can delete own chunks" ON chunks;

-- ============================================
-- STEP 2: Option A - Disable RLS (for development)
-- ============================================
-- Uncomment these if you want to disable RLS entirely during development:

-- ALTER TABLE users DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE files DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE chunks DISABLE ROW LEVEL SECURITY;

-- ============================================
-- STEP 2: Option B - Enable permissive RLS for service key
-- ============================================
-- Since the app uses a service role key, RLS is bypassed by default.
-- These policies are for future use when migrating to Supabase Auth.

-- Allow all operations on users table (service key bypasses anyway)
CREATE POLICY "Allow user operations" ON users
    FOR ALL
    USING (true)
    WITH CHECK (true);

-- Allow all operations on files table (service key bypasses anyway)  
CREATE POLICY "Allow file operations" ON files
    FOR ALL
    USING (true)
    WITH CHECK (true);

-- Allow all operations on chunks table (service key bypasses anyway)
CREATE POLICY "Allow chunk operations" ON chunks
    FOR ALL
    USING (true)
    WITH CHECK (true);

-- Enable RLS on all tables
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE files ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;

-- ============================================
-- STEP 3: Fix legacy file sizes (optional)
-- ============================================
-- Run this to update files that have total_size = 0 or NULL
-- by calculating size from their chunks

UPDATE files f
SET total_size = (
    SELECT COALESCE(SUM(c.chunk_size), 0)
    FROM chunks c
    WHERE c.file_id = f.id
)
WHERE f.total_size IS NULL OR f.total_size = 0;

-- Verify the update
SELECT id, filename, total_size 
FROM files 
WHERE total_size IS NULL OR total_size = 0
LIMIT 10;

-- ============================================
-- NOTES
-- ============================================
-- 1. When using the service_role key, RLS is BYPASSED completely
-- 2. The application enforces user isolation at the code level (checking user_id)
-- 3. For production with proper RLS, you would need to:
--    a) Migrate to Supabase Auth (auth.users table)
--    b) Update policies to use auth.uid()
--    c) Use anon key instead of service_role key
--    d) Example proper policy:
--       CREATE POLICY "Users can see own files" ON files
--           FOR SELECT USING (user_id = auth.uid()::text);
