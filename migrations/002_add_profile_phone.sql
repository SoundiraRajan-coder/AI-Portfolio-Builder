-- Add the phone field used by the reusable profile module.
ALTER TABLE user_profiles
ADD COLUMN IF NOT EXISTS phone VARCHAR(40);
