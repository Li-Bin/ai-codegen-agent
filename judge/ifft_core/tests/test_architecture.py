# -*- coding: utf-8 -*-
"""
tests/test_architecture.py — 架構約束測試（T-10）

【為什麼】協定 D-4：core 層禁止 import 任何 UI／繪圖套件。
    這不是程式碼潔癖——core 一旦 import streamlit，就再也不能在
    無 GUI 的 CI 環境單獨測試，運算與呈現從此焊死在一起。
    架構約束若只寫在文件裡，第一次趕工就會被違反；寫成測試，
    違反的當下就紅燈。用 ast 靜態掃描而非實際 import，所以就算
    core 爛到 import 就炸，這條測試照樣能指出違規點。
"""
import ast
from pathlib import Path

import ifft_sim

BANNED = {
    "streamlit", "PyQt5", "PyQt6", "PySide2", "PySide6",
    "matplotlib", "plotly", "tkinter", "bokeh", "altair",
}


def _imports_of(path: Path) -> set[str]:
    """回傳檔案內全部 import 的「頂層模組名」（a.b.c 只取 a）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:  # 相對匯入(from .x)屬套件內部，放行
                found.add(node.module.split(".")[0])
    return found


def test_T10_core_has_no_ui_or_plotting_imports():
    """
    【測什麼】掃描 ifft_sim/core/ 下所有 .py，任何檔案的 import
        頂層模組名與禁用清單交集必須為空。失敗訊息指出檔案與
        違規模組名。
    """
    core_dir = Path(ifft_sim.__file__).parent / "core"
    assert core_dir.is_dir(), f"找不到 core 目錄: {core_dir}"
    violations = {}
    for py in sorted(core_dir.rglob("*.py")):
        hit = _imports_of(py) & BANNED
        if hit:
            violations[str(py)] = sorted(hit)
    assert not violations, (
        f"core 層 import 了 UI/繪圖套件，違反協定 D-4: {violations}")
