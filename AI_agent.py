import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google import genai

parser = argparse.ArgumentParser(description="AI code-gen agent")
parser.add_argument("task", help="prompts/ 底下的任務檔名（不含 .txt）")
parser.add_argument("--mode", choices=["batch", "service"], default="batch")
parser.add_argument("--timeout", type=int, default=10)
parser.add_argument("--model", default="gemini-3.6-flash")
parser.add_argument("--max-fix", type=int, default=10)
args = parser.parse_args()
BASE = Path(__file__).parent

def load_prompt(name: str) -> str:
    path = BASE / "prompts" / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"找不到 prompt 檔：{path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"prompt 檔是空的：{path}（忘記存檔？）")
    return text

def generate(user_input: str) -> tuple[str, int]:
    interaction = client.interactions.create(
        model=args.model,
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

def run_generated(path: Path) -> tuple[bool, str, str]:
    try:
        r = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True, text=True,
            stdin=subprocess.DEVNULL, timeout=args.timeout,
        )
        return (r.returncode == 0), r.stderr, r.stdout
    except subprocess.TimeoutExpired:
        if args.mode == "service":
            return True, f"存活 {args.timeout}s 未 crash（smoke test 通過）", ""
        return False, f"超過 {args.timeout}s 未結束（無窮迴圈或在等輸入？）", ""
    
def err_signature(err: str) -> str:
    failed = sorted(ln for ln in err.splitlines() if ln.startswith("FAILED"))
    if failed:
        return "|".join(failed)
    lines = [ln for ln in err.strip().splitlines() if ln.strip()]
    return lines[-1] if lines else ""

def run_gold(gen_path: Path) -> tuple[bool, str, str]:
    test_path = BASE / "tests" / f"{args.task}.py"
    if not test_path.exists():
        return True, "", "smoke"
    try:
        t = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_path), "-q", "--tb=line"],
            capture_output=True, text=True,
            stdin=subprocess.DEVNULL, timeout=args.timeout,
            env={**os.environ, "TARGET": str(gen_path)},
        )
        return (t.returncode == 0), (t.stdout + t.stderr), "gold"
    except subprocess.TimeoutExpired:
        return False, "[gold] 金樣測試逾時", "gold"

out_dir = BASE / "generated"
out_dir.mkdir(exist_ok=True)
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

success = False
seen = set()
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise RuntimeError("GEMINI_API_KEY 沒讀到，檢查 .env")
try:
    client = genai.Client(api_key=api_key)
except Exception as e:
    raise RuntimeError(f"Client 建立失敗：{e}") from e

premise = load_prompt("premise")
task_prompt = load_prompt(args.task)


fix_template = load_prompt("fix")
out_dir = BASE / "generated"
out_dir.mkdir(exist_ok=True)
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

code, tokens = generate(task_prompt)


success = False
seen = set()

for attempt in range(1, args.max_fix + 2):        # 第1次=首件，其餘是修
    out_path = out_dir / f"gen_{stamp}_try{attempt}.py"
    out_path.write_text(code, encoding="utf-8")
    ok, err, stdout = run_generated(out_path)
    stage = "smoke"
    if ok:
        ok, gold_err, stage = run_gold(out_path)
        if not ok:
            err = gold_err
    with (BASE / "runs.log").open("a", encoding="utf-8") as f:
        f.write(f"{stamp}\ttask={args.task}\ttry={attempt}\tmode={args.mode}\t"
                f"model={args.model}\ttokens={tokens}\t"
                f"result={stage}:{'PASS' if ok else 'FAIL'}\n")

    if ok:
        success = True
        break
    print(f"--- 第 {attempt} 次 FAIL ---\n{err}")
    sig = err_signature(err)
    if sig in seen:
        print("錯誤簽名重複（含震盪）＝無進展，提前停止")
        break
    seen.add(sig)
    if attempt <= args.max_fix:
        fix_input = fix_template.replace("{code}", code).replace("{error}", err)
        code, tokens = generate(fix_input)

print(f"--- 最終產出 {out_path} ---")
print("=== PASS ===" if success else f"=== FAIL（共 {attempt} 次）===")
if stdout:
    print(stdout)
if err:
    print(err)

# stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
# out_dir = BASE / "generated"
# out_dir.mkdir(exist_ok=True)

# out_path = out_dir / f"gen_{stamp}.py"
# out_path.write_text(code, encoding="utf-8")

# ok, err, stdout = run_generated(out_path)
# with (BASE / "runs.log").open("a", encoding="utf-8") as f:
#     f.write(f"{stamp}\ttask={args.task}\tmode={args.mode}\ttimeout={args.timeout}\t"
#             f"model={args.model}\ttokens={tokens}\t"
#             f"result={'PASS' if ok else 'FAIL'}\n")

# print(f"--- 已寫入 {out_path} ---")
# print("=== PASS ===" if ok else "=== FAIL ===")
# if stdout:
#     print(stdout)
# if err:
#     print(err)