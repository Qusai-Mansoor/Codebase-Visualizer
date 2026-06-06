import pytest


@pytest.fixture
def my_fixture():
    return 42


@pytest.fixture(scope='session')
def session_fixture():
    return 'session'
