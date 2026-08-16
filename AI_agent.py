# -*- coding: utf-8 -*-
"""AI code-gen agent — v2：新增「專案模式」。

兩種模式，依 judge/{task}/ 目錄是否存在自動切換：

【單檔模式】（原 V1 行為，完全保留）
    生成一個 .py → 直接執行 smoke → pytest 跑 tests/{task}.py（TARGET 注入）

【專案模式】（新增）
    生成多檔專案（=== FILE: path === 區塊協定）→ 寫入 generated/proj_*/
    → 複製 judge/{task}/ 的判準資產（tests/ + run_qualification.py）進去
    → 執行判準，解析機讀 JSON（verdict / failures）→ 失敗回授修正

設計要點（為什麼這樣改）：
  * 判準測的是「套件」（import ifft_sim.core.*），不是單一腳本，
    所以 TARGET 環境變數的合約在專案模式不適用。
  * 專案模式跳過 smoke：套件模組含相對匯入，直接執行必炸；
    import 層級的錯誤由判準的 collection error 回報，訊息更準。
  * 錯誤簽名改從 JSON 的失敗清單計算。沿用「取最後一行」的舊邏輯
    會讓每次失敗的簽名都是 '=== END ==='，第二次失敗就誤判震盪。
  * 判準資產「後」複製、覆蓋同名路徑，且模型輸出若指向 tests/ 等
    判準路徑一律拒寫——機械性擋掉「改測試來過關」。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 注意：LLM SDK（google-genai、dotenv）延遲到 main() 才 import——
# 判準管線（split_files / write_project / run_judge）不依賴 SDK，
# 沒裝 SDK 的環境也能單獨測試 harness。

BASE = Path(__file__).parent

# ---------------------------------------------------------------------------
# 多檔輸出協定
# ---------------------------------------------------------------------------
FILE_HEADER_RE = re.compile(r"^===\s*FILE:\s*(.+?)\s*===\s*$", re.MULTILINE)
END_MARK_RE = re.compile(r"^===\s*END\s*FILE\s*===\s*$", re.MULTILINE)
FENCE_RE = re.compile(r"^```[\w+-]*\s*$", re.MULTILINE)

# 模型可寫入的副檔名白名單；判準擁有的路徑一律拒寫
ALLOWED_SUFFIXES = {".py", ".toml", ".md", ".txt", ".cfg", ".ini"}
JUDGE_OWNED = ("tests/", "run_qualification.py", "conftest.py", "result.json")


def split_files(text: str) -> dict[str, str]:
    """把模型輸出依 '=== FILE: path ===' 切成 {相對路徑: 內容}。

    容錯：移除模型多手加上的 ``` 圍欄與 '=== END FILE ===' 標記。
    找不到任何區塊時回傳空 dict，由呼叫端當成格式錯誤處理。
    """
    parts = FILE_HEADER_RE.split(text)
    files: dict[str, str] = {}
    # parts = [前言, path1, body1, path2, body2, ...]
    for i in range(1, len(parts) - 1, 2):
        rel = parts[i].strip().replace("\\", "/")
        body = END_MARK_RE.sub("", parts[i + 1])
        body = FENCE_RE.sub("", body)
        files[rel] = body.strip() + "\n"
    return files


def write_project(files: dict[str, str], proj: Path) -> list[str]:
    """把模型檔案寫進專案目錄，回傳被拒寫的路徑清單。

    拒寫規則：跳脫專案目錄的路徑、白名單外副檔名、判準擁有的路徑。
    後者是「改考卷過關」的典型手法，機械性擋掉（協定 §5.4）。
    """
    rejected: list[str] = []
    root = proj.resolve()
    for rel, body in files.items():
        low = rel.lower().lstrip("./")
        if any(low == p or low.startswith(p) or f"/{p}" in low for p in JUDGE_OWNED):
            rejected.append(f"{rel}（判準路徑，禁止模型覆寫）")
            continue
        dest = (proj / rel).resolve()
        if not dest.is_relative_to(root):
            rejected.append(f"{rel}（路徑跳脫專案目錄）")
            continue
        if dest.suffix not in ALLOWED_SUFFIXES:
            rejected.append(f"{rel}（副檔名不在白名單）")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, encoding="utf-8")
    return rejected


def render_files(files: dict[str, str]) -> str:
    """把檔案集渲染回 FILE 區塊格式——修正輪的輸入與輸出格式一致，
    模型照著看到的樣子回，不用重新理解協定。"""
    return "\n".join(f"=== FILE: {rel} ===\n{body}" for rel, body in files.items())


# ---------------------------------------------------------------------------
# 專案模式：判準執行與結果解析
# ---------------------------------------------------------------------------
SENTINEL_RE = re.compile(
    r"=== IFFT_QUALIFICATION_RESULT ===\s*(\{.*\})\s*=== END ===", re.DOTALL)


def run_judge(proj: Path, judge_dir: Path, timeout: int) -> dict:
    """複製判準資產（覆蓋同名檔）→ 執行 → 回傳結果 dict。

    永遠回傳 {'verdict': 'PASS'|'FAIL', ...}；任何異常（逾時、
    JSON 缺失）都折疊成帶說明的 FAIL，讓主迴圈只看一種形狀。
    """
    for item in judge_dir.iterdir():
        dest = proj / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)
    try:
        r = subprocess.run(
            [sys.executable, "run_qualification.py", "--json-out", "result.json"],
            cwd=proj, capture_output=True, text=True,
            stdin=subprocess.DEVNULL, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"verdict": "FAIL", "failures": [],
                "collection_error_details": [f"判準逾時（>{timeout}s）——無窮迴圈或等待輸入？"]}
    result_file = proj / "result.json"
    if result_file.exists():
        return json.loads(result_file.read_text(encoding="utf-8"))
    m = SENTINEL_RE.search(r.stdout)
    if m:
        return json.loads(m.group(1))
    return {"verdict": "FAIL", "failures": [],
            "collection_error_details": [
                "判準未產生機讀結果。stderr 末段：\n" + r.stderr[-1500:]]}


def judge_signature(result: dict) -> str:
    """從判準 JSON 算錯誤簽名（給震盪偵測用）。

    用「排序後的失敗 nodeid + collection error 首行」而非原始文字：
    hypothesis 已 derandomize，同一組 bug 的簽名是確定性的。
    """
    ids = sorted(f["nodeid"] for f in result.get("failures", []))
    coll = [e.splitlines()[0][:120]
            for e in result.get("collection_error_details", []) if e.strip()]
    return "|".join(ids + coll) or "EMPTY_RESULT"


def judge_error_report(result: dict, max_failures: int = 10, max_msg: int = 800) -> str:
    """把判準結果整理成回授給模型的錯誤文字（控制 token 量）。"""
    out: list[str] = []
    for e in result.get("collection_error_details", []):
        out.append(f"[collection error]\n{e[:max_msg]}")
    fails = result.get("failures", [])
    for f in fails[:max_failures]:
        out.append(f"[{f['id']}] {f['nodeid']}\n{f['message'][:max_msg]}")
    if len(fails) > max_failures:
        out.append(f"...另有 {len(fails) - max_failures} 個失敗未列出，先修上面的")
    for rule in result.get("rules", []):
        out.append(f"[規則] {rule}")
    return "\n\n".join(out) or "（判準沒有回報細節）"


# ---------------------------------------------------------------------------
# 共用：prompt 載入與 LLM 呼叫
# ---------------------------------------------------------------------------
def load_prompt(name: str) -> str:
    path = BASE / "prompts" / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"找不到 prompt 檔：{path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"prompt 檔是空的：{path}（忘記存檔？）")
    return text


def make_generate(client, model: str, premise: str):
    def generate(user_input: str) -> tuple[str, int]:
        interaction = client.interactions.create(
            model=model,
            system_instruction=premise,
            input=user_input,
        )
        code = interaction.output_text.strip()
        lines = code.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip(), interaction.usage.total_tokens
    return generate


# ---------------------------------------------------------------------------
# 單檔模式（V1 原行為，僅整理進函式）
# ---------------------------------------------------------------------------
def run_generated(path: Path, mode: str, timeout: int) -> tuple[bool, str, str]:
    try:
        r = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True, text=True,
            stdin=subprocess.DEVNULL, timeout=timeout,
        )
        return (r.returncode == 0), r.stderr, r.stdout
    except subprocess.TimeoutExpired:
        if mode == "service":
            return True, f"存活 {timeout}s 未 crash（smoke test 通過）", ""
        return False, f"超過 {timeout}s 未結束（無窮迴圈或在等輸入？）", ""


def err_signature(err: str) -> str:
    failed = sorted(ln for ln in err.splitlines() if ln.startswith("FAILED"))
    if failed:
        return "|".join(failed)
    lines = [ln for ln in err.strip().splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def run_gold(gen_path: Path, task: str, timeout: int) -> tuple[bool, str, str]:
    test_path = BASE / "tests" / f"{task}.py"
    if not test_path.exists():
        return True, "", "smoke"
    try:
        t = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_path), "-q", "--tb=line"],
            capture_output=True, text=True,
            stdin=subprocess.DEVNULL, timeout=timeout,
            env={**os.environ, "TARGET": str(gen_path)},
        )
        return (t.returncode == 0), (t.stdout + t.stderr), "gold"
    except subprocess.TimeoutExpired:
        return False, "[gold] 金樣測試逾時", "gold"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="AI code-gen agent")
    parser.add_argument("task", help="prompts/ 底下的任務檔名（不含 .txt）")
    parser.add_argument("--mode", choices=["batch", "service"], default="batch")
    parser.add_argument("--timeout", type=int, default=10,
                        help="單檔模式 smoke/gold 逾時（秒）")
    parser.add_argument("--test-timeout", type=int, default=120,
                        help="專案模式判準逾時（秒）")
    parser.add_argument("--model", default="gemini-3.6-flash")
    parser.add_argument("--max-fix", type=int, default=10)
    args = parser.parse_args()

    judge_dir = BASE / "judge" / args.task
    project_mode = judge_dir.is_dir()

    from dotenv import load_dotenv
    from google import genai

    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY 沒讀到，檢查 .env")
    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        raise RuntimeError(f"Client 建立失敗：{e}") from e

    premise = load_prompt("premise")
    if project_mode:
        premise = premise + "\n\n" + load_prompt("project_rules")
    task_prompt = load_prompt(args.task)
    fix_template = load_prompt("fix_project" if project_mode else "fix")
    generate = make_generate(client, args.model, premise)

    out_dir = BASE / "generated"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    code, tokens = generate(task_prompt)
    success = False
    seen: set[str] = set()
    attempt = 0
    err = ""
    stdout = ""
    out_path: Path = out_dir

    for attempt in range(1, args.max_fix + 2):      # 第1次=首件，其餘是修
        if project_mode:
            proj = out_dir / f"proj_{stamp}_try{attempt}"
            proj.mkdir(parents=True, exist_ok=True)
            files = split_files(code)
            if not files:
                ok, stage = False, "judge"
                err = ("輸出未包含任何 '=== FILE: 路徑 ===' 區塊。"
                       "必須以此格式輸出全部檔案，不得有任何區塊外的文字。")
                sig = "NO_FILE_BLOCKS"
            else:
                rejected = write_project(files, proj)
                result = run_judge(proj, judge_dir, args.test_timeout)
                ok = result.get("verdict") == "PASS"
                stage = "judge"
                err = judge_error_report(result)
                if rejected:
                    err = ("以下檔案被拒寫（不得輸出這些路徑）：\n"
                           + "\n".join(rejected) + "\n\n" + err)
                sig = judge_signature(result) + \
                    ("|REJ:" + ";".join(rejected) if rejected else "")
            out_path = proj
        else:
            out_path = out_dir / f"gen_{stamp}_try{attempt}.py"
            out_path.write_text(code, encoding="utf-8")
            ok, err, stdout = run_generated(out_path, args.mode, args.timeout)
            stage = "smoke"
            if ok:
                ok, gold_err, stage = run_gold(out_path, args.task, args.timeout)
                if not ok:
                    err = gold_err
            sig = err_signature(err)

        with (BASE / "runs.log").open("a", encoding="utf-8") as f:
            f.write(f"{stamp}\ttask={args.task}\ttry={attempt}\tmode={args.mode}\t"
                    f"model={args.model}\ttokens={tokens}\t"
                    f"result={stage}:{'PASS' if ok else 'FAIL'}\n")

        if ok:
            success = True
            break
        print(f"--- 第 {attempt} 次 FAIL ---\n{err}")
        if sig in seen:
            print("錯誤簽名重複（含震盪）＝無進展，提前停止")
            break
        seen.add(sig)
        if attempt <= args.max_fix:
            if project_mode:
                cur = split_files(code)
                fix_input = (fix_template
                             .replace("{files}", render_files(cur) if cur else code)
                             .replace("{failures}", err))
            else:
                fix_input = fix_template.replace("{code}", code).replace("{error}", err)
            code, tokens = generate(fix_input)

    print(f"--- 最終產出 {out_path} ---")
    print("=== PASS ===" if success else f"=== FAIL（共 {attempt} 次）===")
    if stdout:
        print(stdout)
    if err and not success:
        print(err)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
