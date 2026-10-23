"""Exercise schema verification with synthetic metadata, never a live database."""

import ast
import copy
import importlib.util
import json
import re
from contextlib import nullcontext
from io import StringIO

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import SQLAlchemyError

from tools import check_db_schema as check


@pytest.fixture
def baseline():
    return check.load_baseline()


def clean(value):
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items() if key != "source"}
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value


def index(columns, unique=False):
    return {
        "columns": list(columns),
        "unique": unique,
        "index_type": "BTREE",
        "visible": True,
        "prefix_lengths": [None] * len(columns),
        "directions": ["A"] * len(columns),
        "expressions": [None] * len(columns),
    }


@pytest.fixture
def snapshot(baseline):
    tables = clean(baseline["tables"])
    for table in tables.values():
        table["indexes"] = {
            name: index(spec["columns"]) for name, spec in table["indexes"].items()
        }
        table["indexes"]["PRIMARY"] = index(table["primary_key"]["columns"], True)
        for name, spec in table["unique_constraints"].items():
            table["indexes"][name] = index(spec["columns"], True)
    for table, name, column in (
        ("problems", "fk_problems_creator", "created_by"),
        ("submission_cases", "fk_sc_case", "test_case_id"),
        ("user_problem_stats", "fk_ups_problem", "problem_id"),
        ("user_problem_stats", "fk_ups_first_ac_submission", "first_ac_submission_id"),
    ):
        tables[table]["indexes"][name] = index([column])
    return {
        "database": "synthetic_test_database",
        "schema_defaults": clean(baseline["schema_defaults"]),
        "tables": tables,
        "routines": [],
        "triggers": [],
        "events": [],
        "alembic_version": {
            "present": True,
            "kind": "BASE TABLE",
            "versions": ["0001_initial_schema"],
        },
        "row_counts": {name: 0 for name in check.TABLE_ORDER},
    }


def empty_snapshot(snapshot):
    snapshot["tables"] = {}
    snapshot["row_counts"] = {}
    snapshot["alembic_version"] = {"present": False, "kind": None, "versions": []}
    return snapshot


def test_reviewed_baseline_has_all_objects_and_provenance(baseline):
    tables = baseline["tables"]
    assert tuple(tables) == check.TABLE_ORDER
    assert sum(len(table["columns"]) for table in tables.values()) == 84
    assert sum(len(table["unique_constraints"]) for table in tables.values()) == 6
    assert sum(len(table["indexes"]) for table in tables.values()) == 10
    assert sum(len(table["foreign_keys"]) for table in tables.values()) == 12


def test_initial_matches_and_classifies_support_indexes(baseline, snapshot):
    issues, classes = check.compare_snapshot(baseline, snapshot, "initial", True)
    assert issues == []
    assert classes["problems"]["fk_problems_creator"] == "foreign_key_support"
    assert classes["problems"]["idx_problems_status_difficulty_id"] == "query_index"
    assert classes["users"]["uk_users_username"] == "unique_constraint"
    assert classes["users"]["PRIMARY"] == "primary_key"


@pytest.mark.parametrize(
    ("table", "column", "actual"),
    [
        ("test_cases", "is_sample", "tinyint"),
        ("test_cases", "is_sample", "tinyint(1) unsigned"),
        ("submission_cases", "is_sample", "tinyint"),
        ("user_problem_stats", "solved", "tinyint"),
        ("submissions", "attempts", "tinyint"),
        ("submissions", "enqueue_count", "tinyint(3) unsigned"),
        ("users", "id", "bigint"),
        ("users", "username", "varchar(31)"),
        ("users", "created_at", "datetime"),
    ],
)
def test_full_column_type_is_not_normalized(baseline, snapshot, table, column, actual):
    snapshot["tables"][table]["columns"][column]["column_type"] = actual
    issues, _ = check.compare_snapshot(baseline, snapshot, "initial")
    assert any(
        f"tables.{table}.columns.{column}.column_type" in item for item in issues
    )


@pytest.mark.parametrize(
    ("column", "property_name", "actual"),
    [
        ("role", "default", "user"),
        ("created_at", "default", "current_timestamp"),
        ("updated_at", "on_update", None),
        ("username", "nullable", True),
        ("id", "auto_increment", False),
        ("created_at", "datetime_precision", 0),
        ("username", "collation", "utf8mb4_bin"),
    ],
)
def test_column_attributes_are_checked(
    baseline, snapshot, column, property_name, actual
):
    snapshot["tables"]["users"]["columns"][column][property_name] = actual
    issues, _ = check.compare_snapshot(baseline, snapshot, "initial")
    assert any(f"users.columns.{column}.{property_name}" in item for item in issues)


@pytest.mark.parametrize("extra", [False, True])
def test_missing_and_extra_tables(baseline, snapshot, extra):
    if extra:
        snapshot["tables"]["unexpected_view"] = {"kind": "VIEW"}
        expected = "tables.unexpected_view：多余"
    else:
        del snapshot["tables"]["users"]
        expected = "tables.users：缺失"
    issues, _ = check.compare_snapshot(baseline, snapshot, "initial")
    assert any(expected in item for item in issues)


@pytest.mark.parametrize("extra", [False, True])
def test_missing_and_extra_columns(baseline, snapshot, extra):
    columns = snapshot["tables"]["users"]["columns"]
    if extra:
        columns["surprise"] = dict(columns["username"])
        expected = "users.columns.surprise：多余"
    else:
        del columns["username"]
        expected = "users.columns.username：缺失"
    issues, _ = check.compare_snapshot(baseline, snapshot, "initial")
    assert any(expected in item for item in issues)


@pytest.mark.parametrize(
    ("table", "group", "name"),
    [
        ("user_problem_stats", "primary_key", None),
        ("submissions", "unique_constraints", "uk_sub_user_idempotency"),
        ("submissions", "indexes", "idx_sub_user_problem_id"),
    ],
)
def test_composite_column_order_is_significant(baseline, snapshot, table, group, name):
    spec = snapshot["tables"][table][group]
    spec = spec[name] if name else spec
    spec["columns"].reverse()
    issues, _ = check.compare_snapshot(baseline, snapshot, "initial")
    assert any(
        f"tables.{table}.{group}" in item and "columns" in item for item in issues
    )


@pytest.mark.parametrize(
    ("name", "property_name", "actual"),
    [
        ("fk_sc_case", "on_delete", "RESTRICT"),
        ("fk_sc_sub", "on_delete", "RESTRICT"),
        ("fk_sc_case", "on_update", "CASCADE"),
        ("fk_sc_case", "referred_schema", "another_database"),
        ("fk_sc_case", "referred_table", "problems"),
        ("fk_sc_case", "referred_columns", ["another_id"]),
    ],
)
def test_foreign_key_targets_and_actions(
    baseline, snapshot, name, property_name, actual
):
    snapshot["tables"]["submission_cases"]["foreign_keys"][name][property_name] = actual
    issues, _ = check.compare_snapshot(baseline, snapshot, "initial")
    assert any(f"foreign_keys.{name}.{property_name}" in item for item in issues)


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "unique", "prefix", "invisible", "unnecessary"]
)
def test_support_indexes_cannot_hide_schema_drift(baseline, snapshot, change):
    indexes = snapshot["tables"]["problems"]["indexes"]
    if change == "missing":
        del indexes["fk_problems_creator"]
    elif change == "duplicate":
        indexes["redundant_creator"] = index(["created_by"])
    elif change == "unique":
        indexes["fk_problems_creator"]["unique"] = True
    elif change == "prefix":
        indexes["fk_problems_creator"]["prefix_lengths"] = [1]
    elif change == "invisible":
        indexes["fk_problems_creator"]["visible"] = False
    else:
        indexes["redundant_status"] = index(["status"])
    issues, _ = check.compare_snapshot(baseline, snapshot, "initial")
    assert any("problems.indexes" in item for item in issues)


@pytest.mark.parametrize("group", ["routines", "triggers", "events"])
def test_base_rejects_other_database_objects(baseline, snapshot, group):
    snapshot = empty_snapshot(snapshot)
    snapshot[group] = ["leftover"]
    issues, _ = check.compare_snapshot(baseline, snapshot, "base")
    assert any(group in item for item in issues)


@pytest.mark.parametrize("kind", ["BASE TABLE", "VIEW"])
def test_base_rejects_tables_and_views(baseline, snapshot, kind):
    snapshot = empty_snapshot(snapshot)
    snapshot["tables"]["leftover"] = {"kind": kind}
    issues, _ = check.compare_snapshot(baseline, snapshot, "base")
    assert any("tables.leftover" in item for item in issues)


@pytest.mark.parametrize("present", [False, True])
def test_base_reports_empty_version_table_separately(baseline, snapshot, present):
    snapshot = empty_snapshot(snapshot)
    if present:
        snapshot["alembic_version"] = {
            "present": True,
            "kind": "BASE TABLE",
            "versions": [],
        }
    assert check.compare_snapshot(baseline, snapshot, "base")[0] == []


@pytest.mark.parametrize(
    "version",
    [
        {"present": True, "kind": "VIEW", "versions": []},
        {"present": True, "kind": "BASE TABLE", "versions": ["0001_initial_schema"]},
    ],
)
def test_base_rejects_version_view_or_nonempty_version(baseline, snapshot, version):
    snapshot = empty_snapshot(snapshot)
    snapshot["alembic_version"] = version
    issues, _ = check.compare_snapshot(baseline, snapshot, "base")
    assert any("alembic_version" in item for item in issues)


def test_exact_count_blocks_nonempty_data(baseline, snapshot):
    snapshot["row_counts"]["submissions"] = 1
    issues, _ = check.compare_snapshot(baseline, snapshot, "initial", True)
    assert any("row_counts.submissions" in item for item in issues)


@pytest.mark.parametrize(
    "case", ["before", "after", "further_after", "zero", "malformed", "missing"]
)
def test_source_outside_allowed_range_or_malformed_fails(baseline, case):
    start, end = baseline["source_range"]
    sources = {
        "before": f"D:{start - 1}",
        "after": f"D:{end + 1}",
        "further_after": f"D:{end + 2}",
        "zero": "D:0",
        "malformed": "D:bad",
        "missing": None,
    }
    baseline["tables"]["users"]["columns"]["username"]["source"] = sources[case]
    design = check.DESIGN_PATH.read_text(encoding="utf-8")
    with pytest.raises(check.CheckError, match="预期基线需复核"):
        check.validate_baseline(baseline, design)


@pytest.mark.parametrize(
    "path",
    [
        ("tables", "users"),
        ("tables", "users", "columns", "username"),
        ("tables", "users", "primary_key"),
        ("tables", "users", "unique_constraints", "uk_users_username"),
        ("tables", "problems", "indexes", "idx_problems_status_difficulty_id"),
        ("tables", "problems", "foreign_keys", "fk_problems_creator"),
    ],
)
def test_each_object_requires_its_own_source(baseline, path):
    obj = baseline
    for key in path:
        obj = obj[key]
    del obj["source"]
    with pytest.raises(check.CheckError, match="source"):
        check.validate_baseline(baseline, check.DESIGN_PATH.read_text(encoding="utf-8"))


def test_range_change_reports_baseline_and_measured_bounds(baseline):
    start, end = baseline["source_range"]
    design = "\n" + check.DESIGN_PATH.read_text(encoding="utf-8")
    with pytest.raises(check.CheckError) as caught:
        check.validate_baseline(baseline, design)
    assert str(caught.value) == (
        f"预期基线需复核：设计 §9 范围由 {start}—{end} 变为 {start + 1}—{end + 1}"
    )


def test_expected_range_is_taken_from_json_not_a_module_constant(baseline):
    start, end = baseline["source_range"]
    baseline["source_range"] = [start - 1, end + 1]
    with pytest.raises(check.CheckError) as caught:
        check.validate_baseline(baseline, check.DESIGN_PATH.read_text(encoding="utf-8"))
    assert str(caught.value) == (
        f"预期基线需复核：设计 §9 范围由 {start - 1}—{end + 1} 变为 {start}—{end}"
    )


def test_source_within_range_must_point_to_the_named_object(baseline):
    baseline["tables"]["users"]["columns"]["username"]["source"] = baseline["tables"][
        "users"
    ]["columns"]["password_hash"]["source"]
    with pytest.raises(check.CheckError, match="与对象不对应"):
        check.validate_baseline(baseline, check.DESIGN_PATH.read_text(encoding="utf-8"))


def test_design_ddl_change_requires_review_without_rewriting(baseline):
    design = check.DESIGN_PATH.read_text(encoding="utf-8")
    changed = design.replace("DEFAULT 'USER'", "DEFAULT 'ADMIN'", 1)
    before = copy.deepcopy(baseline)
    with pytest.raises(check.CheckError, match="DDL 摘要"):
        check.validate_baseline(baseline, changed)
    assert baseline == before


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (0, "0"),
        ("CURRENT_TIMESTAMP(3)", "current_timestamp(3)"),
        ("current_timestamp()", "current_timestamp"),
        (" USER ", " USER "),
        ("USER", "USER"),
        ("", ""),
    ],
)
def test_default_normalization_preserves_literal_values(value, expected):
    assert check.normalize_default(value) == expected


class Rows:
    def __init__(self, values):
        self.values = values

    def mappings(self):
        return iter(self.values)

    def scalars(self):
        return iter(self.values)


class MetadataConnection:
    """Return controlled DBAPI-style metadata and reject non-SELECT statements."""

    def __init__(self, database="alternate_database", version=False):
        self.database = database
        self.statements = []
        self.counts = {name: 0 for name in check.TABLE_ORDER}
        self.metadata = {
            "SCHEMATA": [{"charset": "utf8mb4", "collation": "utf8mb4_0900_ai_ci"}],
            "TABLES": [
                {
                    "name": name,
                    "kind": "BASE TABLE",
                    "engine": "InnoDB",
                    "charset": "utf8mb4",
                    "collation": "utf8mb4_0900_ai_ci",
                }
                for name in check.TABLE_ORDER
            ],
            "COLUMNS": [],
            "REFERENTIAL_CONSTRAINTS": [],
            "TABLE_CONSTRAINTS": [],
            "STATISTICS": [],
            "ROUTINES": [],
            "TRIGGERS": [],
            "EVENTS": [],
        }
        if version:
            self.metadata["TABLES"].append(
                {
                    "name": "alembic_version",
                    "kind": "BASE TABLE",
                    "engine": "InnoDB",
                    "charset": "utf8mb4",
                    "collation": "utf8mb4_0900_ai_ci",
                }
            )

    def scalar(self, statement):
        sql = str(statement)
        self.statements.append((sql, None))
        if sql == "SELECT DATABASE()":
            return self.database
        assert sql.startswith("SELECT COUNT(*) FROM ")
        name = sql.rsplit(".", 1)[1].strip(chr(96))
        return self.counts[name]

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.statements.append((sql, parameters))
        assert sql.startswith("SELECT ")
        if sql.startswith("SELECT version_num FROM "):
            return Rows(["0001_initial_schema"])
        assert parameters == {"schema": self.database}
        for name, values in self.metadata.items():
            if f"information_schema.{name} " in sql:
                return Rows(values)
        raise AssertionError(f"Unexpected metadata query: {sql}")


def test_counts_use_selected_database_and_all_nine_exact_queries():
    connection = MetadataConnection(database="test_schema" + chr(96) + "quoted")
    connection.counts["submissions"] = 7
    result = check.read_snapshot(connection, require_empty_data=True)
    assert result["database"] == connection.database
    assert result["row_counts"] == connection.counts
    counts = [
        sql for sql, _ in connection.statements if sql.startswith("SELECT COUNT(*)")
    ]
    assert len(counts) == 9
    tick = chr(96)
    escaped = tick + "test_schema" + tick * 2 + "quoted" + tick
    assert all(f"FROM {escaped}." in sql for sql in counts)
    assert all("TABLE_ROWS" not in sql for sql, _ in connection.statements)


def test_metadata_checks_all_object_families_without_counting_unless_requested():
    connection = MetadataConnection(version=True)
    result = check.read_snapshot(connection)
    assert len(result["tables"]) == 9
    assert "alembic_version" not in result["tables"]
    assert result["alembic_version"]["versions"] == ["0001_initial_schema"]
    statements = "\n".join(sql for sql, _ in connection.statements)
    for family in ("TABLES", "ROUTINES", "TRIGGERS", "EVENTS"):
        assert f"information_schema.{family}" in statements
    assert "COUNT(*)" not in statements
    assert result["row_counts"] == {}


def test_metadata_preserves_types_defaults_updates_and_constraint_order(baseline):
    connection = MetadataConnection()
    for table, name in (
        ("test_cases", "is_sample"),
        ("submissions", "attempts"),
        ("users", "updated_at"),
        ("submission_cases", "test_case_id"),
    ):
        expected = baseline["tables"][table]["columns"][name]
        extra = "DEFAULT_GENERATED"
        if expected["on_update"]:
            extra += " on update CURRENT_TIMESTAMP(3)"
        connection.metadata["COLUMNS"].append(
            {
                "table_name": table,
                "name": name,
                "position": expected["position"],
                "column_type": expected["column_type"],
                "nullable": "YES" if expected["nullable"] else "NO",
                "default_value": (
                    "CURRENT_TIMESTAMP(3)"
                    if expected["default"] == "current_timestamp(3)"
                    else expected["default"]
                ),
                "extra": extra,
                "charset": expected["charset"],
                "collation": expected["collation"],
                "datetime_precision": expected["datetime_precision"],
                "generation_expression": "",
            }
        )
    connection.metadata["REFERENTIAL_CONSTRAINTS"] = [
        {
            "table_name": "submission_cases",
            "name": "fk_sc_case",
            "on_update": "RESTRICT",
            "on_delete": "SET NULL",
        }
    ]
    connection.metadata["TABLE_CONSTRAINTS"] = [
        {
            "table_name": "submission_cases",
            "name": "fk_sc_case",
            "kind": "FOREIGN KEY",
            "column_name": "test_case_id",
            "referred_schema": connection.database,
            "referred_table": "test_cases",
            "referred_column": "id",
        }
    ] + [
        {
            "table_name": "user_problem_stats",
            "name": "PRIMARY",
            "kind": "PRIMARY KEY",
            "column_name": column,
        }
        for column in ("user_id", "problem_id")
    ]
    connection.metadata["STATISTICS"] = [
        {
            "table_name": "user_problem_stats",
            "name": "PRIMARY",
            "non_unique": 0,
            "column_name": column,
            "prefix_length": None,
            "direction": "A",
            "index_type": "BTREE",
            "visible": "YES",
            "expression": None,
        }
        for column in ("user_id", "problem_id")
    ]
    result = check.read_snapshot(connection)
    for table, columns in result["tables"].items():
        for name, actual in columns["columns"].items():
            assert actual == clean(baseline["tables"][table]["columns"][name])
    stats = result["tables"]["user_problem_stats"]
    assert stats["primary_key"]["columns"] == ["user_id", "problem_id"]
    assert stats["indexes"]["PRIMARY"] == index(["user_id", "problem_id"], True)
    assert result["tables"]["submission_cases"]["foreign_keys"]["fk_sc_case"] == clean(
        baseline["tables"]["submission_cases"]["foreign_keys"]["fk_sc_case"]
    )


def test_no_selected_database_is_configuration_error():
    with pytest.raises(check.CheckError, match="未选择数据库"):
        check.read_snapshot(MetadataConnection(database=None))


@pytest.mark.parametrize("value", [None, -1, "0"])
def test_unavailable_or_invalid_exact_count_is_error(value):
    connection = MetadataConnection()
    connection.counts["users"] = value
    with pytest.raises(check.CheckError, match="精确行数"):
        check.read_snapshot(connection, True)


@pytest.mark.parametrize(
    "value",
    [None, "", " ", "not-a-url", "sqlite:///test.db", "mysql+asyncmy://example/db"],
)
def test_missing_or_wrong_driver_fails_without_echoing_url(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("DATABASE_URL_SYNC", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL_SYNC", value)
    with pytest.raises(check.CheckError) as caught:
        check.database_url()
    if value and value.strip():
        assert value not in str(caught.value)


def test_url_percent_encoding_is_not_routed_through_ini(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL_SYNC", "mysql+pymysql://example:fake%40pass%25@localhost/test"
    )
    url = check.database_url()
    assert url.drivername == "mysql+pymysql"
    assert url.password == "fake@pass%"


class Engine:
    def __init__(self):
        self.disposed = False

    def connect(self):
        return nullcontext(object())

    def dispose(self):
        self.disposed = True


@pytest.mark.parametrize("mismatch", [False, True])
def test_cli_exit_codes_and_json_output(
    monkeypatch, capsys, baseline, snapshot, mismatch
):
    snapshot = empty_snapshot(snapshot)
    if mismatch:
        snapshot["events"] = ["leftover_event"]
    engine = Engine()
    monkeypatch.setenv(
        "DATABASE_URL_SYNC", "mysql+pymysql://example:fake@localhost/test"
    )
    monkeypatch.setattr(check, "create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(check, "read_snapshot", lambda *args: snapshot)
    code = check.main(["--expect", "base", "--format", "json"])
    report = json.loads(capsys.readouterr().out)
    assert code == int(mismatch)
    assert report["status"] == ("mismatch" if mismatch else "ok")
    assert bool(report["differences"]) == mismatch
    assert report["snapshot"]["alembic_version"]["present"] is False
    assert engine.disposed


def test_cli_connection_error_returns_two_and_hides_credentials(monkeypatch, capsys):
    marker = "never-print-this-fake-password"
    monkeypatch.setenv(
        "DATABASE_URL_SYNC", f"mysql+pymysql://example:{marker}@localhost/test"
    )

    def fail(*args, **kwargs):
        raise SQLAlchemyError(marker)

    monkeypatch.setattr(check, "create_engine", fail)
    assert check.main(["--expect", "initial", "--format", "json"]) == 2
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "error"
    assert marker not in output


def test_cli_baseline_error_prevents_any_engine_creation(monkeypatch, capsys):
    def fail():
        raise check.CheckError("预期基线需复核：source 超出 §9")

    def forbidden(*args, **kwargs):
        pytest.fail("Database access must not precede baseline validation")

    monkeypatch.setattr(check, "load_baseline", fail)
    monkeypatch.setattr(check, "create_engine", forbidden)
    assert check.main(["--expect", "base"]) == 2
    assert "预期基线需复核" in capsys.readouterr().out


def test_initial_migration_has_complete_upgrade_and_downgrade(baseline):
    path = check.ROOT / "backend/alembic/versions/0001_initial_schema.py"
    module = ast.parse(path.read_text(encoding="utf-8"))
    assignments = [node for node in module.body if isinstance(node, ast.Assign)]
    assert len(assignments) == 2
    assert {
        node.targets[0].id: ast.literal_eval(node.value) for node in assignments
    } == {"revision": "0001_initial_schema", "down_revision": None}
    functions = [node for node in module.body if isinstance(node, ast.FunctionDef)]
    assert [node.name for node in functions] == ["upgrade", "downgrade"]
    upgrade, downgrade = functions

    def op_calls(function):
        return [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "op"
        ]

    upgrade_calls = op_calls(upgrade)
    assert [call.func.attr for call in upgrade_calls] == (
        ["create_table"] * 9 + ["create_index"] * 10 + ["create_foreign_key"] * 12
    )
    expected_tables = (
        "users",
        "tags",
        "problems",
        "test_cases",
        "submissions",
        "submission_cases",
        "user_problem_stats",
        "problem_tags",
        "audit_logs",
    )
    total_columns = 0
    total_unique_constraints = 0
    for create_table, table_name in zip(
        upgrade_calls[:9], expected_tables, strict=True
    ):
        assert create_table.args
        assert isinstance(create_table.args[0], ast.Constant)
        assert create_table.args[0].value == table_name
        table_items = [
            arg
            for arg in create_table.args[1:]
            if isinstance(arg, ast.Call)
            and isinstance(arg.func, ast.Attribute)
            and isinstance(arg.func.value, ast.Name)
            and arg.func.value.id == "sa"
        ]
        column_names = [
            ast.literal_eval(arg.args[0])
            for arg in table_items
            if arg.func.attr == "Column"
        ]
        expected = baseline["tables"][table_name]
        assert column_names == sorted(
            expected["columns"],
            key=lambda name: expected["columns"][name]["position"],
        )
        total_columns += len(column_names)
        unique_names = [
            ast.literal_eval(keyword.value)
            for arg in table_items
            if arg.func.attr == "UniqueConstraint"
            for keyword in arg.keywords
            if keyword.arg == "name"
        ]
        assert unique_names == list(expected["unique_constraints"])
        total_unique_constraints += len(unique_names)
        for node in ast.walk(create_table):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "sa"
            ):
                assert node.func.attr not in {
                    "ForeignKey",
                    "ForeignKeyConstraint",
                    "Index",
                }
            if isinstance(node, ast.keyword) and node.arg == "index":
                assert ast.literal_eval(node.value) is False
    assert total_columns == 84
    assert total_unique_constraints == 6

    expected_indexes = sorted(
        [
            (name, table_name, spec)
            for table_name, table in baseline["tables"].items()
            for name, spec in table["indexes"].items()
        ],
        key=lambda item: int(item[2]["source"].removeprefix("D:")),
    )
    expected_foreign_keys = sorted(
        [
            (name, table_name, spec)
            for table_name, table in baseline["tables"].items()
            for name, spec in table["foreign_keys"].items()
        ],
        key=lambda item: int(item[2]["source"].removeprefix("D:")),
    )
    assert len(expected_indexes) == 10
    assert len(expected_foreign_keys) == 12
    for call, (name, table_name, spec) in zip(
        upgrade_calls[9:19], expected_indexes, strict=True
    ):
        assert [ast.literal_eval(arg) for arg in call.args] == [
            name,
            table_name,
            spec["columns"],
        ]
        assert {
            keyword.arg: ast.literal_eval(keyword.value) for keyword in call.keywords
        } == {"unique": False}
    for call, (name, table_name, spec) in zip(
        upgrade_calls[19:], expected_foreign_keys, strict=True
    ):
        assert [ast.literal_eval(arg) for arg in call.args] == [
            name,
            table_name,
            spec["referred_table"],
            spec["columns"],
            spec["referred_columns"],
        ]
        assert [keyword.arg for keyword in call.keywords] == ["ondelete", "onupdate"]
        assert {
            keyword.arg: ast.literal_eval(keyword.value) for keyword in call.keywords
        } == {"ondelete": spec["on_delete"], "onupdate": spec["on_update"]}

    downgrade_calls = op_calls(downgrade)
    assert [call.func.attr for call in downgrade_calls] == (
        ["drop_constraint"] * 12 + ["drop_index"] * 10 + ["drop_table"] * 9
    )
    for call, (name, table_name, _spec) in zip(
        downgrade_calls[:12], reversed(expected_foreign_keys), strict=True
    ):
        assert [ast.literal_eval(arg) for arg in call.args] == [name, table_name]
        assert {
            keyword.arg: ast.literal_eval(keyword.value) for keyword in call.keywords
        } == {"type_": "foreignkey"}
    for call, (name, table_name, _spec) in zip(
        downgrade_calls[12:22], reversed(expected_indexes), strict=True
    ):
        assert [ast.literal_eval(arg) for arg in call.args] == [name]
        assert {
            keyword.arg: ast.literal_eval(keyword.value) for keyword in call.keywords
        } == {"table_name": table_name}
    for call, table_name in zip(
        downgrade_calls[22:], reversed(expected_tables), strict=True
    ):
        assert [ast.literal_eval(arg) for arg in call.args] == [table_name]
        assert not call.keywords


def test_initial_migration_column_semantics_match_baseline(baseline, monkeypatch):
    path = check.ROOT / "backend/alembic/versions/0001_initial_schema.py"
    spec = importlib.util.spec_from_file_location("initial_schema_semantics", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Recorder:
        def __init__(self):
            self.metadata = sa.MetaData()

        def create_table(self, name, *elements, **kwargs):
            sa.Table(name, self.metadata, *elements, **kwargs)

        def create_index(self, *args, **kwargs):
            pass

        def create_foreign_key(self, *args, **kwargs):
            pass

    def normalize_type(value):
        return str(value).strip().lower().replace("integer", "int")

    def normalize_default(value):
        if value is None:
            return None
        return str(value).strip().strip("'\"").lower()

    recorder = Recorder()
    monkeypatch.setattr(module, "op", recorder)
    module.upgrade()
    assert set(recorder.metadata.tables) == set(baseline["tables"])
    dialect = mysql.dialect()
    # charset/collation 的实际继承结果留给实库轮验证，内存声明不能证明。
    for table_name, table in recorder.metadata.tables.items():
        expected = baseline["tables"][table_name]
        assert list(table.columns.keys()) == sorted(
            expected["columns"],
            key=lambda name: expected["columns"][name]["position"],
        )
        assert [column.name for column in table.primary_key] == expected["primary_key"][
            "columns"
        ], table_name
        assert {
            constraint.name: [column.name for column in constraint.columns]
            for constraint in table.constraints
            if isinstance(constraint, sa.UniqueConstraint)
        } == {
            name: constraint["columns"]
            for name, constraint in expected["unique_constraints"].items()
        }, table_name
        for column in table.columns:
            location = f"{table_name}.{column.name}"
            column_expected = expected["columns"][column.name]
            default = (
                str(column.server_default.arg)
                if column.server_default is not None
                else None
            )
            on_update = None
            if default is not None:
                parts = re.split(r"\s+ON UPDATE\s+", default, maxsplit=1, flags=re.I)
                default = parts[0]
                if len(parts) == 2:
                    on_update = parts[1]
            assert {
                "column_type": normalize_type(column.type.compile(dialect=dialect)),
                "nullable": column.nullable,
                "default": normalize_default(default),
                "on_update": normalize_default(on_update),
                "auto_increment": column.autoincrement is True,
            } == {
                "column_type": normalize_type(column_expected["column_type"]),
                "nullable": column_expected["nullable"],
                "default": normalize_default(column_expected["default"]),
                "on_update": normalize_default(column_expected["on_update"]),
                "auto_increment": column_expected["auto_increment"],
            }, location
            if column_expected["auto_increment"]:
                assert column.autoincrement is True, location
            else:
                assert column.autoincrement in (False, "auto"), location


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_initial_migration_offline_sql_never_connects(monkeypatch, direction):
    from alembic.config import Config
    from sqlalchemy.engine import URL

    from alembic import command

    def forbidden(*args, **kwargs):
        pytest.fail("Offline rendering must never create an engine or connection")

    monkeypatch.setattr("sqlalchemy.create_engine", forbidden)
    monkeypatch.setattr("sqlalchemy.engine.Engine.connect", forbidden)
    url = URL.create(
        "mysql+pymysql",
        username="offline",
        password="offline",
        host="127.0.0.1",
        port=13306,
        database="oj",
    )
    monkeypatch.setenv("DATABASE_URL_SYNC", url.render_as_string(hide_password=False))
    output = StringIO()
    config = Config(str(check.ROOT / "backend/alembic.ini"), output_buffer=output)
    if direction == "upgrade":
        command.upgrade(config, "head", sql=True)
        prefix = "CREATE TABLE "
        expected_tables = list(check.TABLE_ORDER)
        index_fragment = "CREATE INDEX "
        foreign_key_fragment = " ADD CONSTRAINT "
    else:
        command.downgrade(config, "0001_initial_schema:base", sql=True)
        prefix = "DROP TABLE "
        expected_tables = list(reversed(check.TABLE_ORDER))
        index_fragment = "DROP INDEX "
        foreign_key_fragment = " DROP FOREIGN KEY "
    lines = output.getvalue().splitlines()
    tables = [
        line.removeprefix(prefix).split()[0].rstrip(";")
        for line in lines
        if line.startswith(prefix)
    ]
    assert [table for table in tables if table != "alembic_version"] == expected_tables
    assert sum(line.startswith(index_fragment) for line in lines) == 10
    assert sum(foreign_key_fragment in line for line in lines) == 12


def test_alembic_configuration_resolves_revision_without_running_env():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(check.ROOT / "backend/alembic.ini"))
    assert config.get_main_option("sqlalchemy.url") == ""
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["0001_initial_schema"]
    assert script.get_revision("0001_initial_schema").down_revision is None


def test_standard_template_renders_valid_python_in_memory():
    from mako.template import Template

    template = Template(filename=str(check.ROOT / "backend/alembic/script.py.mako"))
    rendered = template.render(
        message="Synthetic template check",
        up_revision="synthetic_revision",
        down_revision=None,
        create_date="synthetic",
        imports="",
        branch_labels=None,
        depends_on=None,
        upgrades="",
        downgrades="",
        comma=lambda value: "" if value is None else str(value),
    )
    ast.parse(rendered)
