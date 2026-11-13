def compare_output(expected: bytes, actual: bytes) -> bool:
    """按设计 §7.3.1 比较输出，规整后相同返回 True，否则返回 False。

    expected 是 UTF-8 编码的期望输出，actual 是程序原始输出字节。
    仅统一 CRLF、移除指定 ASCII 行尾空白及末尾空行；其他字节保留。
    不解码、不做 Unicode 归一化，不读写文件或访问外部服务。
    """

    def normalize(output: bytes) -> list[bytes]:
        """只按 LF 分行，保留行中裸 CR 与内部空行。"""
        # 显式列出可忽略的行尾字节，避免默认空白集合扩大判题规则。
        lines = [
            line.rstrip(b" \t\r")
            for line in output.replace(b"\r\n", b"\n").split(b"\n")
        ]
        # 逐行处理后才删除尾部空行；中间的空行仍参与比较。
        while lines and lines[-1] == b"":
            lines.pop()
        return lines

    return normalize(expected) == normalize(actual)
