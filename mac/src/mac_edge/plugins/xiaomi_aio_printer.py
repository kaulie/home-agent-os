"""米家喷墨一体机：经本机 CUPS 打印 document Asset（lp，失败时 IPP 直连兜底）。

不切 SoftAP、不连打印机热点、不走米家云。仅使用家宽 Wi-Fi 上已配置的队列。
当 /usr/bin/lp 客户端异常（CUPS 服务器/GUI 打印仍正常）时，自动改用 ipptool
向本机 CUPS 服务器（ipp://127.0.0.1:631/printers/<队列>）提交 Print-Job。
"""

from __future__ import annotations

import getpass
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

log = logging.getLogger("mac_edge.xiaomi_aio_printer")

DEFAULT_QUEUE_SUBSTRING = "Mi_All_in_One_Inkjet"
DEFAULT_TIMEOUT_SEC = 60.0
# CUPS ColorModel for this Mi inkjet queue (lpoptions -l); Gray = 黑白/灰度。
DEFAULT_COLOR_MODEL = "Gray"
COLOR_MODEL_COLOR = "RGB"

_RunFn = Callable[..., subprocess.CompletedProcess[str]]

_MIME_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".txt": "text/plain",
}


class XiaomiPrinterError(Exception):
    pass


def cups_available() -> bool:
    """True when both lp and lpstat are on PATH."""
    return bool(shutil.which("lp") and shutil.which("lpstat"))


def _ipptool_bin() -> str:
    """System ipptool (direct IPP submit — works even when the lp CLI is broken)."""
    found = shutil.which("ipptool")
    if found:
        return found
    if Path("/usr/bin/ipptool").is_file():
        return "/usr/bin/ipptool"
    return ""


def _queue_name_prefix(line: str) -> str:
    """First ASCII CUPS destination-name token of an `lpstat -a` line.

    CUPS queue names use ASCII ([A-Za-z0-9_.@%+:-]); localized locale prints the
    status ("…正在接受请求…") right after the name with no separator, so stop at
    the first non-ASCII character / whitespace to keep a clean queue name.
    """
    m = re.match(r"[A-Za-z0-9_][A-Za-z0-9_.@%+:\-]*", line or "")
    return m.group(0) if m else ""


def _mime_for_path(path: Path) -> str:
    return _MIME_BY_SUFFIX.get((path.suffix or "").lower(), "application/octet-stream")


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


def parse_color_model(raw: Any = None) -> str:
    """Resolve CUPS ColorModel; default grayscale (黑白).

    Optional capability input ``color_mode`` / ``color``:
    bw|gray|grayscale|mono|black → Gray；color|rgb|colour → RGB。
    Env ``MAC_EDGE_PRINTER_COLOR_MODEL`` can force a CUPS value (e.g. Gray / RGB).
    """
    env = (os.environ.get("MAC_EDGE_PRINTER_COLOR_MODEL") or "").strip()
    if env:
        return env
    text = str(raw or "").strip().lower()
    if not text:
        return DEFAULT_COLOR_MODEL
    if text in (
        "bw",
        "b/w",
        "gray",
        "grey",
        "grayscale",
        "greyscale",
        "mono",
        "monochrome",
        "black",
        "黑白",
        "灰度",
    ):
        return DEFAULT_COLOR_MODEL
    if text in ("color", "colour", "rgb", "彩色", "彩打"):
        return COLOR_MODEL_COLOR
    raise XiaomiPrinterError(
        f"color_mode 无法识别：{raw!r}（可用 bw / color，默认黑白）"
    )


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
        # CUPS queue name may be followed directly by a localized status with no
        # separator (zh: "Queue_正在接受请求…"); take only the clean ASCII name.
        name = _queue_name_prefix(line)
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


def _cups_queue_uri(printer_name: str) -> str:
    """Local CUPS queue IPP URI (server/GUI printing path)."""
    return "ipp://127.0.0.1:631/printers/" + quote(str(printer_name or ""), safe="")


def _parse_ipp_job_id(stdout: str, printer_name: str) -> str:
    """Parse `job-id (integer) = N` / `/jobs/N` from ipptool -tv output."""
    text = (stdout or "").strip()
    m = re.search(r"job-id\s*\(integer\)\s*=\s*(\d+)", text)
    if m:
        return f"{printer_name}-{int(m.group(1))}"
    m2 = re.search(r"/jobs/(\d+)", text)
    if m2:
        return f"{printer_name}-{int(m2.group(1))}"
    raise XiaomiPrinterError(f"无法从 IPP 响应解析任务号：{text[:300] or '(空输出)'}")


def submit_print_ipp(
    path: Path,
    *,
    printer_name: str,
    copies: int = 1,
    color_model: str = DEFAULT_COLOR_MODEL,
    run_fn: _RunFn | None = None,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    mime_type: str | None = None,
) -> str:
    """Direct IPP Print-Job to the local CUPS server (bypasses the `lp` client).

    macOS GUI/Preview printing reaches the printer through the local CUPS server,
    so this path stays healthy even when `/usr/bin/lp` itself is broken
    (e.g. returns `No such file or directory` for every job).
    """
    tool = _ipptool_bin()
    if not tool:
        raise XiaomiPrinterError("本机未找到 ipptool，无法走 IPP 直连提交")
    uri = _cups_queue_uri(printer_name)
    fmt = (mime_type or "").strip() or _mime_for_path(path)
    user = getpass.getuser() or (os.environ.get("USER") or "")
    job_name = (path.name or "print.pdf").replace("\\", "_").replace('"', "_")
    doc = str(path.resolve())
    cm = (color_model or DEFAULT_COLOR_MODEL).strip() or DEFAULT_COLOR_MODEL
    # CUPS maps ColorModel + print-color-mode; monochrome ≈ Gray for this queue.
    print_color_mode = "monochrome" if cm != COLOR_MODEL_COLOR else "color"
    req_lines = [
        "{",
        "  VERSION 2.0",
        "  OPERATION Print-Job",
        "  GROUP operation",
        '  ATTR charset attributes-charset "utf-8"',
        '  ATTR language attributes-natural-language "en"',
        f'  ATTR uri printer-uri "{uri}"',
        f'  ATTR name requesting-user-name "{user}"',
        "  GROUP job",
        f'  ATTR name job-name "{job_name}"',
        f'  ATTR mimeMediaType document-format "{fmt}"',
        f"  ATTR integer copies {int(copies)}",
        f'  ATTR keyword print-color-mode "{print_color_mode}"',
        f'  ATTR keyword ColorModel "{cm}"',
        f"  FILE {doc}",
        "  STATUS successful-ok",
        "}",
        "",
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".ipp", delete=False, encoding="utf-8") as fh:
        fh.write("\n".join(req_lines))
        req_path = fh.name
    try:
        argv = [tool, "-tv", uri, req_path]
        log.info(
            "printer.print ipptool %s copies=%s color=%s path=%s mime=%s",
            printer_name,
            copies,
            cm,
            path,
            fmt,
        )
        proc = _run(argv, timeout_sec=timeout_sec, run_fn=run_fn)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
            raise XiaomiPrinterError(f"IPP 提交失败：{err}")
        return _parse_ipp_job_id(proc.stdout or "", printer_name)
    finally:
        try:
            Path(req_path).unlink(missing_ok=True)
        except OSError:
            pass


def submit_print(
    path: Path,
    *,
    printer_name: str,
    copies: int = 1,
    color_model: str = DEFAULT_COLOR_MODEL,
    run_fn: _RunFn | None = None,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    mime_type: str | None = None,
) -> str:
    """Submit a print job; return job_id.

    Tries `lp -d <queue> [-n copies] -o ColorModel=… <path>` first; when the lp
    CLI is missing or fails (macOS can leave /usr/bin/lp broken while the CUPS
    server / GUI printing still works), falls back to a direct IPP Print-Job to
    the local CUPS server. Default ColorModel is Gray (黑白).
    """
    cm = (color_model or DEFAULT_COLOR_MODEL).strip() or DEFAULT_COLOR_MODEL
    lp_bin = shutil.which("lp") if run_fn is None else "lp"
    lp_err = ""
    if lp_bin:
        argv = [lp_bin, "-d", printer_name]
        if copies != 1:
            argv.extend(["-n", str(copies)])
        argv.extend(["-o", f"ColorModel={cm}"])
        argv.append(str(path))
        log.info(
            "printer.print lp %s copies=%s color=%s path=%s",
            printer_name,
            copies,
            cm,
            path,
        )
        try:
            proc = _run(argv, timeout_sec=timeout_sec, run_fn=run_fn)
            if proc.returncode == 0:
                return parse_job_id(proc.stdout or "", printer_name)
            lp_err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        except XiaomiPrinterError as e:
            lp_err = str(e)
    else:
        lp_err = "未找到 lp 命令"
    try:
        return submit_print_ipp(
            path,
            printer_name=printer_name,
            copies=copies,
            color_model=cm,
            run_fn=run_fn,
            timeout_sec=timeout_sec,
            mime_type=mime_type,
        )
    except XiaomiPrinterError as e:
        raise XiaomiPrinterError(f"提交打印失败：{lp_err}（IPP 兜底：{e}）") from e


def print_from_params(
    params: dict[str, Any],
    *,
    asset: Any,
    run_fn: _RunFn | None = None,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
) -> tuple[str, dict[str, Any]]:
    """Capability entry: materialize document Asset → lp (default 黑白)."""
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
    color_raw = params.get("color_mode", params.get("color"))
    color_model = parse_color_model(color_raw)
    printer_name = resolve_printer_name(params, run_fn=run_fn)
    ensure_queue_accepting(printer_name, run_fn=run_fn)
    job_id = submit_print(
        path,
        printer_name=printer_name,
        copies=copies,
        color_model=color_model,
        run_fn=run_fn,
        timeout_sec=timeout_sec,
        mime_type=str(getattr(ref, "mime_type", None) or "") or None,
    )
    tone = "黑白" if color_model != COLOR_MODEL_COLOR else "彩色"
    status_text = f"已提交打印到 {printer_name}（任务 {job_id}，{copies} 份，{tone}）"
    outputs = {
        "status_text": status_text,
        "job_id": job_id,
        "printer_name": printer_name,
        "color_mode": "color" if color_model == COLOR_MODEL_COLOR else "bw",
    }
    return f"printer.print ok job_id={job_id}", outputs