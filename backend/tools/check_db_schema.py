"""Compare MySQL metadata with the reviewed design baseline using SELECT only."""

# CLI 入口 main 先验证独立设计基线，再读取数据库事实，最后交给纯比较函数。
# 本工具不执行迁移；read_snapshot 需要真实连接，测试用合成快照或替身隔离它。
import argparse
import hashlib
import json
import os
import re
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = ROOT / "backend/tests/fixtures/schema_v1.json"
DESIGN_PATH = ROOT / "docs/project-design.md"
TABLE_ORDER = (
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


class CheckError(ValueError):
    """Report configuration or baseline errors without revealing credentials."""


def design_section(design):
    """Find section 9 and exclude its trailing blank separator."""
    lines = design.splitlines()
    start = next((i for i, line in enumerate(lines, 1) if line.startswith("## 9. ")), 0)
    end = next(
        (
            i - 1
            for i, line in enumerate(lines, 1)
            if i > start and line.startswith("## ")
        ),
        len(lines),
    )
    while end > start and not lines[end - 1].strip():
        end -= 1
    if not start:
        raise CheckError("预期基线需复核：找不到设计 §9")
    return lines, start, end


def design_digest(design):
    """Fingerprint the nine design DDL blocks, independently of migrations."""
    # 只提取 §9 的九段建表 SQL；迁移和实库都不能反过来生成期望值，否则会自证正确。
    lines, start, end = design_section(design)
    section = "\n".join(lines[start - 1 : end])
    fence = chr(96) * 3
    blocks = re.findall(fence + r"sql\n(CREATE TABLE .*?)\n" + fence, section, re.S)
    if len(blocks) != len(TABLE_ORDER):
        raise CheckError("预期基线需复核：设计 DDL 数量不是九张表")
    return hashlib.sha256("\n\n".join(blocks).encode("utf-8")).hexdigest()


def validate_baseline(baseline, design):
    """Validate every object's source before any database connection is opened."""
    lines, start, end = design_section(design)
    expected_range = baseline.get("source_range")
    if (
        not isinstance(expected_range, list)
        or len(expected_range) != 2
        or any(type(value) is not int for value in expected_range)
        or not 1 <= expected_range[0] <= expected_range[1]
    ):
        raise CheckError("预期基线需复核：source_range 无效")
    expected_start, expected_end = expected_range
    if (start, end) != (expected_start, expected_end):
        raise CheckError(
            f"预期基线需复核：设计 §9 范围由 {expected_start}—{expected_end} "
            f"变为 {start}—{end}"
        )
    if baseline.get("design_ddl_sha256") != design_digest(design):
        raise CheckError("预期基线需复核：设计 DDL 摘要已变化")
    if (
        baseline.get("format_version") != 1
        or baseline.get("revision") != "0001_initial_schema"
        or set(baseline.get("tables", {})) != set(TABLE_ORDER)
    ):
        raise CheckError("预期基线需复核：版本或表集合无效")

    # 摘要防结构内容漂移，D: 行号再逐对象核验出处；任一失效都要求人工复核基线。
    def source(obj, location, pattern):
        value = obj.get("source", "")
        match = re.fullmatch(r"D:([1-9]\d*)", value) if isinstance(value, str) else None
        if match is None or not start <= int(match[1]) <= end:
            raise CheckError(f"预期基线需复核：{location}.source 无效或超出 §9")
        if not re.search(pattern, lines[int(match[1]) - 1]):
            raise CheckError(f"预期基线需复核：{location}.source 与对象不对应")

    source(baseline["schema_defaults"], "schema_defaults", r"字符集与排序规则")
    for name, table in baseline["tables"].items():
        location = f"tables.{name}"
        source(table, location, rf"^CREATE TABLE {re.escape(name)} \(")
        for column, spec in table["columns"].items():
            source(
                spec,
                f"{location}.columns.{column}",
                rf"^\s+{re.escape(column)}\s+",
            )
        source(table["primary_key"], f"{location}.primary_key", r"PRIMARY KEY")
        for group, prefix in (
            ("unique_constraints", r"UNIQUE KEY"),
            ("indexes", r"KEY"),
            ("foreign_keys", r"CONSTRAINT"),
        ):
            for key, spec in table[group].items():
                source(
                    spec,
                    f"{location}.{group}.{key}",
                    rf"\b{prefix}\s+{re.escape(key)}\b",
                )
                if not spec["columns"] or not set(spec["columns"]) <= set(
                    table["columns"]
                ):
                    raise CheckError(f"预期基线需复核：{location}.{group}.{key} 列无效")
        if not set(table["primary_key"]["columns"]) <= set(table["columns"]):
            raise CheckError(f"预期基线需复核：{location}.primary_key 列无效")
        for key, spec in table["foreign_keys"].items():
            target = baseline["tables"].get(spec["referred_table"])
            if target is None or not set(spec["referred_columns"]) <= set(
                target["columns"]
            ):
                raise CheckError(f"预期基线需复核：{location}.{key} 引用无效")


def load_baseline():
    """Read the tracked expectation and its design source without rewriting either."""
    try:
        baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        design = DESIGN_PATH.read_text(encoding="utf-8")
        validate_baseline(baseline, design)
    except CheckError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise CheckError("预期基线需复核：文件不可读或结构无效") from None
    return baseline


def database_url():
    """Use only DATABASE_URL_SYNC and never include its value in diagnostics."""
    value = os.environ.get("DATABASE_URL_SYNC", "").strip()
    if not value:
        raise CheckError("DATABASE_URL_SYNC 缺失或为空")
    try:
        url = make_url(value)
    except (ArgumentError, ValueError):
        raise CheckError("DATABASE_URL_SYNC 格式无效") from None
    if url.drivername != "mysql+pymysql":
        raise CheckError("DATABASE_URL_SYNC 必须使用 mysql+pymysql 驱动")
    return url


def normalize_default(value):
    """Normalize timestamp syntax while preserving literal string values."""
    # 实库比较只统一时间函数写法；普通字符串保留大小写与空白，避免吞掉真实差异。
    if value is None:
        return None
    value = str(value)
    match = re.fullmatch(r"\s*current_timestamp(?:\((\d*)\))?\s*", value, flags=re.I)
    if match:
        precision = match[1]
        return "current_timestamp" + (f"({precision})" if precision else "")
    return value


def without_sources(value):
    """Remove provenance only; COLUMN_TYPE and column order remain exact."""
    # source 是设计出处而非数据库属性；只剥掉它，不改字段类型或列表列序。
    if isinstance(value, dict):
        return {
            key: without_sources(item) for key, item in value.items() if key != "source"
        }
    if isinstance(value, list):
        return [without_sources(item) for item in value]
    return value


def index_model(columns, unique=False):
    """Describe the full-length, visible BTREE indexes specified by section 9."""
    return {
        "columns": list(columns),
        "unique": unique,
        "index_type": "BTREE",
        "visible": True,
        "prefix_lengths": [None] * len(columns),
        "directions": ["A"] * len(columns),
        "expressions": [None] * len(columns),
    }


def declared_indexes(table):
    """Include PK/UNIQUE backing indexes without counting them as query indexes."""
    result = {"PRIMARY": index_model(table["primary_key"]["columns"], True)}
    result.update(
        (name, index_model(spec["columns"], True))
        for name, spec in table["unique_constraints"].items()
    )
    result.update(
        (name, index_model(spec["columns"])) for name, spec in table["indexes"].items()
    )
    return result


def differences(expected, actual, path):
    """Report missing, extra and changed properties with stable object paths."""
    # 字典按对象名比较，不受键排列影响；列表保持顺序，联合键的列序不能排序抹平。
    result = []
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(expected.keys() - actual.keys()):
            result.append(f"{path}.{key}：缺失")
        for key in sorted(actual.keys() - expected.keys()):
            result.append(f"{path}.{key}：多余")
        for key in sorted(expected.keys() & actual.keys()):
            result.extend(differences(expected[key], actual[key], f"{path}.{key}"))
    elif expected != actual:
        want = json.dumps(expected, ensure_ascii=False, sort_keys=True)
        got = json.dumps(actual, ensure_ascii=False, sort_keys=True)
        result.append(f"{path}：期望 {want}，实际 {got}")
    return result


def classify_indexes(table, actual, path):
    """Allow one necessary FK support index per uncovered column group.

    MySQL metadata cannot prove who created an index. This classifies its
    structural purpose, not its origin; redundant or unique extras still fail.
    """
    declared = declared_indexes(table)
    # 已声明索引的最左列前缀能覆盖外键时，不再要求额外支撑索引。
    # 这里按结构用途分类，元数据本身不能证明该索引是 MySQL 自动创建的。
    required = {
        tuple(spec["columns"])
        for spec in table["foreign_keys"].values()
        if not any(
            model["columns"][: len(spec["columns"])] == spec["columns"]
            for model in declared.values()
        )
    }
    classes = {}
    result = differences(
        declared,
        {name: model for name, model in actual.items() if name in declared},
        path,
    )
    for name in sorted(actual):
        if name in declared:
            classes[name] = (
                "primary_key"
                if name == "PRIMARY"
                else "unique_constraint"
                if name in table["unique_constraints"]
                else "query_index"
            )
            continue
        model = actual[name]
        columns = tuple(model["columns"])
        # 一个未覆盖列组只接受一个合规支撑索引；多余或带唯一性的索引仍报错。
        if columns in required and model == index_model(columns):
            required.remove(columns)
            classes[name] = "foreign_key_support"
        else:
            result.append(f"{path}.{name}：多余或不符合外键支持索引要求")
    for columns in sorted(required):
        result.append(f"{path}：缺少外键支持索引 {list(columns)}")
    return classes, result


def compare_snapshot(baseline, snapshot, expect, require_empty_data=False):
    """Compare collected facts without executing any SQL or migration."""
    # baseline 是审核过的期望，snapshot 是采集结果；此函数只比较内存数据。
    # initial 要求九表及版本号，base 要求业务对象清空，但允许空的 Alembic 版本表。
    result = differences(
        without_sources(baseline["schema_defaults"]),
        snapshot["schema_defaults"],
        "schema_defaults",
    )
    for group in ("routines", "triggers", "events"):
        result.extend(differences([], snapshot[group], group))
    version = snapshot["alembic_version"]
    if expect == "initial":
        result.extend(
            differences(
                {
                    "present": True,
                    "kind": "BASE TABLE",
                    "versions": [baseline["revision"]],
                },
                version,
                "alembic_version",
            )
        )
    elif version["present"]:
        result.extend(
            differences("BASE TABLE", version["kind"], "alembic_version.kind")
        )
        result.extend(differences([], version["versions"], "alembic_version.versions"))

    expected_tables = baseline["tables"] if expect == "initial" else {}
    actual_tables = snapshot["tables"]
    for name in sorted(expected_tables.keys() - actual_tables.keys()):
        result.append(f"tables.{name}：缺失")
    for name in sorted(actual_tables.keys() - expected_tables.keys()):
        result.append(f"tables.{name}：多余（{actual_tables[name]['kind']}）")
    classes = {}
    for name in sorted(expected_tables.keys() & actual_tables.keys()):
        table = expected_tables[name]
        expected = without_sources(table)
        expected.pop("indexes")
        actual = dict(actual_tables[name])
        indexes = actual.pop("indexes")
        result.extend(differences(expected, actual, f"tables.{name}"))
        classes[name], index_differences = classify_indexes(
            table, indexes, f"tables.{name}.indexes"
        )
        result.extend(index_differences)
    if require_empty_data:
        for name in TABLE_ORDER:
            if expect == "initial" or name in actual_tables:
                result.extend(
                    differences(
                        0, snapshot["row_counts"].get(name), f"row_counts.{name}"
                    )
                )
    return result, classes


def quote_identifier(value):
    """Quote database and fixed table names as MySQL identifiers, not SQL values."""
    # 标识符不能当成 :schema 这样的值参数绑定；用反引号并转义内部反引号。
    quote = chr(96)
    return quote + value.replace(quote, quote * 2) + quote


def read_snapshot(connection, require_empty_data=False):
    """Collect metadata and optional exact counts in the database selected by URL."""
    # 连接由 main 持有并关闭；本层只读当前 URL 所选库，避免硬编码库名查错环境。
    database = connection.scalar(text("SELECT DATABASE()"))
    if not isinstance(database, str) or not database:
        raise CheckError("DATABASE_URL_SYNC 未选择数据库")
    parameters = {"schema": database}

    def rows(sql):
        # 统一绑定 schema 值并转成按字段名访问的行；不是拼接用户输入到 SQL。
        return list(connection.execute(text(sql), parameters).mappings())

    schema = rows(
        "SELECT DEFAULT_CHARACTER_SET_NAME AS charset, "
        "DEFAULT_COLLATION_NAME AS collation FROM information_schema.SCHEMATA "
        "WHERE SCHEMA_NAME = :schema"
    )
    if len(schema) != 1:
        raise CheckError("无法读取当前数据库的元数据")
    snapshot = {
        "database": database,
        "schema_defaults": dict(schema[0]),
        "tables": {},
        "routines": [],
        "triggers": [],
        "events": [],
        "alembic_version": {"present": False, "kind": None, "versions": []},
        "row_counts": {},
    }
    for row in rows(
        "SELECT t.TABLE_NAME AS name, t.TABLE_TYPE AS kind, t.ENGINE AS engine, "
        "t.TABLE_COLLATION AS collation, c.CHARACTER_SET_NAME AS charset "
        "FROM information_schema.TABLES t LEFT JOIN "
        "information_schema.COLLATION_CHARACTER_SET_APPLICABILITY c "
        "ON t.TABLE_COLLATION = c.COLLATION_NAME "
        "WHERE t.TABLE_SCHEMA = :schema ORDER BY t.TABLE_NAME"
    ):
        name = row["name"]
        if name == "alembic_version":
            # Alembic 的版本表是迁移状态，不混进九张业务表的结构计数。
            version = snapshot["alembic_version"]
            version.update(present=True, kind=row["kind"])
            if row["kind"] == "BASE TABLE":
                qualified = ".".join(
                    (quote_identifier(database), quote_identifier("alembic_version"))
                )
                version["versions"] = list(
                    connection.execute(
                        text(
                            f"SELECT version_num FROM {qualified} ORDER BY version_num"
                        )
                    ).scalars()
                )
            continue
        snapshot["tables"][name] = {
            "kind": row["kind"],
            "engine": row["engine"],
            "charset": row["charset"],
            "collation": row["collation"],
            "columns": {},
            "primary_key": {"columns": []},
            "unique_constraints": {},
            "indexes": {},
            "foreign_keys": {},
            "check_constraints": [],
        }
    tables = snapshot["tables"]
    # position 和完整 COLUMN_TYPE 保留精度/unsigned；默认值与 ON UPDATE 分开采集。
    for row in rows(
        "SELECT TABLE_NAME AS table_name, COLUMN_NAME AS name, "
        "ORDINAL_POSITION AS position, COLUMN_TYPE AS column_type, "
        "IS_NULLABLE AS nullable, COLUMN_DEFAULT AS default_value, EXTRA AS extra, "
        "CHARACTER_SET_NAME AS charset, COLLATION_NAME AS collation, "
        "DATETIME_PRECISION AS datetime_precision, "
        "GENERATION_EXPRESSION AS generation_expression "
        "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = :schema "
        "ORDER BY TABLE_NAME, ORDINAL_POSITION"
    ):
        if row["table_name"] not in tables:
            continue
        extra = row["extra"] or ""
        update = re.search(
            r"\bon update\s+(current_timestamp(?:\(\d*\))?)", extra, re.I
        )
        tables[row["table_name"]]["columns"][row["name"]] = {
            "position": row["position"],
            "column_type": row["column_type"],
            "nullable": row["nullable"] == "YES",
            "default": normalize_default(row["default_value"]),
            "auto_increment": "auto_increment" in extra.lower(),
            "on_update": normalize_default(update[1]) if update else None,
            "charset": row["charset"],
            "collation": row["collation"],
            "datetime_precision": row["datetime_precision"],
            "generation_expression": row["generation_expression"] or "",
        }
    actions = {
        (row["table_name"], row["name"]): row
        for row in rows(
            "SELECT TABLE_NAME AS table_name, CONSTRAINT_NAME AS name, "
            "UPDATE_RULE AS on_update, DELETE_RULE AS on_delete "
            "FROM information_schema.REFERENTIAL_CONSTRAINTS "
            "WHERE CONSTRAINT_SCHEMA = :schema"
        )
    }
    # 约束一列一行；依赖下面的 ORDINAL_POSITION 排序，才能还原联合键的列序。
    for row in rows(
        "SELECT t.TABLE_NAME AS table_name, t.CONSTRAINT_NAME AS name, "
        "t.CONSTRAINT_TYPE AS kind, k.COLUMN_NAME AS column_name, "
        "k.REFERENCED_TABLE_SCHEMA AS referred_schema, "
        "k.REFERENCED_TABLE_NAME AS referred_table, "
        "k.REFERENCED_COLUMN_NAME AS referred_column "
        "FROM information_schema.TABLE_CONSTRAINTS t LEFT JOIN "
        "information_schema.KEY_COLUMN_USAGE k "
        "ON t.CONSTRAINT_SCHEMA = k.CONSTRAINT_SCHEMA "
        "AND t.TABLE_NAME = k.TABLE_NAME AND t.CONSTRAINT_NAME = k.CONSTRAINT_NAME "
        "WHERE t.CONSTRAINT_SCHEMA = :schema "
        "ORDER BY t.TABLE_NAME, t.CONSTRAINT_NAME, k.ORDINAL_POSITION"
    ):
        table = tables.get(row["table_name"])
        if table is None:
            continue
        name, kind = row["name"], row["kind"]
        if kind == "PRIMARY KEY":
            table["primary_key"]["columns"].append(row["column_name"])
        elif kind == "UNIQUE":
            table["unique_constraints"].setdefault(name, {"columns": []})[
                "columns"
            ].append(row["column_name"])
        elif kind == "FOREIGN KEY":
            action = actions[(row["table_name"], name)]
            spec = table["foreign_keys"].setdefault(
                name,
                {
                    "columns": [],
                    "referred_schema": (
                        "CURRENT_DATABASE"
                        if row["referred_schema"] == database
                        else row["referred_schema"]
                    ),
                    "referred_table": row["referred_table"],
                    "referred_columns": [],
                    "on_update": action["on_update"],
                    "on_delete": action["on_delete"],
                },
            )
            spec["columns"].append(row["column_name"])
            spec["referred_columns"].append(row["referred_column"])
        elif kind == "CHECK" and name not in table["check_constraints"]:
            table["check_constraints"].append(name)
    # STATISTICS 同样一列一行，按 SEQ_IN_INDEX 拼装索引，列、前缀与方向一一对应。
    for row in rows(
        "SELECT TABLE_NAME AS table_name, INDEX_NAME AS name, "
        "NON_UNIQUE AS non_unique, COLUMN_NAME AS column_name, "
        "SUB_PART AS prefix_length, COLLATION AS direction, INDEX_TYPE AS index_type, "
        "IS_VISIBLE AS visible, EXPRESSION AS expression "
        "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = :schema "
        "ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX"
    ):
        table = tables.get(row["table_name"])
        if table is None:
            continue
        spec = table["indexes"].setdefault(
            row["name"],
            {
                "columns": [],
                "unique": row["non_unique"] == 0,
                "index_type": row["index_type"],
                "visible": row["visible"] == "YES",
                "prefix_lengths": [],
                "directions": [],
                "expressions": [],
            },
        )
        for key, value in (
            ("columns", row["column_name"]),
            ("prefix_lengths", row["prefix_length"]),
            ("directions", row["direction"]),
            ("expressions", row["expression"]),
        ):
            spec[key].append(value)
    snapshot["routines"] = [
        dict(row)
        for row in rows(
            "SELECT ROUTINE_NAME AS name, ROUTINE_TYPE AS kind "
            "FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = :schema "
            "ORDER BY ROUTINE_NAME, ROUTINE_TYPE"
        )
    ]
    for group, name_column, schema_column in (
        ("triggers", "TRIGGER_NAME", "TRIGGER_SCHEMA"),
        ("events", "EVENT_NAME", "EVENT_SCHEMA"),
    ):
        snapshot[group] = [
            row["name"]
            for row in rows(
                f"SELECT {name_column} AS name FROM information_schema.{group.upper()} "
                f"WHERE {schema_column} = :schema ORDER BY {name_column}"
            )
        ]
    # 表元数据的行数可能是估计值；显式要求空数据时才 SELECT COUNT(*)，成本也更高。
    if require_empty_data:
        for name in TABLE_ORDER:
            if name in tables and tables[name]["kind"] == "BASE TABLE":
                qualified = f"{quote_identifier(database)}.{quote_identifier(name)}"
                count = connection.scalar(text(f"SELECT COUNT(*) FROM {qualified}"))
                if not isinstance(count, int) or count < 0:
                    raise CheckError(f"无法读取 {name} 的精确行数")
                snapshot["row_counts"][name] = count
    return snapshot


def emit(report, output_format):
    """Keep JSON stable for round-trip comparisons; print readable text otherwise."""
    if output_format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if report["status"] == "error":
        print(f"ERROR: {report['error']}")
        return
    snapshot = report["snapshot"]
    version = snapshot["alembic_version"]
    print(f"数据库：{snapshot['database']}；状态：{report['status']}")
    print(
        f"表/视图：{len(snapshot['tables'])}；例程：{len(snapshot['routines'])}；"
        f"触发器：{len(snapshot['triggers'])}；事件：{len(snapshot['events'])}"
    )
    print(
        f"alembic_version（单独报告）：存在={version['present']}；"
        f"类型={version['kind']}；版本行={version['versions']}"
    )
    for name, count in sorted(snapshot["row_counts"].items()):
        print(f"COUNT {name}: {count}")
    for item in report["differences"]:
        print(f"FAIL {item}")
    if not report["differences"]:
        print("PASS：与预期一致（未执行迁移或任何 DDL）")


def main(argv=None):
    """Return 0 for a match, 1 for a mismatch and 2 for configuration/read failures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect", choices=("base", "initial"), required=True)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--require-empty-data", action="store_true")
    args = parser.parse_args(argv)
    engine = None
    try:
        # 基线不可信就先失败，不能为了核对一个过期的期望值去连接数据库。
        baseline = load_baseline()
        # 驱动参数和查询不回显，连接错误也只输出受控信息，避免泄露凭据。
        engine = create_engine(
            database_url(),
            poolclass=NullPool,
            connect_args={
                "init_command": "SET time_zone = '+00:00'",
                "connect_timeout": 5,
            },
            echo=False,
            hide_parameters=True,
        )
        with engine.connect() as connection:
            snapshot = read_snapshot(connection, args.require_empty_data)
        issues, classes = compare_snapshot(
            baseline, snapshot, args.expect, args.require_empty_data
        )
    except (
        CheckError,
        SQLAlchemyError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        # 仅 CheckError 文本是本工具主动构造的安全说明；底层异常可能含连接信息。
        message = (
            str(exc)
            if isinstance(exc, CheckError)
            else "配置、连接或元数据读取失败；请检查配置及权限"
        )
        emit({"status": "error", "error": message}, args.format)
        return 2
    finally:
        if engine is not None:
            # 连接上下文退出后再释放 Engine；失败路径同样执行，资源责任不交给调用者。
            engine.dispose()
    emit(
        {
            "status": "mismatch" if issues else "ok",
            "expect": args.expect,
            "snapshot": snapshot,
            "index_classification": classes,
            "differences": issues,
        },
        args.format,
    )
    # 退出码区分“结构不匹配”(1) 与“无法完成核对”(2)，调用者不能都当成通过。
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
