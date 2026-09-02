"""米家喷墨一体机：经本机 CUPS（lp/lpstat）打印 document Asset。

不切 SoftAP、不连打印机热点、不走米家云。仅使用家宽 Wi-Fi 上已配置的队列。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("mac_edge.xiaomi_aio_printer")

DEFAULT_QUEUE_SUBSTRING = "Mi_All_in_One_Inkjet"
DEFAULT_TIMEOUT_SEC = 60.0

_RunFn = Callable[..., subprocess.CompletedProcess[str]]


class XiaomiPrinterError(Exception):
    pass


def cups_available() -> bool:
    """True when both lp and lpstat are on PATH."""
    return bool(shutil.which("lp") and shutil.which("lpstat"))


def _run(
    argv: list[str],
    *,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    run_fn: _RunFn | None = None,
) -> subprocess.CompletedProcess[str]:
    fn = run_fn or subprocess.run
    try:
        return fn(
            argv,
            capture_output=True,
            text=True,
            timeout=max(5.0, float(timeout_sec)),
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise XiaomiPrinterError(f"打印命令超时（>{int(timeout_sec)}s）：{' '.join(argv[:2])}") from e
    except OSError as e:
        raise XiaomiPrinterError(f"无法启动打印命令：{e}") from e


def _parse_copies(raw: Any) -> int:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return 1
    try:
        n = int(raw)
    except (TypeError, ValueError) as e:
        raise XiaomiPrinterError(f"copies 必须是正整数，收到：{raw!r}") from e
    if n < 1:
        raise XiaomiPrinterError(f"copies 必须是正整数，收到：{n}")
    if n > 99:
        raise XiaomiPrinterError(f"copies 过大（最多 99）：{n}")
    return n


def list_cups_queues(*, run_fn: _RunFn | None = None) -> list[str]:
    """Return accepting queue names from `lpstat -a`."""
    lpstat = shutil.which("lpstat") or "lpstat"
    proc = _run([lpstat, "-a"], run_fn=run_fn)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise XiaomiPrinterError(f"无法查询 CUPS 队列：{err}")
    names: list[str] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        # "QueueName accepting requests since ..."
        name = line.split(None, 1)[0].strip()
        if name:
            names.append(name)
    return names


def resolve_printer_name(
    params: dict[str, Any] | None = None,
    *,
    run_fn: _RunFn | None = None,
) -> str:
    """入参 printer_name → MAC_EDGE_PRINTER_NAME → 匹配 Mi_All_in_One_Inkjet*。"""
    params = params or {}
    explicit = str(params.get("printer_name") or "").strip()
    if explicit:
        return explicit
    env_name = (os.environ.get("MAC_EDGE_PRINTER_NAME") or "").strip()
    if env_name:
        return env_name
    queues = list_cups_queues(run_fn=run_fn)
    matches = [q for q in queues if DEFAULT_QUEUE_SUBSTRING in q]
    if not matches:
        raise XiaomiPrinterError(
            "未找到米家喷墨一体机 CUPS 队列"
            f"（名含 {DEFAULT_QUEUE_SUBSTRING}）。"
            "请确认本机已在家宽 Wi-Fi 下配置该打印机，或设置 MAC_EDGE_PRINTER_NAME。"
        )
    if len(matches) > 1:
        log.info("multiple Mi inkjet queues %s; using first", matches)
    return matches[0]


def ensure_queue_accepting(printer_name: str, *, run_fn: _RunFn | None = None) -> None:
    """Fail in Chinese if the named queue is missing or not accepting."""
    queues = list_cups_queues(run_fn=run_fn)
    if printer_name not in queues:
        raise XiaomiPrinterError(
            f"CUPS 队列不可用或不存在：{printer_name}。"
            "请确认打印机已在家宽 Wi-Fi 上配置且队列接受任务。"
        )


def parse_job_id(stdout: str, printer_name: str) -> str:
    """Parse `request id is Queue-123` from lp stdout."""
    text = (stdout or "").strip()
    m = re.search(r"request id is\s+(\S+)", text, re.IGNORECASE)
    if m:
        return m.group(1).rstrip(".")
    # Fallback: QueueName-N
    escaped = re.escape(printer_name)
    m2 = re.search(rf"({escaped}-\d+)", text)
    if m2:
        return m2.group(1)
    raise XiaomiPrinterError(f"无法解析打印任务号：{text or '(空输出)'}")


def submit_print(
    path: Path,
    *,
    printer_name: str,
    copies: int = 1,
    run_fn: _RunFn | None = None,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
) -> str:
    """Run `lp -d <queue> [-n copies] <path>`; return job_id."""
    lp_bin = shutil.which("lp")
    if lp_bin is None and run_fn is None:
        raise XiaomiPrinterError("本机未找到 lp 命令，无法打印")
    lp = lp_bin or "lp"
    argv = [lp, "-d", printer_name]
    if copies != 1:
        argv.extend(["-n", str(copies)])
    argv.append(str(path))
    log.info("printer.print lp %s copies=%s path=%s", printer_name, copies, path)
    proc = _run(argv, timeout_sec=timeout_sec, run_fn=run_fn)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise XiaomiPrinterError(f"提交打印失败：{err}")
    return parse_job_id(proc.stdout or "", printer_name)


def print_from_params(
    params: dict[str, Any],
    *,
    asset: Any,
    run_fn: _RunFn | None = None,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
) -> tuple[str, dict[str, Any]]:
    """Capability entry: materialize document Asset → lp."""
    from mac_edge.asset.types import AssetError

    if asset is None or not hasattr(asset, "require_ref") or not hasattr(asset, "materialize_file"):
        raise XiaomiPrinterError("printer.print 需要 CapAsset（Runtime SDK）")

    try:
        ref = asset.require_ref(params, "asset_ref")
    except AssetError as e:
        raise XiaomiPrinterError(f"缺少或无效的 asset_ref：{e}") from e

    if str(ref.type or "").strip() != "document":
        raise XiaomiPrinterError(
            f"printer.print 只接受 type=document 的 Asset，收到 type={ref.type!r}"
        )

    try:
        local_path = asset.materialize_file(ref)
    except AssetError as e:
        raise XiaomiPrinterError(f"无法物化待打印文件：{e}") from e

    path = Path(local_path)
    if not path.is_file():
        raise XiaomiPrinterError(f"待打印文件不存在：{path}")

    copies = _parse_copies(params.get("copies"))
    printer_name = resolve_printer_name(params, run_fn=run_fn)
    ensure_queue_accepting(printer_name, run_fn=run_fn)
    job_id = submit_print(
        path,
        printer_name=printer_name,
        copies=copies,
        run_fn=run_fn,
        timeout_sec=timeout_sec,
    )
    status_text = f"已提交打印到 {printer_name}（任务 {job_id}，{copies} 份）"
    outputs = {
        "status_text": status_text,
        "job_id": job_id,
        "printer_name": printer_name,
    }
    return f"printer.print ok job_id={job_id}", outputs
