"""执行器内部的语言白名单；只提供不可变参数，不读取环境或解析镜像。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageSpec:
    """运行参数是完整 argv；镜像配置键由后续 Runner 读取并核验身份。"""

    name: str
    source_filename: str
    image_config_key: str
    compile_argv: tuple[str, ...] | None
    run_argv: tuple[str, ...]


_PYTHON = LanguageSpec(
    name="python",
    source_filename="main.py",
    image_config_key="JUDGE_IMAGE_PYTHON",
    compile_argv=None,
    run_argv=("/usr/local/bin/python3", "-B", "-u", "/work/main.py"),
)


def get_language(name: str) -> LanguageSpec:
    """仅接受精确的 python；不修剪空白、不改大小写，其他值抛出 ValueError。"""
    if name != "python":
        raise ValueError("Unsupported judge language")
    return _PYTHON
