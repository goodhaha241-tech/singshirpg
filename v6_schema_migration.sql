-- Safe, additive migration for the cumulative v6 build.
ALTER TABLE users ADD COLUMN IF NOT EXISTS total_turns BIGINT NOT NULL DEFAULT 0;
UPDATE users
SET total_turns=GREATEST(COALESCE(total_investigations,0),COALESCE(total_subjugations,0))
WHERE total_turns=0;

CREATE TABLE IF NOT EXISTS user_life_data (
    user_id VARCHAR(50) PRIMARY KEY,
    data JSON NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS gems JSON;
ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS metadata JSON;

INSERT INTO guilds (guild_id,name,owner_id,level,exp,member_count)
VALUES (1,'공용 길드',NULL,1,0,0)
ON DUPLICATE KEY UPDATE name='공용 길드';

-- Existing users are merged by the Python migration so contribution totals can
-- be preserved transactionally. Do not delete old memberships in raw SQL.
