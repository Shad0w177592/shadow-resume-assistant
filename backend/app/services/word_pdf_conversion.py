from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

_POWERSHELL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$source = [IO.Path]::GetFullPath($env:SHADOW_WORD_SOURCE)
$target = [IO.Path]::GetFullPath($env:SHADOW_PDF_TARGET)
$word = $null
$document = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $document = $word.Documents.Open($source, $false, $true)
    $document.ExportAsFixedFormat($target, 17)
}
finally {
    if ($null -ne $document) { $document.Close(0) }
    if ($null -ne $word) { $word.Quit() }
}
""".strip()


def word_to_pdf(
    source: Path,
    target: Path,
    runner: Callable[..., Any] = subprocess.run,
) -> None:
    source = source.resolve()
    target = target.resolve()
    if source.suffix.lower() != ".docx" or not source.is_file():
        raise ValueError("Word 转 PDF 的源文件无效")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        _POWERSHELL_SCRIPT,
    ]
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={
                **os.environ,
                "SHADOW_WORD_SOURCE": str(source),
                "SHADOW_PDF_TARGET": str(target),
            },
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(
            "无法调用 Microsoft Word 生成同版 PDF，请确认电脑已安装桌面版 Word"
        ) from error
    if completed.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        suffix = f"：{detail[-300:]}" if detail else ""
        raise RuntimeError(
            "无法通过 Microsoft Word 生成同版 PDF，请确认电脑已安装并可正常打开 Word"
            + suffix
        )
