-- Achievements tables (additive). The app creates them automatically on startup; run manually if preferred.

CREATE TABLE IF NOT EXISTS user_achievements (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	achievement_id VARCHAR(40) NOT NULL, 
	earned_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	game_id INTEGER, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_user_achievement UNIQUE (user_id, achievement_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_achievement_state (
	user_id INTEGER NOT NULL, 
	current_correct_streak INTEGER NOT NULL, 
	best_correct_streak INTEGER NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
