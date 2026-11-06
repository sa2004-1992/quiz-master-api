-- Quiz modes for questions (PostgreSQL / Supabase). The app applies this automatically at startup; run it by hand
-- in the Supabase SQL editor if you prefer. It is additive: no rows, ids, games, progress or daily assignments change.
--
-- questions.pool is the quiz-mode identifier: 'category' (Quiz 1), 'all' (Quiz 2), 'daily' (Quiz 3).
-- 1) allow the new 'all' mode
ALTER TABLE questions DROP CONSTRAINT IF EXISTS ck_questions_pool;
ALTER TABLE questions ADD CONSTRAINT ck_questions_pool CHECK (pool IN ('category','all','daily'));
-- 2) duplicates are prevented per quiz mode AND category (identical text may exist in another mode or category)
ALTER TABLE questions ADD CONSTRAINT uq_questions_pool_cat_hash UNIQUE (pool, category_id, question_hash);
ALTER TABLE questions DROP CONSTRAINT IF EXISTS uq_questions_pool_hash;
-- Existing indexes (ix_questions_pool_cat_id on pool, category_id, id) already make mode + category lookups efficient.
