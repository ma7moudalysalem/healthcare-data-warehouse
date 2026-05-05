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
        "LICENSE",
        "CONTRIBUTING.md",
        "Makefile",
        "requirements.txt",
        ".env.example",
        ".gitignore",
        "setup.cfg",
        "docker/docker-compose.yml",
        "docker/Dockerfile.generator",
        "docker/Dockerfile.streamlit",
        ".github/workflows/ci.yml",
        # M2 deliverables
        "sql/ddl/01_oltp_source_schema.sql",
        "sql/ddl/10_warehouse_schema.sql",
        "sql/stored_procedures/sp_merge_dim_patient_scd2.sql",
        "docs/architecture/er_diagram_warehouse.md",
        "docs/data_dictionary/data_dictionary.md",
        # M3 deliverables
        "pipelines/bronze/bronze_ingest.py",
        "pipelines/silver/silver_common.py",
        "pipelines/streaming/vitals_streaming.py",
        "pipelines/adf_templates/PL_Daily_Bronze_Silver_Gold.json",
        # M4 deliverables
        "dashboards/streamlit/app.py",
        "dashboards/powerbi/dax_measures.md",
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
