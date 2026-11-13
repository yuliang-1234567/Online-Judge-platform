import pytest

from app.judge.comparator import compare_output


# 每组输入都直接使用 bytes，防止测试先解码或预处理而掩盖字节差异。
# 这些是内存比对的行为证据，不代表 Worker、容器或文件采集已经验收。
@pytest.mark.parametrize(
    ("expected", "actual", "matches"),
    [
        pytest.param(b"a", b"a", True, id="identical"),
        pytest.param(b"", b"", True, id="empty"),
        pytest.param(b"a\nb\n", b"a\r\nb\r\n", True, id="crlf"),
        pytest.param(b"a\r", b"a", True, id="trailing-cr"),
        pytest.param(b"a \t\r", b"a", True, id="trailing-ascii"),
        pytest.param(b"a \t\r\nb\t \r", b"a\nb", True, id="each-line-ascii"),
        pytest.param(b"a", b"a\n", True, id="no-final-newline"),
        pytest.param(b"a\n\n", b"a", True, id="trailing-empty-lines"),
        pytest.param(b"", b"\r\n", True, id="empty-vs-crlf"),
        pytest.param(b"", b"   ", True, id="empty-vs-spaces"),
        pytest.param(b"", b"\n\n", True, id="empty-vs-newlines"),
        pytest.param(b"", b"\t \r\t", True, id="empty-vs-ascii"),
        pytest.param(b"a\n \nb", b"a\n\nb", True, id="internal-space-line"),
        pytest.param(b"a\n\t\r\nb", b"a\n\nb", True, id="internal-tab-line"),
        pytest.param(b"\xe4\xb8\xad", b"\xe4\xb8\xad", True, id="same-utf8"),
        pytest.param(b"a", b"b", False, id="content"),
        pytest.param(b"a\rb", b"a\nb", False, id="internal-cr-vs-lf"),
        pytest.param(b"a\rb", b"ab", False, id="internal-cr-preserved"),
        pytest.param(b"a", b" a", False, id="leading-space"),
        pytest.param(b"a b", b"ab", False, id="internal-space"),
        pytest.param(b"a\tb", b"a b", False, id="internal-tab"),
        pytest.param(b"a\n\nb", b"a\nb", False, id="internal-empty-line"),
        pytest.param(b"a\n\n\nb", b"a\n\nb", False, id="extra-internal-empty"),
        pytest.param(b"a", b"\na", False, id="leading-empty-line"),
        pytest.param(b"a", b"a\xc2\xa0", False, id="trailing-nbsp"),
        pytest.param(b"a", b"a\x0b", False, id="trailing-vt"),
        pytest.param(b"a", b"a\x0c", False, id="trailing-ff"),
        pytest.param(b"a", b"\xef\xbb\xbfa", False, id="bom"),
        pytest.param(b"\xff", b"\xef\xbf\xbd", False, id="invalid-vs-replacement"),
        pytest.param(b"\xc3\xa9", b"e\xcc\x81", False, id="unicode-composition"),
        pytest.param(b"a\nb", b"a b", False, id="newline-vs-space"),
        pytest.param(b"a", b"a\xc2\xa0 \t", False, id="nbsp-before-ascii"),
    ],
)
def test_compare_output(expected: bytes, actual: bytes, matches: bool) -> None:
    # 两个方向都走公开接口，核对期望和实际应用相同规则。
    assert compare_output(expected, actual) is matches
    assert compare_output(actual, expected) is matches
