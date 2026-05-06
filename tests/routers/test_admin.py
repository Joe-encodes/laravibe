import pytest
from fastapi.testclient import TestClient
from api.main import app
from api.database import get_db
from api.services.auth_service import get_current_user

# Setup client
client = TestClient(app)

async def mock_get_current_user():
    return {"user_id": "test_user"}

# We will patch get_db in the individual tests
# because overriding dependencies globally affects everything.
app.dependency_overrides[get_current_user] = mock_get_current_user

class MockDbResult:
    def __init__(self, data):
        self.data = data
    
    def scalars(self):
        class MockScalars:
            def all(_self):
                return self.data
        return MockScalars()
    
    def all(self):
        return self.data

class MockAsyncSession:
    def __init__(self, execute_return_data, is_scalars=False):
        self.execute_return_data = execute_return_data
        self.is_scalars = is_scalars
        
    async def execute(self, stmt):
        if self.is_scalars:
            return MockDbResult(self.execute_return_data)
        else:
            return MockDbResult(self.execute_return_data)

class MockSubmission:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

class MockRow:
    def __init__(self, experiment_id, total_cases, success_count, created_at):
        self.experiment_id = experiment_id
        self.total_cases = total_cases
        self.success_count = success_count
        self.created_at = created_at

def test_get_training_dataset():
    subs = [
        MockSubmission(id="sub1", original_code="A", final_code="B", total_iterations=1, error_summary="err1", category="cat1", created_at="2026-05-01T00:00:00Z"),
        MockSubmission(id="sub2", original_code="C", final_code="D", total_iterations=2, error_summary="err2", category="cat2", created_at="2026-05-02T00:00:00Z"),
    ]
    
    async def get_mock_db():
        yield MockAsyncSession(subs, is_scalars=True)
        
    app.dependency_overrides[get_db] = get_mock_db
    
    response = client.get("/api/admin/training-dataset")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["data"]) == 2
    assert data["data"][0]["id"] == "sub1"

def test_get_evaluations():
    rows = [
        MockRow("exp1", 10, 8, "2026-05-01T00:00:00Z"),
        MockRow("exp2", 5, 5, "2026-05-02T00:00:00Z"),
        MockRow("exp3", 0, 0, "2026-05-03T00:00:00Z"),
    ]
    
    async def get_mock_db():
        yield MockAsyncSession(rows, is_scalars=False)
        
    app.dependency_overrides[get_db] = get_mock_db
    
    response = client.get("/api/admin/evaluations")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    assert data[0]["id"] == "exp1"
    assert data[0]["total_cases"] == 10
    assert data[0]["success_count"] == 8
    assert data[0]["success_rate_pct"] == 80.0
    
    assert data[1]["id"] == "exp2"
    assert data[1]["success_rate_pct"] == 100.0
    
    assert data[2]["id"] == "exp3"
    assert data[2]["success_rate_pct"] == 0.0

def test_unauthenticated():
    # Remove auth override
    app.dependency_overrides.pop(get_current_user, None)
    
    response = client.get("/api/admin/training-dataset")
    # auth_service might raise 401/403 when not overridden
    assert response.status_code in [401, 403]
    
    app.dependency_overrides[get_current_user] = mock_get_current_user
