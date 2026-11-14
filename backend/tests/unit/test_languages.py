from dataclasses import FrozenInstanceError
from operator import setitem

import pytest

from app.judge.languages import LanguageSpec, get_language


def test_python_language_contract() -> None:
    spec = get_language("python")
    assert isinstance(spec, LanguageSpec)
    assert spec.name == "python"
    assert spec.source_filename == "main.py"
    assert spec.image_config_key == "JUDGE_IMAGE_PYTHON"
    assert spec.compile_argv is None
    assert spec.run_argv == (
        "/usr/local/bin/python3",
        "-B",
        "-u",
        "/work/main.py",
    )


@pytest.mark.parametrize(
    "name",
    ["Python", "PYTHON", " python", "python ", "python\n", "cpp", "", "python3"],
)
def test_language_lookup_rejects_unsupported_strings(name: str) -> None:
    with pytest.raises(ValueError, match="Unsupported judge language"):
        get_language(name)


def test_language_spec_and_argv_are_immutable() -> None:
    spec = get_language("python")
    with pytest.raises(FrozenInstanceError):
        spec.name = "cpp"
    # 冻结对象之外，argv 自身也必须不可变，不能通过嵌套可变值污染后续执行。
    with pytest.raises(TypeError):
        setitem(spec.run_argv, 0, "sh")
    assert get_language("python").name == "python"
    assert get_language("python").run_argv[0] == "/usr/local/bin/python3"


def test_lookup_keeps_image_resolution_outside_language_table(monkeypatch) -> None:
    monkeypatch.setenv("JUDGE_IMAGE_PYTHON", "unit-only:replacement")
    # 返回配置键而非环境值；本节不加载 Settings，也不把 tag 当已确认的镜像 ID。
    assert get_language("python").image_config_key == "JUDGE_IMAGE_PYTHON"
