import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_required_directories_exist():
    expected_dirs = [
        "src",
        "src/generators",
        "src/synthea",
        "notebooks",
        "sql",
        "sql/ddl",
        "sql/queries",
        "pipelines",
        "dashboards",
        "docs",
        "tests",
        "docker",
        "config",
    ]
    for d in expected_dirs:
        path = os.path.join(ROOT_DIR, d)
        assert os.path.isdir(path), f"Missing directory: {d}"


def test_required_files_exist():
    expected_files = [
        "README.md",
        "requirements.txt",
        ".env.example",
        ".gitignore",
        "setup.cfg",
        "docker/docker-compose.yml",
        "docker/Dockerfile.generator",
        ".github/workflows/ci.yml",
    ]
    for f in expected_files:
        path = os.path.join(ROOT_DIR, f)
        assert os.path.isfile(path), f"Missing file: {f}"


def test_env_example_has_required_keys():
    env_path = os.path.join(ROOT_DIR, ".env.example")
    with open(env_path, "r") as f:
        content = f.read()

    required_keys = [
        "MSSQL_HOST",
        "MSSQL_PORT",
        "MSSQL_DB",
        "ADLS_ACCOUNT_NAME",
        "EVENT_HUB_CONNECTION_STRING",
        "SYNAPSE_SERVER",
        "FLASK_PORT",
    ]
    for key in required_keys:
        assert key in content, f"Missing env key: {key}"


def test_requirements_has_core_packages():
    req_path = os.path.join(ROOT_DIR, "requirements.txt")
    with open(req_path, "r") as f:
        content = f.read()

    core_packages = [
        "pandas",
        "pyspark",
        "faker",
        "sqlalchemy",
        "pyodbc",
        "flask",
        "pytest",
    ]
    for pkg in core_packages:
        assert pkg in content, f"Missing package: {pkg}"
