-- Quiz Master initial schema (PostgreSQL / Supabase). Safe to run once on an empty database.
-- The app also creates missing tables automatically on startup (never drops anything).

CREATE TABLE IF NOT EXISTS categories (
	id SERIAL NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	slug VARCHAR(80) NOT NULL, 
	position INTEGER NOT NULL, 
	language VARCHAR(5) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name), 
	UNIQUE (slug), 
	UNIQUE (position)
);


CREATE TABLE IF NOT EXISTS daily_question_sets (
	id SERIAL NOT NULL, 
	quiz_date DATE NOT NULL, 
	question_ids JSON NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (quiz_date)
);


CREATE TABLE IF NOT EXISTS users (
	id SERIAL NOT NULL, 
	full_name VARCHAR(100) NOT NULL, 
	email VARCHAR(254) NOT NULL, 
	username VARCHAR(30) NOT NULL, 
	username_lower VARCHAR(30) NOT NULL, 
	gender VARCHAR(10) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_users_gender CHECK (gender IN ('Male','Female','Other')), 
	UNIQUE (email), 
	UNIQUE (username_lower)
);


CREATE TABLE IF NOT EXISTS feedback (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	rating INTEGER, 
	message TEXT NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS play_all_progress (
	user_id INTEGER NOT NULL, 
	pointer INTEGER NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (user_id), 
	CONSTRAINT ck_pap_pointer CHECK (pointer >= 0), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS questions (
	id SERIAL NOT NULL, 
	pool VARCHAR(10) NOT NULL, 
	category_id INTEGER NOT NULL, 
	question_text TEXT NOT NULL, 
	option_a TEXT NOT NULL, 
	option_b TEXT NOT NULL, 
	option_c TEXT NOT NULL, 
	option_d TEXT NOT NULL, 
	correct_answer VARCHAR(1) NOT NULL, 
	explanation TEXT NOT NULL, 
	difficulty VARCHAR(10) NOT NULL, 
	question_hash VARCHAR(64) NOT NULL, 
	source VARCHAR(10) NOT NULL, 
	daily_date DATE, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_questions_pool_hash UNIQUE (pool, question_hash), 
	CONSTRAINT ck_questions_correct CHECK (correct_answer IN ('A','B','C','D')), 
	CONSTRAINT ck_questions_pool CHECK (pool IN ('category','daily')), 
	CONSTRAINT ck_questions_difficulty CHECK (difficulty IN ('easy','medium','hard')), 
	FOREIGN KEY(category_id) REFERENCES categories (id)
);

CREATE INDEX IF NOT EXISTS ix_questions_pool_cat_id ON questions (pool, category_id, id);

CREATE TABLE IF NOT EXISTS quiz_games (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	quiz_type VARCHAR(10) NOT NULL, 
	category_id INTEGER, 
	status VARCHAR(12) NOT NULL, 
	active_key VARCHAR(20), 
	question_ids JSON NOT NULL, 
	seq_positions JSON NOT NULL, 
	start_pointer INTEGER NOT NULL, 
	current_index INTEGER NOT NULL, 
	resolved_count INTEGER NOT NULL, 
	correct_count INTEGER NOT NULL, 
	hints_used INTEGER NOT NULL, 
	hints_max INTEGER NOT NULL, 
	difficulty VARCHAR(10) NOT NULL, 
	score INTEGER NOT NULL, 
	started_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	paused_at TIMESTAMP WITHOUT TIME ZONE, 
	paused_seconds FLOAT NOT NULL, 
	finished_at TIMESTAMP WITHOUT TIME ZONE, 
	elapsed_seconds INTEGER, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_games_user_active UNIQUE (user_id, active_key), 
	CONSTRAINT ck_games_type CHECK (quiz_type IN ('category','all','daily')), 
	CONSTRAINT ck_games_status CHECK (status IN ('in_progress','completed')), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(category_id) REFERENCES categories (id)
);

CREATE INDEX IF NOT EXISTS ix_games_status_finished ON quiz_games (status, finished_at);
CREATE INDEX IF NOT EXISTS ix_games_user_status_finished ON quiz_games (user_id, status, finished_at);

CREATE TABLE IF NOT EXISTS user_category_progress (
	user_id INTEGER NOT NULL, 
	category_id INTEGER NOT NULL, 
	pointer INTEGER NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (user_id, category_id), 
	CONSTRAINT ck_ucp_pointer CHECK (pointer >= 0), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(category_id) REFERENCES categories (id)
);


CREATE TABLE IF NOT EXISTS user_daily_streaks (
	user_id INTEGER NOT NULL, 
	current_streak INTEGER NOT NULL, 
	longest_streak INTEGER NOT NULL, 
	last_completed_date DATE, 
	PRIMARY KEY (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS user_preferences (
	user_id INTEGER NOT NULL, 
	dark_mode BOOLEAN NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS bookmarks (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	question_id INTEGER NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_bookmarks_user_question UNIQUE (user_id, question_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(question_id) REFERENCES questions (id) ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS daily_game_records (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	quiz_date DATE NOT NULL, 
	game_id INTEGER, 
	status VARCHAR(12) NOT NULL, 
	score INTEGER NOT NULL, 
	completed_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_daily_user_date UNIQUE (user_id, quiz_date), 
	CONSTRAINT ck_daily_status CHECK (status IN ('in_progress','completed')), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(game_id) REFERENCES quiz_games (id) ON DELETE SET NULL
);


CREATE TABLE IF NOT EXISTS quiz_game_answers (
	id SERIAL NOT NULL, 
	game_id INTEGER NOT NULL, 
	question_id INTEGER NOT NULL, 
	position INTEGER NOT NULL, 
	selected_option VARCHAR(1), 
	is_correct BOOLEAN NOT NULL, 
	hint_used BOOLEAN NOT NULL, 
	points INTEGER NOT NULL, 
	answered_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_answers_game_question UNIQUE (game_id, question_id), 
	CONSTRAINT uq_answers_game_position UNIQUE (game_id, position), 
	FOREIGN KEY(game_id) REFERENCES quiz_games (id) ON DELETE CASCADE, 
	FOREIGN KEY(question_id) REFERENCES questions (id)
);

CREATE INDEX IF NOT EXISTS ix_answers_question ON quiz_game_answers (question_id);

