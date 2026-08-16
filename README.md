# ai-codegen-agent (V2)

用 Gemini 生成 Python 程式 → 自動執行 → 用 pytest 金樣判定 → 失敗訊息回授給模型修正 → 直到通過或停機。

一句話：**你寫規格（prompt）和考卷（pytest），工具負責生碼、跑碼、改碼。**

---

## 1. 安裝

```bash
git clone https://github.com/Li-Bin/ai-codegen-agent.git
cd ai-codegen-agent

# 建虛擬環境並啟用
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux / macOS

pip install -r requirements.txt

# 金鑰：複製範本後填入
copy .env.example .env          # Windows
# cp .env.example .env          # Linux / macOS
```

`.env` 內容只有一行：

```
GEMINI_API_KEY=你的金鑰
```

`.env`、`.venv/`、`generated/`、`runs.log` 都在 `.gitignore` 裡，**不會**進版控。

---

## 2. 資料夾結構

```
AI_agent.py          主程式
prompts/
  premise.txt        角色設定與編碼規則（每次呼叫都送）
  fix.txt            修正指令模板（只在修正輪送）
  <task>.txt         任務規格，一個任務一個檔
tests/
  <task>.py          任務對應的金樣（pytest），檔名必須與任務同名
generated/           每輪產出 gen_<時間>_try<n>.py（自動建立）
runs.log             每輪一行的執行紀錄
requirements.txt
.env.example         金鑰範本
```

---

## 3. 執行

```bash
python AI_agent.py <task> [--max-fix N] [--timeout S] [--mode batch|service] [--model NAME]
```

範例：

```bash
python AI_agent.py spring_qc                 # 跑 prompts/spring_qc.txt，金樣 tests/spring_qc.py
python AI_agent.py matrix --max-fix 0        # 只生首件，不修正
python AI_agent.py server --mode service --timeout 30
```

| 參數 | 預設 | 作用 |
|---|---|---|
| `task` | 必填 | 任務名 = `prompts/<task>.txt` 的檔名（不含 .txt） |
| `--max-fix` | 10 | 修正額度。總執行次數 = 1 次首件 + max-fix 次修正。設 0 = 只生成不修 |
| `--timeout` | 10 | 每一次執行（含金樣）的秒數上限 |
| `--mode` | batch | timeout 到期的解讀：`batch` = 判 FAIL；`service` = 活過 N 秒沒 crash 判 PASS（常駐程式用） |
| `--model` | gemini-3.6-flash | 使用的模型 |

> **`--mode service` 是半成品。** 它只做一件事：timeout 到期時不判 FAIL、改判「存活通過」。
> 它**不會**探測服務是否真的正常（沒有打請求、沒有驗回應）；金樣（`tests/<task>.py`）對常駐程式也不適用，
> 因為金樣是把生成檔當腳本再跑一次驗 stdout。常駐任務目前只能驗「沒 crash」，功能正確性請人工確認。
> 完整的服務探測（啟動 → 等就緒 → 送請求 → 驗回應 → 關閉）列為 V2 需求。

---

## 4. prompts/ —— 改哪個檔會影響什麼

| 檔案 | 什麼時候送給模型 | 影響範圍 | 改動時注意 |
|---|---|---|---|
| `premise.txt` | **每一次**呼叫（首件與每輪修正） | 所有任務、所有輪：角色、編碼標準、輸出規則、可用套件白名單 | 改一個字所有任務都受影響。輸出規則（只出程式碼、不要 ``` ）放最後 |
| `fix.txt` | 只在**修正輪** | 模型「怎麼修」 | 必須保留 `{code}` 和 `{error}` 兩個佔位符，程式用字串取代填入。不要改成別的名字 |
| `<task>.txt` | 只在該任務的**首件** | 只影響這一個任務 | 這是規格。寫得越精確（點數、格式、位數、行數），金樣越好出、收斂越快 |

改完 prompt **一定要存檔**（建議 VS Code 開 Auto Save）。程式讀到空檔會直接停下並提示「prompt 檔是空的（忘記存檔？）」。

### 新增一個任務

1. 建 `prompts/foo.txt`，寫規格
2. （建議）建 `tests/foo.py`，寫金樣
3. `python AI_agent.py foo`

---

## 5. tests/ —— 金樣（pytest）

### 命名規則（最常踩的坑）

**測試檔名必須與任務名完全相同**：任務 `spring_qc` → 金樣 `tests/spring_qc.py`。
程式用 `tests/<task>.py` 去找；找不到就**跳過金樣**、只做 smoke（能不能跑），
runs.log 會標成 `smoke:PASS` 而不是 `gold:PASS`。看到 `smoke:` 就代表金樣沒被執行。

### 受測檔怎麼傳進來

程式用 `pytest` 執行金樣，並把**當輪生成檔的路徑**放進環境變數 `TARGET`。
金樣裡用 `os.environ["TARGET"]` 取得受測檔。

### 兩種寫法

黑箱（跑受測檔、驗它印出的東西）：

```python
import os, subprocess, sys

def _out():
    r = subprocess.run([sys.executable, os.environ["TARGET"]],
                       capture_output=True, text=True, timeout=10)
    return [ln for ln in r.stdout.splitlines() if ln.strip()]

def test_line_count():
    assert len(_out()) == 8, f"預期 8 行，實得 {len(_out())} 行"
```

白箱（import 受測檔、直接呼叫函式）：

```python
import importlib.util, os
import numpy as np

_s = importlib.util.spec_from_file_location("target", os.environ["TARGET"])
target = importlib.util.module_from_spec(_s); _s.loader.exec_module(target)

def test_roundtrip():
    x = np.random.default_rng(42).normal(size=256)
    assert np.allclose(np.fft.ifft(np.fft.fft(x)).real, x, atol=1e-9)
```

### 寫金樣的三條規則

1. **assert 一定帶訊息**（預期什麼、實得什麼）。這段訊息就是回授給模型的誤差訊號，寫得越清楚修得越快。
2. **金樣先自驗**：拿一份確認正確的程式跑，必須全過；再故意改壞一處，必須抓到。沒驗過的金樣給的 FAIL 不算數。
3. **金樣內容不進 prompt**：模型只會收到失敗訊息，收不到考卷本身。這是防止它「只針對測項硬編碼答案」。

---

## 6. 迴圈怎麼跑、什麼時候停

```
規格 → 生成 → 寫檔 gen_try1.py → 執行(smoke) → 金樣(gold) → PASS? 結束
                                                     ↓ FAIL
                              fix.txt + 失敗訊息 → 重新生成 → gen_try2.py → ...
```

停機條件（三選一）：

| 出口 | 條件 | 畫面訊息 |
|---|---|---|
| PASS | smoke 與金樣皆過 | `=== PASS ===` |
| 無進展 | 同一組失敗訊息重複出現（含 A→B→A 震盪） | `錯誤簽名重複…提前停止` |
| 額度用盡 | 已跑滿 1 + max-fix 次 | `=== FAIL（共 n 次）===` |

每一輪都會：寫一個 `generated/gen_<時間>_try<n>.py`、在 `runs.log` 加一行。
同一次執行的所有輪共用同一個時間戳，靠 `try` 編號區分——這組就是完整病歷。

`runs.log` 格式（tab 分隔）：

```
20260814_230225  task=spring_qc  try=1  mode=batch  model=gemini-3.6-flash  tokens=1834  result=gold:FAIL
20260814_230225  task=spring_qc  try=2  mode=batch  model=gemini-3.6-flash  tokens=2210  result=gold:PASS
```

`result` 欄前綴：`smoke` = 只驗了能不能跑（沒金樣）；`gold` = 金樣有跑。

---

## 7. 常見狀況

| 訊息 / 現象 | 原因 | 處理 |
|---|---|---|
| `找不到 prompt 檔：...` | 任務名打錯，或 `prompts/<task>.txt` 不存在 | 對一下檔名 |
| `prompt 檔是空的（忘記存檔？）` | 建了檔沒存 | 存檔，或開 Auto Save |
| `GEMINI_API_KEY 沒讀到` | 沒有 `.env`，或不在 `AI_agent.py` 同一層 | 照第 1 節建 |
| runs.log 都是 `smoke:PASS` | 金樣檔名跟任務名不同，被跳過 | 改名成 `tests/<task>.py` |
| 生成碼 `ModuleNotFoundError` | 模型用了 venv 裡沒裝的套件 | 確認是真實套件後**手動** `pip install`，並加進 `premise.txt` 白名單。工具刻意不自動安裝 |
| 每輪 FAIL 但錯誤各不相同 | 正常，這是在收斂 | 等它跑完；卡住會被無進展偵測攔下 |
| 想只看模型生什麼、不修 | — | `--max-fix 0` |

---

## 8. 這個工具能做什麼、不能做什麼

能：單檔、跑完就結束（或常駐可 smoke）的 Python 程式；正確性可由 pytest 判定的任務。

不能（V1 刻意不做）：多檔／專案級生成、修改既有檔案、GUI 的正確性判定（Streamlit 這類請在迴圈外用一般方式協作＋人工驗收）、常駐服務的功能探測（`--mode service` 只驗存活）、自動安裝套件、沙箱隔離（生成碼以你的帳號權限執行——任務內容請自己把關）。

---

## 9. 安全提醒

- 生成的程式碼視同**不受信任的輸入**。它能做到你帳號能做的一切。
- 金鑰只放 `.env`，永遠不要寫進程式或 commit。
- 需要新套件時，先到 PyPI 確認名稱真實、有正常下載量再裝——模型會幻覺出不存在的套件名。
