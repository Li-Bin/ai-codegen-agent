# -*- coding: utf-8 -*-
"""
tests/test_metrics.py — 量測函式測試（T-04, T-13）

【為什麼】UI 的指標列（rmse / snr / peak）直接顯示這些函式的輸出，
    而且 T-11b 用 rmse 驗證 UI↔core 的連接。量測函式本身錯了，
    整個「自我檢驗」機制就是在用壞掉的尺量東西。
"""
import numpy as np
import pytest

from ifft_sim.core.signal_gen import generate
from ifft_sim.core.spectrum import forward
from ifft_sim.core.metrics import rmse, snr_db, peak_frequency
from ifft_sim.core.types import InvalidParameterError
from tests.conftest import ATOL_EXACT, make_spec


def test_T04_peak_frequency_exact_on_binary_exact_grid():
    """
    【為什麼】peak_frequency 是「濾波前後對照」的客觀證據：濾除前
        峰值應在主頻。這裡要求「精確相等」而非近似——做得到，因為
        參數刻意選成二進位精確：fs=1024（2 的冪）、N=512 → Δf=2.0
        精確、d=1/1024 精確、rfftfreq 每個值精確。主頻 100.0 =
        bin 50，能量全在單一 bin，argmax 沒有歧義。
        用 fs=1000 這種十進位漂亮、二進位不精確的值，這條測試會被
        最後一位 ulp 的浮點雜訊搞到偶發失敗——那是測試設計錯，
        不是實作錯。
    【測什麼】fs=1024, N=512, f_main=100, f_noise=250（皆對齊 bin），
        noise_amp < main_amp 時 peak == 100.0，容差 ATOL_EXACT。
    """
    spec = make_spec(main_freq_hz=100.0, noise_freq_hz=250.0,
                     sample_rate_hz=1024.0, n_samples=512,
                     main_amp=1.0, noise_amp=0.4)
    s = forward(generate(spec).noisy, spec.sample_rate_hz)
    peak = peak_frequency(s)
    assert peak == pytest.approx(100.0, abs=ATOL_EXACT), \
        f"峰值頻率 {peak}，應為 100.0（bin 50）"


def test_T04_ignore_dc_actually_ignores_dc():
    """
    【為什麼】加了直流偏移的訊號，DC bin 能量往往最大。ignore_dc
        預設 True 若沒實作，「峰值頻率」永遠回 0 Hz——UI 上這個
        指標就廢了。
    【測什麼】訊號加大直流偏移後，peak_frequency(ignore_dc=True)
        仍回主頻，ignore_dc=False 回 0.0。
    """
    spec = make_spec(main_freq_hz=100.0, noise_freq_hz=250.0,
                     sample_rate_hz=1024.0, n_samples=512, noise_amp=0.0)
    x = generate(spec).noisy + 5.0  # 直流偏移遠大於弦波振幅
    s = forward(x, spec.sample_rate_hz)
    assert peak_frequency(s, ignore_dc=True) == pytest.approx(100.0, abs=ATOL_EXACT)
    assert peak_frequency(s, ignore_dc=False) == pytest.approx(0.0, abs=ATOL_EXACT)


def test_T13_snr_db_matches_hand_computed_value():
    """
    【為什麼】SNR 的常見錯法：用振幅比而非功率比、log 底數錯、
        少乘 10。用常數訊號手算可完全繞開「弦波要整數週期功率
        才是 A²/2」的干擾，把判準釘在一個小學算術就能驗的數字上。
    【測什麼】signal=全 2（功率 4）、noise=全 1（功率 1）：
        snr == 10*log10(4) ≈ 6.0206 dB，rtol=1e-9。
    """
    s = np.full(64, 2.0)
    n = np.full(64, 1.0)
    assert snr_db(s, n) == pytest.approx(10.0 * np.log10(4.0), rel=1e-9)


def test_T13_snr_db_zero_noise_returns_inf():
    """
    【為什麼】雜訊振幅拉到 0 是 UI 滑桿的合法輸入。除以零若沒
        處理，畫面直接炸 ZeroDivisionError 或出現 nan。
    【測什麼】全零雜訊 → 回傳 float('inf')，不丟例外。
    """
    assert snr_db(np.ones(32), np.zeros(32)) == float("inf")


def test_T13_rmse_rejects_length_mismatch():
    """
    【為什麼】長度不一的陣列丟進 rmse，numpy 廣播規則可能默默
        算出一個「看起來合理」的錯值——這比當掉更危險。
    【測什麼】長度 32 vs 33 → InvalidParameterError。
    """
    with pytest.raises(InvalidParameterError):
        rmse(np.ones(32), np.ones(33))


def test_T13_rmse_known_value():
    """
    【測什麼】a=[0,0,0,0], b=[1,1,1,1] → rmse == 1.0（手算可驗）。
        a==b → rmse == 0.0。
    """
    assert rmse(np.zeros(4), np.ones(4)) == pytest.approx(1.0, rel=1e-12)
    assert rmse(np.ones(4), np.ones(4)) == 0.0
