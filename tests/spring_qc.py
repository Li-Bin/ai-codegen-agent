"""spring_qc 金樣（pytest 版）：格式、邊界、良率逐條驗。
受測檔路徑由環境變數 TARGET 注入（run_gold 會設好）。"""
import os
import random
import subprocess
import sys


def _out():
    r = subprocess.run(
        [sys.executable, os.environ["TARGET"]],
        capture_output=True, text=True, timeout=10,
    )
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def _expected():
    random.seed(42)
    vals = [round(random.uniform(9.0, 11.0), 2) for _ in range(7)]
    exp = [9.20 <= v <= 10.80 for v in vals]
    return vals, exp


def test_line_count():
    n = len(_out())
    assert n == 8, f"預期 8 行，實得 {n} 行"


def test_items():
    out = _out()
    vals, exp = _expected()
    for i in range(7):
        want = f"item{i+1}: {vals[i]:.2f} {'PASS' if exp[i] else 'FAIL'}"
        assert out[i] == want, f"第 {i+1} 行預期「{want}」，實得「{out[i]}」"


def test_yield():
    out = _out()
    _, exp = _expected()
    rate = 100 * sum(exp) / 7
    assert out[7] == f"yield: {rate:.1f}%", f"末行預期「yield: {rate:.1f}%」，實得「{out[7]}」"