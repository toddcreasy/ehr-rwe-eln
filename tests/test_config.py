from pathlib import Path

from ehr_rwe_eln.agents.config import AgentSettings
from ehr_rwe_eln.config import Settings

EXAMPLE = Path(__file__).parent.parent / ".env.example"


def test_blank_values_copied_from_env_example_fall_back_to_defaults(tmp_path, monkeypatch):
    for name in ("DB_HOST", "DB_PASSWORD", "LOG_LEVEL", "FRONTEND_DIR", "MODEL"):
        monkeypatch.delenv(name, raising=False)
    env = EXAMPLE.read_text().replace("DB_PASSWORD=\n", "DB_PASSWORD=x\n")
    (tmp_path / ".env").write_text(env)
    monkeypatch.chdir(tmp_path)
    settings = Settings()
    assert settings.log_level == "INFO"
    assert settings.frontend_dir == "frontend/out"
    assert AgentSettings().model == "us.anthropic.claude-opus-4-6-v1"


def test_iam_auth_signs_in_with_a_token_over_tls(monkeypatch):
    from ehr_rwe_eln import config

    TOKEN = object()

    calls = {}

    class FakeRds:
        def generate_db_auth_token(self, **kwargs):
            calls["token_for"] = kwargs
            return TOKEN

    monkeypatch.setattr(config.boto3, "client", lambda service, region_name: FakeRds())
    monkeypatch.setattr(
        config.psycopg, "connect", lambda **kwargs: calls.setdefault("connect", kwargs)
    )
    settings = config.DatabaseSettings(
        db_host="aurora.example", db_user="app", db_iam_auth=True, _env_file=None
    )

    settings.connect()

    assert calls["token_for"] == {"DBHostname": "aurora.example", "Port": 5432, "DBUsername": "app"}
    assert calls["connect"]["password"] is TOKEN
    assert calls["connect"]["sslmode"] == "require"
