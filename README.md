# ai-codegen-agent (V1.5)

用 Gemini 生成 Python 程式 → 自動執行 → 用 pytest 判定 → 失敗訊息回授給模型修正 → 直到通過或停機。

一句話：**你寫規格（prompt）和考卷（pytest），工具負責生碼、跑碼、改碼。**

V1.5 起有兩種模式，依 `judge/<task>/` 目錄是否存在**自動切換**：
單檔模式（V1 原行為，一字未動）與專案模式（多檔生成＋整套判準，見第 4 節）。

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

> V1.5 起 `requirements.txt` 改為 UTF-8 編碼並加入 `hypothesis`（判準端 property-based 測試用）。
> 舊版是 PowerShell 重導向產生的 UTF-16，pip 認得但其他工具讀不了。

---

## 2. 資料夾結構

```
AI_agent.py              主程式
prompts/
  premise.txt            角色設定與編碼規則（每次呼叫都送）
  fix.txt                修正指令模板（單檔模式的修正輪）
  project_rules.txt      多檔輸出格式規則（專案模式時附加到 premise 後）
  fix_project.txt        專案模式修正模板（佔位符 {files}、{failures}）
  <task>.txt             任務規格，一個任務一個檔
tests/
  <task>.py              單檔模式金樣（pytest），檔名必須與任務同名
judge/
  <task>/                專案模式判準資產（存在即啟用專案模式）
    tests/               整套 pytest 判準
    run_qualification.py 判準執行器（輸出機讀 JSON）
generated/               單檔模式：gen_<時間>_try<n>.py
                         專案模式：proj_<時間>_try<n>/（整個專案目錄）
runs.log                 每輪一行的執行紀錄
requirements.txt
.env.example             金鑰範本
```

---

## 3. 執行

```bash
python AI_agent.py <task> [--max-fix N] [--timeout S] [--test-timeout S] [--mode batch|service] [--model NAME]
```

範例：

```bash
python AI_agent.py spring_qc                 # 單檔模式：prompts/spring_qc.txt + tests/spring_qc.py
python AI_agent.py ifft_core                 # 專案模式：judge/ifft_core/ 存在，自動啟用
python AI_agent.py matrix --max-fix 0        # 只生首件，不修正
python AI_agent.py server --mode service --timeout 30
```

| 參數 | 預設 | 作用 |
|---|---|---|
| `task` | 必填 | 任務名 = `prompts/<task>.txt` 的檔名（不含 .txt） |
| `--max-fix` | 10 | 修正額度。總執行次數 = 1 次首件 + max-fix 次修正。設 0 = 只生成不修 |
| `--timeout` | 10 | 單檔模式每一次執行（含金樣）的秒數上限 |
| `--test-timeout` | 120 | 專案模式判準的秒數上限（property-based 測試較耗時） |
| `--mode` | batch | timeout 到期的解讀：`batch` = 判 FAIL；`service` = 活過 N 秒沒 crash 判 PASS（常駐程式用，僅單檔模式） |
| `--model` | gemini-3.6-flash | 使用的模型 |

> **`--mode service` 仍是半成品**（這也是版本叫 V1.5 而非 V2 的原因）。它只在 timeout 到期時改判「存活通過」，
> 不會探測服務是否真的正常。完整的服務探測（啟動 → 等就緒 → 送請求 → 驗回應 → 關閉）仍列為 V2 需求。

---

## 4. 專案模式（V1.5 新增）

單檔模式生一個腳本、金樣靠 `TARGET` 環境變數指向它。專案模式生**一整個套件**，
判準直接 import 套件——兩者的合約形狀完全不同：

| | 單檔模式（V1） | 專案模式（V1.5） |
|---|---|---|
| 觸發 | `judge/<task>/` 不存在 | `judge/<task>/` 存在 |
| 生成單位 | 一個 .py | 多檔（`=== FILE: 路徑 ===` 區塊協定） |
| 受測物傳遞 | 環境變數 `TARGET` | 判準複製進專案目錄後直接 import |
| 判定 | `tests/<task>.py` | `judge/<task>/` 整套 + `run_qualification.py` 機讀 JSON |
| smoke | 有 | 無（套件模組含相對匯入，直接執行必炸；import 錯誤由判準 collection error 回報） |
| 錯誤簽名 | 失敗訊息文字行 | JSON 失敗測項清單（排序後） |
| 產出 | `gen_*.py` | `proj_*/try<n>/` 目錄（含 result.json） |

### 迴圈

```
生成多檔 → 解析＋安全寫入 → 複製判準進專案（覆蓋同名）→ 執行判準
  → JSON verdict：PASS 結束 / FAIL → fix_project.txt（全部檔案＋失敗清單）→ 重生
```

### 防作弊（機制，不是君子協定）

- 模型輸出若指向 `tests/`、`run_qualification.py`、`conftest.py` 等判準路徑 → **拒寫**並記入回授。
- 判準資產在模型檔案**之後**複製、覆蓋同名檔——判準永遠是原版。
- 路徑跳脫（`..`）、白名單外副檔名一律拒寫。

### 新增一個專案模式任務

1. 建 `prompts/foo.txt`，寫規格（建議直接放完整介面協定）
2. 建 `judge/foo/tests/`（pytest 判準）與 `judge/foo/run_qualification.py`
   （執行器需輸出 `=== IFFT_QUALIFICATION_RESULT ===` 哨兵包住的 JSON，含 `verdict` 與 `failures`）
3. `python AI_agent.py foo`

`runs.log` 的 `result` 欄在專案模式標成 `judge:PASS` / `judge:FAIL`。
看到 `smoke:` 代表跑的是單檔模式——多半是 `judge/<task>/` 目錄名跟任務名對不上。

---

## 5. prompts/ —— 改哪個檔會影響什麼

| 檔案 | 什麼時候送給模型 | 影響範圍 | 改動時注意 |
|---|---|---|---|
| `premise.txt` | **每一次**呼叫（首件與每輪修正） | 所有任務、所有輪：角色、編碼標準、輸出規則、可用套件白名單 | 改一個字所有任務都受影響。輸出規則（只出程式碼、不要 ``` ）放最後 |
| `project_rules.txt` | 專案模式的每一次呼叫（附加在 premise 後） | 多檔輸出格式、禁產 tests/ 的規則 | 只影響專案模式 |
| `fix.txt` | 單檔模式的**修正輪** | 模型「怎麼修」 | 必須保留 `{code}` 和 `{error}` 兩個佔位符 |
| `fix_project.txt` | 專案模式的**修正輪** | 同上 | 必須保留 `{files}` 和 `{failures}` 兩個佔位符 |
| `<task>.txt` | 只在該任務的**首件** | 只影響這一個任務 | 這是規格。寫得越精確，判準越好出、收斂越快 |

改完 prompt **一定要存檔**（建議 VS Code 開 Auto Save）。程式讀到空檔會直接停下並提示「prompt 檔是空的（忘記存檔？）」。

### 新增一個單檔任務

1. 建 `prompts/foo.txt`，寫規格
2. （建議）建 `tests/foo.py`，寫金樣
3. `python AI_agent.py foo`

---

## 6. tests/ —— 單檔模式金樣（pytest）

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

### 寫金樣的三條規則（專案模式的判準同樣適用）

1. **assert 一定帶訊息**（預期什麼、實得什麼）。這段訊息就是回授給模型的誤差訊號，寫得越清楚修得越快。
2. **金樣先自驗**：拿一份確認正確的程式跑，必須全過；再故意改壞一處，必須抓到。沒驗過的金樣給的 FAIL 不算數。
3. **金樣內容不進 prompt**：模型只會收到失敗訊息，收不到考卷本身。這是防止它「只針對測項硬編碼答案」。

---

## 7. 迴圈怎麼跑、什麼時候停

單檔模式：

```
規格 → 生成 → 寫檔 gen_try1.py → 執行(smoke) → 金樣(gold) → PASS? 結束
                                                     ↓ FAIL
                              fix.txt + 失敗訊息 → 重新生成 → gen_try2.py → ...
```

專案模式的迴圈見第 4 節。停機條件（兩種模式相同，三選一）：

| 出口 | 條件 | 畫面訊息 |
|---|---|---|
| PASS | 判定全過 | `=== PASS ===` |
| 無進展 | 同一組錯誤簽名重複出現（含 A→B→A 震盪） | `錯誤簽名重複…提前停止` |
| 額度用盡 | 已跑滿 1 + max-fix 次 | `=== FAIL（共 n 次）===` |

每一輪都會在 `generated/` 留產出、在 `runs.log` 加一行。
同一次執行的所有輪共用同一個時間戳，靠 `try` 編號區分——這組就是完整病歷。

`runs.log` 格式（tab 分隔）：

```
20260814_230225  task=spring_qc  try=1  mode=batch  model=gemini-3.6-flash  tokens=1834  result=gold:FAIL
20260817_002948  task=ifft_core  try=1  mode=batch  model=gemini-3.6-flash  tokens=9127  result=judge:PASS
```

`result` 欄前綴：`smoke` = 只驗了能不能跑（沒金樣）；`gold` = 單檔金樣有跑；`judge` = 專案模式判準有跑。

---

## 8. 常見狀況

| 訊息 / 現象 | 原因 | 處理 |
|---|---|---|
| `找不到 prompt 檔：...` | 任務名打錯，或 `prompts/<task>.txt` 不存在 | 對一下檔名 |
| `prompt 檔是空的（忘記存檔？）` | 建了檔沒存 | 存檔，或開 Auto Save |
| `GEMINI_API_KEY 沒讀到` | 沒有 `.env`，或不在 `AI_agent.py` 同一層 | 照第 1 節建 |
| 想跑專案模式卻看到 `smoke:` / `gen_*.py` | `judge/<task>/` 目錄名跟任務名對不上，靜默退回單檔模式 | 對齊三處：命令列任務名、`prompts/<task>.txt`、`judge/<task>/` |
| `judge:FAIL` 但畫面訊息不夠 | — | 看 `generated/proj_*/try<n>/result.json` 的 failures |
| 判準逾時 | property-based 測試或防毒掃描拖慢 | 調高 `--test-timeout` |
| runs.log 都是 `smoke:PASS` | 金樣檔名跟任務名不同，被跳過 | 改名成 `tests/<task>.py` |
| 生成碼 `ModuleNotFoundError` | 模型用了 venv 裡沒裝的套件 | 確認是真實套件後**手動** `pip install`，並加進 `premise.txt` 白名單。工具刻意不自動安裝 |
| 每輪 FAIL 但錯誤各不相同 | 正常，這是在收斂 | 等它跑完；卡住會被無進展偵測攔下 |
| 想只看模型生什麼、不修 | — | `--max-fix 0` |

---

## 9. 這個工具能做什麼、不能做什麼

能：單檔、跑完就結束的 Python 程式；**多檔專案級生成（V1.5，需自備 judge 判準）**；正確性可由 pytest 判定的任務。

不能（刻意不做或尚未做）：增量修改既有專案（每輪重生全部檔案）、GUI 的正確性判定（可把 AppTest 之類寫進 judge，但工具本身不內建）、常駐服務的功能探測（`--mode service` 只驗存活，V2 需求）、自動安裝套件、沙箱隔離（生成碼以你的帳號權限執行——任務內容請自己把關）。

---

## 10. 安全提醒

- 生成的程式碼視同**不受信任的輸入**。它能做到你帳號能做的一切。
- 金鑰只放 `.env`，永遠不要寫進程式或 commit。
- 需要新套件時，先到 PyPI 確認名稱真實、有正常下載量再裝——模型會幻覺出不存在的套件名。
- 專案模式的判準路徑拒寫是防「模型改考卷」，不是防惡意——沙箱隔離仍不存在。

---

## 11. 版本

| 版本 | 內容 |
|---|---|
| V1 | 單檔生成＋TARGET 金樣＋修正迴圈＋震盪偵測 |
| V1.5 | 專案模式：多檔區塊協定、judge 判準注入、機讀 JSON 回授、判準路徑拒寫、SDK 延遲匯入、`--test-timeout`；requirements 轉 UTF-8＋hypothesis |
| V2（待辦） | `--mode service` 完整服務探測；增量修改既有專案 |
