-- Fix for Files Table User ID Type Mismatch
-- The current application uses string-based IDs (telegram_id) for users, 
-- but the files table expects UUIDs. This fix changes the column type to TEXT.

-- 1. Drop foreign key constraint if it exists (may vary based on constraint name)
-- Try to drop common constraint names, ignore error if not exists or handle manually.
ALTER TABLE files DROP CONSTRAINT IF EXISTS files_user_id_fkey;

-- 2. Change column type to TEXT to support "telegram_id" strings
ALTER TABLE files ALTER COLUMN user_id TYPE text;

-- 3. (Optional) Re-add FK if users table uses telegram_id as PK
-- ALTER TABLE files ADD CONSTRAINT files_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(telegram_id);
