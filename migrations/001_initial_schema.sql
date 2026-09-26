-- AI-Powered Portfolio Generator
-- Initial PostgreSQL schema for Supabase.
-- Authentication and application services are intentionally not implemented here.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = timezone('utc', now());
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    google_subject VARCHAR(255) NOT NULL UNIQUE,
    email VARCHAR(320) NOT NULL UNIQUE,
    display_name VARCHAR(150),
    avatar_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now())
);

CREATE TABLE user_profiles (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    headline VARCHAR(180),
    bio TEXT,
    location VARCHAR(150),
    website_url TEXT,
    github_url TEXT,
    linkedin_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now())
);

CREATE TABLE skills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    category VARCHAR(100),
    proficiency SMALLINT CHECK (proficiency IS NULL OR proficiency BETWEEN 1 AND 5),
    display_order INTEGER NOT NULL DEFAULT 0 CHECK (display_order >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    UNIQUE (user_id, id),
    UNIQUE (user_id, name)
);

CREATE TABLE education (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    institution VARCHAR(200) NOT NULL,
    degree VARCHAR(150),
    field_of_study VARCHAR(150),
    start_date DATE,
    end_date DATE,
    is_current BOOLEAN NOT NULL DEFAULT FALSE,
    description TEXT,
    display_order INTEGER NOT NULL DEFAULT 0 CHECK (display_order >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    UNIQUE (user_id, id),
    CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date)
);

CREATE TABLE work_experiences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company_name VARCHAR(200) NOT NULL,
    job_title VARCHAR(180) NOT NULL,
    location VARCHAR(150),
    start_date DATE,
    end_date DATE,
    is_current BOOLEAN NOT NULL DEFAULT FALSE,
    description TEXT,
    display_order INTEGER NOT NULL DEFAULT 0 CHECK (display_order >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    UNIQUE (user_id, id),
    CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date)
);

CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    summary TEXT,
    description TEXT,
    project_url TEXT,
    repository_url TEXT,
    start_date DATE,
    end_date DATE,
    is_current BOOLEAN NOT NULL DEFAULT FALSE,
    display_order INTEGER NOT NULL DEFAULT 0 CHECK (display_order >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    UNIQUE (user_id, id),
    CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date)
);

CREATE TABLE certifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    issuing_organization VARCHAR(200),
    issue_date DATE,
    expiration_date DATE,
    credential_id VARCHAR(200),
    credential_url TEXT,
    display_order INTEGER NOT NULL DEFAULT 0 CHECK (display_order >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    UNIQUE (user_id, id),
    CHECK (expiration_date IS NULL OR issue_date IS NULL OR expiration_date >= issue_date)
);

CREATE TABLE portfolios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(150) NOT NULL,
    slug VARCHAR(180) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'archived')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    UNIQUE (user_id, slug),
    UNIQUE (id, user_id)
);

CREATE TABLE portfolio_metadata (
    portfolio_id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    seo_title VARCHAR(180),
    seo_description VARCHAR(320),
    locale VARCHAR(20) NOT NULL DEFAULT 'en',
    public_contact_email VARCHAR(320),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    FOREIGN KEY (portfolio_id, user_id) REFERENCES portfolios(id, user_id) ON DELETE CASCADE
);

CREATE TABLE portfolio_skills (
    portfolio_id UUID NOT NULL,
    user_id UUID NOT NULL,
    skill_id UUID NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0 CHECK (display_order >= 0),
    PRIMARY KEY (portfolio_id, skill_id),
    FOREIGN KEY (portfolio_id, user_id) REFERENCES portfolios(id, user_id) ON DELETE CASCADE,
    FOREIGN KEY (skill_id, user_id) REFERENCES skills(id, user_id) ON DELETE CASCADE
);

CREATE TABLE portfolio_education (
    portfolio_id UUID NOT NULL,
    user_id UUID NOT NULL,
    education_id UUID NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0 CHECK (display_order >= 0),
    PRIMARY KEY (portfolio_id, education_id),
    FOREIGN KEY (portfolio_id, user_id) REFERENCES portfolios(id, user_id) ON DELETE CASCADE,
    FOREIGN KEY (education_id, user_id) REFERENCES education(id, user_id) ON DELETE CASCADE
);

CREATE TABLE portfolio_experiences (
    portfolio_id UUID NOT NULL,
    user_id UUID NOT NULL,
    experience_id UUID NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0 CHECK (display_order >= 0),
    PRIMARY KEY (portfolio_id, experience_id),
    FOREIGN KEY (portfolio_id, user_id) REFERENCES portfolios(id, user_id) ON DELETE CASCADE,
    FOREIGN KEY (experience_id, user_id) REFERENCES work_experiences(id, user_id) ON DELETE CASCADE
);

CREATE TABLE portfolio_projects (
    portfolio_id UUID NOT NULL,
    user_id UUID NOT NULL,
    project_id UUID NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0 CHECK (display_order >= 0),
    PRIMARY KEY (portfolio_id, project_id),
    FOREIGN KEY (portfolio_id, user_id) REFERENCES portfolios(id, user_id) ON DELETE CASCADE,
    FOREIGN KEY (project_id, user_id) REFERENCES projects(id, user_id) ON DELETE CASCADE
);

CREATE TABLE portfolio_certifications (
    portfolio_id UUID NOT NULL,
    user_id UUID NOT NULL,
    certification_id UUID NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0 CHECK (display_order >= 0),
    PRIMARY KEY (portfolio_id, certification_id),
    FOREIGN KEY (portfolio_id, user_id) REFERENCES portfolios(id, user_id) ON DELETE CASCADE,
    FOREIGN KEY (certification_id, user_id) REFERENCES certifications(id, user_id) ON DELETE CASCADE
);

-- Immutable snapshots make history independent from later profile edits.
CREATE TABLE portfolio_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL,
    user_id UUID NOT NULL,
    version_number INTEGER NOT NULL CHECK (version_number > 0),
    snapshot JSONB NOT NULL,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    UNIQUE (portfolio_id, version_number),
    UNIQUE (id, portfolio_id),
    FOREIGN KEY (portfolio_id, user_id) REFERENCES portfolios(id, user_id) ON DELETE CASCADE
);

CREATE TABLE portfolio_ai_content (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL,
    user_id UUID NOT NULL,
    version_id UUID,
    content_type VARCHAR(80) NOT NULL,
    content JSONB NOT NULL,
    prompt TEXT,
    model_name VARCHAR(120),
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    FOREIGN KEY (portfolio_id, user_id) REFERENCES portfolios(id, user_id) ON DELETE CASCADE,
    FOREIGN KEY (version_id, portfolio_id) REFERENCES portfolio_versions(id, portfolio_id) ON DELETE RESTRICT
);

CREATE TABLE portfolio_design_specs (
    portfolio_id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    generation_prompt TEXT,
    specification JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_custom BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    FOREIGN KEY (portfolio_id, user_id) REFERENCES portfolios(id, user_id) ON DELETE CASCADE
);

CREATE TABLE portfolio_exports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL,
    user_id UUID NOT NULL,
    version_id UUID,
    export_format VARCHAR(20) NOT NULL CHECK (export_format IN ('html', 'pdf', 'zip')),
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    storage_path TEXT,
    error_message TEXT,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    completed_at TIMESTAMPTZ,
    FOREIGN KEY (portfolio_id, user_id) REFERENCES portfolios(id, user_id) ON DELETE CASCADE,
    FOREIGN KEY (version_id, portfolio_id) REFERENCES portfolio_versions(id, portfolio_id) ON DELETE RESTRICT
);

CREATE INDEX idx_portfolios_user_id ON portfolios(user_id);
CREATE INDEX idx_skills_user_id ON skills(user_id);
CREATE INDEX idx_education_user_id ON education(user_id);
CREATE INDEX idx_work_experiences_user_id ON work_experiences(user_id);
CREATE INDEX idx_projects_user_id ON projects(user_id);
CREATE INDEX idx_certifications_user_id ON certifications(user_id);
CREATE INDEX idx_portfolio_versions_portfolio_id ON portfolio_versions(portfolio_id, created_at DESC);
CREATE INDEX idx_portfolio_ai_content_portfolio_id ON portfolio_ai_content(portfolio_id, created_at DESC);
CREATE INDEX idx_portfolio_exports_portfolio_id ON portfolio_exports(portfolio_id, requested_at DESC);

CREATE TRIGGER users_set_updated_at BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER user_profiles_set_updated_at BEFORE UPDATE ON user_profiles
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER skills_set_updated_at BEFORE UPDATE ON skills
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER education_set_updated_at BEFORE UPDATE ON education
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER work_experiences_set_updated_at BEFORE UPDATE ON work_experiences
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER projects_set_updated_at BEFORE UPDATE ON projects
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER certifications_set_updated_at BEFORE UPDATE ON certifications
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER portfolios_set_updated_at BEFORE UPDATE ON portfolios
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER portfolio_metadata_set_updated_at BEFORE UPDATE ON portfolio_metadata
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER portfolio_design_specs_set_updated_at BEFORE UPDATE ON portfolio_design_specs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
