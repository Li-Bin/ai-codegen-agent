#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_qualification.py — IFFT 合格性測試執行器（給 AI agent 的自我修正迴圈）

用法：
    python run_qualification.py              # 跑全部，人讀 + 機讀輸出
    python run_qualification.py -k T06      # 透傳 pytest 參數，只跑 T-06
    python run_qualification.py --json-out result.json   # 另存 JSON

機讀輸出格式（stdout 最後一段）：
    === IFFT_QUALIFICATION_RESULT ===
    { "verdict": "PASS" | "FAIL", ... }
    === END ===
離開碼：PASS=0，FAIL=1。

給 agent 的迴圈規則（也寫在 JSON 的 rules 欄位裡）：
    1. verdict == FAIL 時，讀 failures[].message，修改「實作」後重跑。
    2. 禁止修改 tests/ 目錄與本檔的任何內容——測試是判準，
       實作過不了判準時修的是實作（協定 §5.4）。
    3. 禁止修改容差常數或 T-06 的參數。
    4. 若認定某條測試本身有誤，停止並回報衝突，由需求端裁決。
"""
import argparse
import json
import re
import sys
from pathlib import Path

# 讓 ifft_sim 與 tests 以「專案根目錄」為基準可匯入，
# 不受使用者從哪個目錄執行影響。
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

_TID = re.compile(r"T(\d{2})([a-z]?)")


def _tid_of(nodeid: str) -> str:
    m = _TID.search(nodeid)
    return f"T-{m.group(1)}{m.group(2)}" if m else "GEN"


class _Collector:
    """pytest plugin：收集每個測試案例的結果與失敗訊息。"""

    def __init__(self) -> None:
        self.cases: list[dict] = []
        self.collection_errors: list[str] = []

    def pytest_runtest_logreport(self, report):
        if report.when == "call":
            self.cases.append({
                "id": _tid_of(report.nodeid),
                "nodeid": report.nodeid,
                "outcome": report.outcome,  # passed / failed / skipped
                "message": str(report.longrepr)[:2000] if report.failed else "",
            })
        elif report.when in ("setup", "teardown") and report.failed:
            # fixture / import 階段炸掉也要能回報
            self.cases.append({
                "id": _tid_of(report.nodeid),
                "nodeid": report.nodeid,
                "outcome": "error",
                "message": str(report.longrepr)[:2000],
            })
        elif report.when == "setup" and report.skipped:
            self.cases.append({
                "id": _tid_of(report.nodeid),
                "nodeid": report.nodeid,
                "outcome": "skipped",
                "message": "",
            })

    def pytest_collectreport(self, report):
        if report.failed:
            self.collection_errors.append(str(report.longrepr)[:2000])


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--json-out", default=None)
    args, passthrough = parser.parse_known_args()

    collector = _Collector()
    rc = pytest.main(
        [str(ROOT / "tests"), "-q", "-p", "no:cacheprovider", *passthrough],
        plugins=[collector],
    )

    # 依 T-ID 彙整：任一案例 failed/error 則該 ID fail
    by_id: dict[str, dict] = {}
    for c in collector.cases:
        slot = by_id.setdefault(c["id"], {"outcome": "passed", "cases": 0, "failed_cases": 0})
        slot["cases"] += 1
        if c["outcome"] in ("failed", "error"):
            slot["outcome"] = "failed"
            slot["failed_cases"] += 1

    failures = [c for c in collector.cases if c["outcome"] in ("failed", "error")]
    n_pass = sum(1 for c in collector.cases if c["outcome"] == "passed")

    ok = (rc == 0 and not collector.collection_errors and len(collector.cases) > 0)
    if len(collector.cases) == 0 and not collector.collection_errors:
        collector.collection_errors.append(
            "沒有收集到任何測試——tests/ 目錄不在專案根旁，或 pytest 參數過濾掉了全部")

    result = {
        "verdict": "PASS" if ok else "FAIL",
        "summary": {
            "passed_cases": n_pass,
            "failed_cases": len(failures),
            "collection_errors": len(collector.collection_errors),
            "pytest_exit_code": rc,
        },
        "tests": by_id,
        "failures": failures,
        "collection_error_details": collector.collection_errors,
        "rules": [
            "只准修改實作（ifft_sim/），禁止修改 tests/、容差常數、T-06 參數與本執行器",
            "collection_errors > 0 時優先處理：通常是模組缺失或 API 簽章不符協定 §3",
            "修復順序建議：import/collection 錯 → T-01/T-02 → T-07/T-09 → T-03/T-08 → T-05/T-06 → 其餘",
            "若認定測試本身有誤：停止，回報衝突，不得自行改測試",
        ],
    }

    blob = json.dumps(result, ensure_ascii=False, indent=2)
    print("\n=== IFFT_QUALIFICATION_RESULT ===")
    print(blob)
    print("=== END ===")
    if args.json_out:
        Path(args.json_out).write_text(blob, encoding="utf-8")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
