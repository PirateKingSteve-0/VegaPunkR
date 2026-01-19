# Testing Guide

## Test Database Setup ✓

Your project now has a separate test database configured for fast, isolated testing.

### Architecture

- **Production DB**: `vegapunk_db` on port `5432` (persistent storage)
- **Test DB**: `vegapunk_db_test` on port `5433` (in-memory tmpfs, super fast!)

### Configuration

**Environment Variables** (`.env`):
```env
DATABASE_URL=postgresql://user:pass@localhost:5432/vegapunk
DATABASE_TEST_URL=postgresql://user:pass@localhost:5433/vegapunk_test
```

### Running Tests

```bash
# Start test database
cd docker && docker compose up -d timescaledb_test

# Run all tests
cd api && pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_models.py

# Run specific test
pytest tests/test_models.py::test_admin_user_exists

# Run with coverage report
pytest --cov=. --cov-report=term-missing

# Run with coverage HTML report
pytest --cov=. --cov-report=html
# Open htmlcov/index.html in browser
```

### Test Structure

```
api/
├── conftest.py              # Pytest fixtures and configuration
├── test_database.py         # Test database connection setup
└── tests/
    ├── __init__.py
    └── test_models.py       # Model tests
```

### Available Fixtures

Defined in `conftest.py`:

- **`db_session`**: Fresh database session for each test (auto-rollback)
- **`sample_user`**: Pre-created test user
- **`sample_strategy`**: Pre-created test strategy
- **`sample_position`**: Pre-created test position

### Example Test

```python
def test_my_feature(db_session, sample_user):
    """Test description."""
    # Create a strategy for the user
    strategy = Strategy(
        user_id=sample_user.id,
        name="My Test Strategy",
        params_json={"param": "value"}
    )
    db_session.add(strategy)
    db_session.commit()

    # Assert
    assert strategy.id is not None
    assert strategy.user_id == sample_user.id
```

## Test Database Features

### In-Memory Storage (tmpfs)
- Tests run **blazingly fast** (no disk I/O)
- Data is **automatically wiped** when container stops
- Perfect for CI/CD pipelines

### Automatic Cleanup
- Each test gets a fresh transaction that's rolled back
- Database schema is created at test session start
- Database schema is dropped at test session end

### Isolation
- Test database is completely separate from production
- Can run tests while development database is running
- No risk of polluting real data

## Adding New Tests

1. Create test file in `tests/` directory:
```python
# tests/test_strategies.py
def test_strategy_creation(db_session, sample_user):
    """Test creating a strategy."""
    # Your test code here
    pass
```

2. Use fixtures for common setup:
```python
@pytest.fixture
def my_custom_fixture(db_session):
    """Create custom test data."""
    # Setup
    yield data
    # Teardown (if needed)
```

3. Run tests:
```bash
pytest tests/test_strategies.py -v
```

## Best Practices

### DO:
- ✅ Use fixtures for reusable test data
- ✅ Test one thing per test function
- ✅ Use descriptive test names
- ✅ Clean up resources in fixtures
- ✅ Use `db_session` fixture for database access

### DON'T:
- ❌ Depend on test execution order
- ❌ Use production database for tests
- ❌ Commit to test database (use fixtures instead)
- ❌ Mock everything (integration tests are valuable)

## CI/CD Integration

For GitHub Actions or similar:

```yaml
- name: Start test database
  run: docker compose -f docker/docker-compose.yml up -d timescaledb_test

- name: Wait for database
  run: sleep 5

- name: Run tests
  run: |
    cd api
    pytest --cov=. --cov-report=xml

- name: Upload coverage
  uses: codecov/codecov-action@v3
```

## Troubleshooting

### Test database not starting
```bash
docker logs vegapunk_db_test
docker compose -f docker/docker-compose.yml restart timescaledb_test
```

### Connection refused errors
```bash
# Check if test DB is running
docker ps | grep vegapunk_db_test

# Verify port is correct
echo $DATABASE_TEST_URL
```

### Tests failing after schema changes
```bash
# Restart test container to reset schema
docker compose -f docker/docker-compose.yml restart timescaledb_test
```

### Slow tests
- Test DB uses tmpfs (in-memory), so should be fast
- If slow, check if you're hitting production DB by mistake
- Use `pytest -v` to see which tests are slow

## Current Test Coverage

```bash
$ pytest --cov=. --cov-report=term
conftest.py              100%
models.py                100%
tests/test_models.py     100%
```

All 9 tests passing! ✅

## Next Steps

1. Add tests for business logic (strategies, risk management)
2. Add API endpoint tests (when FastAPI is set up)
3. Add integration tests (Alpaca API mocking)
4. Set up continuous integration

---

**Test Database**: `vegapunk_db_test` running on port 5433 (tmpfs)
**Test Status**: 9/9 passing ✓
