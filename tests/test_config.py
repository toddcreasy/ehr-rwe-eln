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
