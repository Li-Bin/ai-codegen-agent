# ai-codegen-agent 專案模式改版（2026-08-16）

## 你回報的症狀與實際根因

「沒辦法跑多個單元測試」不是 pytest 參數問題，是四個綁在一起的架構假設：

1. `run_gold` 寫死單一測試檔 `tests/{task}.py`。
2. 金樣合約靠 `TARGET` 環境變數指向「一個生成腳本」；IFFT 判準測的是
   套件（`import ifft_sim.core.*`），沒有 TARGET 可言。
3. `generate()` 只產一個字串、寫一個檔——缺多檔輸出協定。
4. `err_signature()` 的 fallback 取「最後一行」：接上機讀判準後每次
   失敗的最後一行都是 `=== END ===`，第二次失敗就誤觸「簽名重複＝
   提前停止」。這個 bug 不修，換什麼測試都跑不完。

## 改了什麼

**AI_agent.py**（重構為函式結構，`main()` 進入點）
- 新增專案模式：偵測到 `judge/{task}/` 目錄即啟用；原單檔流程
  （spring_qc）一行邏輯都沒動，向後相容。
- 多檔協定：模型以 `=== FILE: 路徑 ===` 區塊輸出，`split_files()`
  解析（容錯 ``` 圍欄與 END 標記），寫入 `generated/proj_*/try*/`。
- `write_project()` 安全規則：拒寫跳脫目錄的路徑、白名單外副檔名、
  以及 tests/、run_qualification.py 等判準路徑——機械性擋掉
  「改考卷過關」；判準資產在模型檔案「之後」複製並覆蓋同名檔。
- `run_judge()`：於專案目錄執行 `run_qualification.py`，解析
  result.json（備援：stdout 哨兵區塊）；逾時、缺 JSON 一律折疊成
  帶說明的 FAIL。
- `judge_signature()`：以排序後的失敗 nodeid 計算簽名（判準端
  hypothesis 已 derandomize，簽名具確定性），取代舊的末行 fallback。
- `judge_error_report()`：回授訊息截斷（10 個失敗 × 800 字），
  控制修正輪 token 量。
- 專案模式跳過 smoke：套件模組含相對匯入，直接執行必炸；import
  錯誤由判準 collection error 回報。
- SDK 延遲匯入：google-genai／dotenv 移入 `main()`，harness 函式
  可在沒有 SDK 的環境單獨測試。
- 新參數 `--test-timeout`（預設 120s），與單檔 smoke 的 `--timeout`
  分離。判準實測 ~2s，餘裕給冷啟動與 hypothesis 首跑。

**prompts/**
- `project_rules.txt`（新）：多檔輸出格式規則，專案模式時附加到
  premise 後。
- `fix_project.txt`（新）：修正輪模板，佔位符 {files}／{failures}。
- `ifft_core.txt`（新）：任務頭（範圍限 core 六檔、禁產 tests/）
  ＋介面協定 v1.2 全文。

**judge/ifft_core/**（新）：判準資產——tests/ 七檔＋
run_qualification.py，即先前交付的合格性套件原封搬入。

**requirements.txt**：UTF-16 → UTF-8（原檔是 PowerShell 重導向的
副作用，pip 認得但其他工具全讀爆），補 `hypothesis==6.164.0`。

## 離線驗證紀錄（無 API 金鑰，假模型輸出打全管線）

    [1] 正確參考實作           -> PASS（41 案例）
    [2] 植入 M3 正規化 bug     -> FAIL，簽名含 T03
    [3] 植入 M2 奇數長度 bug   -> FAIL，簽名與 [2] 不同（震盪偵測有意義）
    [4] 模型企圖覆寫 tests/    -> 拒寫，判準檔完好，verdict 不受影響
    [5] 模型輸出散文無區塊     -> 空 dict → 格式錯誤回授
    [6] 同 bug 重跑            -> 簽名一致（提前停止條件可靠）

## 使用

    pip install -r requirements.txt
    python AI_agent.py ifft_core --max-fix 10 --test-timeout 120

唯一沒驗證的環節是 Gemini 呼叫本身（此環境無金鑰）；`generate()`
的介面沒動過，風險最低。第一次真跑建議 `--max-fix 3` 觀察回授品質
再放大。
