-- Adds per-game answered/wrong counts to quiz_games (additive; nothing is dropped).
-- The app applies this automatically on startup. Run it manually in the Supabase SQL editor if you prefer.
ALTER TABLE quiz_games ADD COLUMN IF NOT EXISTS answered_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE quiz_games ADD COLUMN IF NOT EXISTS wrong_count INTEGER NOT NULL DEFAULT 0;

UPDATE quiz_games SET
  answered_count = (SELECT COUNT(*) FROM quiz_game_answers a
                    WHERE a.game_id = quiz_games.id AND a.selected_option IS NOT NULL),
  wrong_count = (SELECT COUNT(*) FROM quiz_game_answers a
                 WHERE a.game_id = quiz_games.id AND a.selected_option IS NOT NULL AND a.is_correct = false)
WHERE status = 'completed';
