"""printer.print — CapAsset document → CUPS lp/lpstat."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from mac_edge.asset.types import AssetError, AssetRef
from mac_edge.plugins.xiaomi_aio_printer import (
    XiaomiPrinterError,
    ensure_queue_accepting,
    list_cups_queues,
    parse_color_model,
    parse_job_id,
    print_from_params,
    resolve_printer_name,
)
from mac_edge.services import default_services

QUEUE = "Mi_All_in_One_Inkjet_Printer__1EB808_"


def _fake_run_factory(
    queues: list[str],
    *,
    lp_stdout: str = "",
    lp_code: int = 0,
    calls: list[list[str]] | None = None,
):
    def _run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if calls is not None:
            calls.append(list(argv))
        cmd = argv[0] if argv else ""
        name = Path(cmd).name
        if name == "lpstat" or (len(argv) > 1 and argv[1] == "-a" and "lpstat" in cmd):
            if "-a" in argv:
                out = "\n".join(
                    f"{q} accepting requests since Sun Jan 1 00:00:00 2020" for q in queues
                )
                return subprocess.CompletedProcess(argv, 0, out, "")
        if name == "lp":
            return subprocess.CompletedProcess(
                argv, lp_code, lp_stdout, "" if lp_code == 0 else "lp failed"
            )
        return subprocess.CompletedProcess(argv, 1, "", f"unexpected: {argv}")

    return _run


class ParseColorModelTests(unittest.TestCase):
    def test_default_bw(self) -> None:
        with patch.dict(os.environ, {"MAC_EDGE_PRINTER_COLOR_MODEL": ""}, clear=False):
            self.assertEqual(parse_color_model(None), "Gray")
            self.assertEqual(parse_color_model(""), "Gray")

    def test_color_override(self) -> None:
        with patch.dict(os.environ, {"MAC_EDGE_PRINTER_COLOR_MODEL": ""}, clear=False):
            self.assertEqual(parse_color_model("color"), "RGB")
            self.assertEqual(parse_color_model("彩色"), "RGB")

    def test_env_wins(self) -> None:
        with patch.dict(os.environ, {"MAC_EDGE_PRINTER_COLOR_MODEL": "RGB"}, clear=False):
            self.assertEqual(parse_color_model("bw"), "RGB")


class ParseJobIdTests(unittest.TestCase):
    def test_standard_lp_stdout(self) -> None:
        out = f"request id is {QUEUE}-42 (1 file(s))"
        self.assertEqual(parse_job_id(out, QUEUE), f"{QUEUE}-42")


class ResolvePrinterTests(unittest.TestCase):
    def test_param_wins(self) -> None:
        run = _fake_run_factory([QUEUE])
        name = resolve_printer_name({"printer_name": "Other_Queue"}, run_fn=run)
        self.assertEqual(name, "Other_Queue")

    def test_env_then_match(self) -> None:
        run = _fake_run_factory([QUEUE, "Another"])
        with patch.dict(os.environ, {"MAC_EDGE_PRINTER_NAME": "Env_Queue"}, clear=False):
            self.assertEqual(resolve_printer_name({}, run_fn=run), "Env_Queue")
        with patch.dict(os.environ, {"MAC_EDGE_PRINTER_NAME": ""}, clear=False):
            self.assertEqual(resolve_printer_name({}, run_fn=run), QUEUE)

    def test_no_match_chinese(self) -> None:
        run = _fake_run_factory(["Some_Other_Printer"])
        with patch.dict(os.environ, {"MAC_EDGE_PRINTER_NAME": ""}, clear=False):
            with self.assertRaises(XiaomiPrinterError) as ctx:
                resolve_printer_name({}, run_fn=run)
        msg = str(ctx.exception)
        self.assertIn("未找到", msg)
        self.assertNotIn("SoftAP", msg)


class EnsureQueueTests(unittest.TestCase):
    def test_missing_queue_chinese(self) -> None:
        run = _fake_run_factory(["Other"])
        with self.assertRaises(XiaomiPrinterError) as ctx:
            ensure_queue_accepting(QUEUE, run_fn=run)
        msg = str(ctx.exception)
        self.assertIn("不可用", msg)
        self.assertNotIn("SoftAP", msg)

    def test_list_cups_queues_strips_localized_status(self) -> None:
        # zh locale prints "Queue_正在接受请求…" with no separator; names must stay clean.
        def _run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            out = (
                f"{QUEUE}正在接受请求，时间始于五  9/ 4 07:33:29 2026\n"
                "HP_Some_Queue_正在接受请求，时间始于五  9/ 4 07:33:29 2026\n"
            )
            return subprocess.CompletedProcess(argv, 0, out, "")

        queues = list_cups_queues(run_fn=_run)
        self.assertIn(QUEUE, queues)
        self.assertIn("HP_Some_Queue_", queues)
        self.assertTrue(all("正在接受" not in q for q in queues))


class PrintFromParamsTests(unittest.TestCase):
    def test_missing_asset_ref(self) -> None:
        asset = MagicMock()
        asset.require_ref.side_effect = AssetError(
            "missing or invalid asset_ref (AssetRef required)"
        )
        with self.assertRaises(XiaomiPrinterError) as ctx:
            print_from_params({}, asset=asset)
        self.assertIn("asset_ref", str(ctx.exception))

    def test_non_document(self) -> None:
        asset = MagicMock()
        asset.require_ref.return_value = AssetRef(asset_id="a1", type="image")
        with self.assertRaises(XiaomiPrinterError) as ctx:
            print_from_params(
                {"asset_ref": {"asset_id": "a1", "type": "image"}}, asset=asset
            )
        self.assertIn("document", str(ctx.exception))
        asset.materialize_file.assert_not_called()

    def test_happy_path(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            fh.write(b"%PDF-1.4 fake")
            path = Path(fh.name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))

        asset = MagicMock()
        asset.require_ref.return_value = AssetRef(
            asset_id="a1", type="document", mime_type="application/pdf"
        )
        asset.materialize_file.return_value = path

        lp_out = f"request id is {QUEUE}-7 (1 file(s))"
        calls: list[list[str]] = []
        run = _fake_run_factory([QUEUE], lp_stdout=lp_out, calls=calls)
        with patch.dict(os.environ, {"MAC_EDGE_PRINTER_NAME": "", "MAC_EDGE_PRINTER_COLOR_MODEL": ""}, clear=False):
            msg, outputs = print_from_params(
                {"asset_ref": {"asset_id": "a1", "type": "document"}, "copies": 2},
                asset=asset,
                run_fn=run,
            )
        self.assertIn("printer.print ok", msg)
        self.assertEqual(outputs["job_id"], f"{QUEUE}-7")
        self.assertEqual(outputs["printer_name"], QUEUE)
        self.assertEqual(outputs["color_mode"], "bw")
        self.assertIn("黑白", outputs["status_text"])
        self.assertNotIn("SoftAP", outputs["status_text"])
        lp = next(c for c in calls if Path(c[0]).name == "lp")
        self.assertIn("-o", lp)
        self.assertIn("ColorModel=Gray", lp)

    def test_color_mode_color(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            fh.write(b"%PDF-1.4 fake")
            path = Path(fh.name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))

        asset = MagicMock()
        asset.require_ref.return_value = AssetRef(
            asset_id="a1", type="document", mime_type="application/pdf"
        )
        asset.materialize_file.return_value = path

        lp_out = f"request id is {QUEUE}-8 (1 file(s))"
        calls: list[list[str]] = []
        run = _fake_run_factory([QUEUE], lp_stdout=lp_out, calls=calls)
        with patch.dict(os.environ, {"MAC_EDGE_PRINTER_NAME": QUEUE, "MAC_EDGE_PRINTER_COLOR_MODEL": ""}, clear=False):
            _, outputs = print_from_params(
                {
                    "asset_ref": {"asset_id": "a1", "type": "document"},
                    "color_mode": "color",
                },
                asset=asset,
                run_fn=run,
            )
        self.assertEqual(outputs["color_mode"], "color")
        self.assertIn("彩色", outputs["status_text"])
        lp = next(c for c in calls if Path(c[0]).name == "lp")
        self.assertIn("ColorModel=RGB", lp)

    def test_lp_failure_chinese(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            fh.write(b"%PDF")
            path = Path(fh.name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))

        asset = MagicMock()
        asset.require_ref.return_value = AssetRef(asset_id="a1", type="document")
        asset.materialize_file.return_value = path
        run = _fake_run_factory([QUEUE], lp_code=1)
        with patch.dict(os.environ, {"MAC_EDGE_PRINTER_NAME": QUEUE}, clear=False):
            with self.assertRaises(XiaomiPrinterError) as ctx:
                print_from_params(
                    {"asset_ref": {"asset_id": "a1", "type": "document"}},
                    asset=asset,
                    run_fn=run,
                )
        self.assertIn("提交打印失败", str(ctx.exception))
        self.assertNotIn("SoftAP", str(ctx.exception))

    def test_ipp_fallback_when_lp_broken(self) -> None:
        # macOS can leave the `lp` CLI broken while the CUPS server / GUI printing
        # still works; print_from_params must fall back to a direct IPP Print-Job.
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            fh.write(b"%PDF")
            path = Path(fh.name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))

        calls: list[list[str]] = []
        doc_texts: list[str] = []

        def _run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append(list(argv))
            name = Path(argv[0]).name
            if name == "lpstat":
                return subprocess.CompletedProcess(
                    argv, 0, f"{QUEUE} accepting requests since Sun Jan 1 00:00:00 2020\n", ""
                )
            if name == "lp":
                return subprocess.CompletedProcess(argv, 1, "", "lp: broken")
            if name == "ipptool":
                req = Path(argv[-1])
                if req.is_file():
                    doc_texts.append(req.read_text(encoding="utf-8"))
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    "status-code = successful-ok\n"
                    "job-id (integer) = 77\n"
                    "job-uri (uri) = ipp://localhost/jobs/77\n",
                    "",
                )
            return subprocess.CompletedProcess(argv, 1, "", f"unexpected: {argv}")

        asset = MagicMock()
        asset.require_ref.return_value = AssetRef(
            asset_id="a1", type="document", mime_type="application/pdf"
        )
        asset.materialize_file.return_value = path
        with patch.dict(os.environ, {"MAC_EDGE_PRINTER_NAME": QUEUE}, clear=False):
            msg, outputs = print_from_params(
                {"asset_ref": {"asset_id": "a1", "type": "document"}},
                asset=asset,
                run_fn=_run,
            )
        self.assertIn("printer.print ok", msg)
        self.assertEqual(outputs["job_id"], f"{QUEUE}-77")
        self.assertEqual(outputs["printer_name"], QUEUE)
        ipp = next(c for c in calls if Path(c[0]).name == "ipptool")
        self.assertIn("-tv", ipp)
        self.assertNotIn("-f", ipp)
        self.assertIn(f"ipp://127.0.0.1:631/printers/{QUEUE}", ipp)
        self.assertTrue(doc_texts)
        req_text = doc_texts[0]
        self.assertIn("OPERATION Print-Job", req_text)
        self.assertIn(f"FILE {path.resolve()}", req_text)
        self.assertIn('ATTR keyword print-color-mode "monochrome"', req_text)
        self.assertIn('ATTR keyword ColorModel "Gray"', req_text)


class AdvertisePrinterTests(unittest.TestCase):
    def test_laptop_advertises_when_cups_available(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "laptop",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_GOPRO_SSID": "",
            "MAC_EDGE_ADVERTISE_CAST": "0",
            "MAC_EDGE_HISENSE_USERNAME": "",
            "MAC_EDGE_HISENSE_PASSWORD": "",
            "MAC_EDGE_XIAOMI_USERNAME": "",
            "MAC_EDGE_XIAOMI_PASSWORD": "",
            "MAC_EDGE_XIAOMI_TV": "",
            "MAC_EDGE_DISPLAY_BACKEND": "",
            "MAC_EDGE_XIAOMI_TV_HOST": "",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch(
                "mac_edge.plugins.xiaomi_aio_printer.cups_available",
                return_value=True,
            ):
                services = default_services()
        ids = [s["service_id"] for s in services]
        self.assertIn("local.printer", ids)
        printer = next(s for s in services if s["service_id"] == "local.printer")
        caps = [c["capability_id"] for c in printer["capabilities"]]
        self.assertIn("printer.print", caps)

    def test_skips_when_cups_missing(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "laptop",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_ADVERTISE_CAST": "0",
            "MAC_EDGE_GOPRO_SSID": "",
            "MAC_EDGE_HISENSE_USERNAME": "",
            "MAC_EDGE_HISENSE_PASSWORD": "",
            "MAC_EDGE_XIAOMI_USERNAME": "",
            "MAC_EDGE_XIAOMI_PASSWORD": "",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch(
                "mac_edge.plugins.xiaomi_aio_printer.cups_available",
                return_value=False,
            ):
                ids = [s["service_id"] for s in default_services()]
        self.assertNotIn("local.printer", ids)


if __name__ == "__main__":
    unittest.main()
