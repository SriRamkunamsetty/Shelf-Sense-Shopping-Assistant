import pytest
from fastapi.testclient import TestClient

from shelfsense.api.main import create_app
from shelfsense.config import Settings
from shelfsense.context import AppContext, build_context


@pytest.fixture
def settings() -> Settings:
    return Settings(
        llm_mode="off", app_env="test", static_dir="/nonexistent", demo_mode=True, ops_api_key=None
    )


@pytest.fixture
def ctx(settings) -> AppContext:
    return build_context(settings, seed=True)


@pytest.fixture
def client(settings, ctx):
    app = create_app(settings, ctx)
    with TestClient(app) as c:
        yield c
