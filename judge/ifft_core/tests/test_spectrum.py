# -*- coding: utf-8 -*-
"""
tests/test_spectrum.py — IFFT 合格性核心測試（T-01, T-02, T-05, T-06, T-12）

這個檔案回答一個問題：「這個 FFT→濾除→IFFT 管線，數學上合格嗎？」
五條測試各守一個不同的失敗模式，缺一條就有一種爛法抓不到。
"""
import numpy as np
import pytest
from numpy.testing import assert_allclose

from ifft_sim.core.signal_gen import generate
from ifft_sim.core.spectrum import forward, reconstruct, suppress_tone
from ifft_sim.core.metrics import rmse
from tests.conftest import (
    ATOL_EXACT, ATOL_ALIGNED, RTOL_LEAK_MIN, RTOL_LEAKY,
    make_spec, align_to_bin,
)


@pytest.mark.parametrize("n", [64, 128, 255, 512, 1023])
def test_T01_roundtrip_is_identity(n):
    """
    【為什麼】irfft(rfft(x)) == x 是整個系統的地基。這條不成立，
        後面所有「濾除→還原」都是在錯的地基上蓋房子。
        參數化刻意包含奇數長度（255, 1023）：irfft 不給 n= 參數時，
        奇數長度會被還原成 n-1 點——這是最常見的實作 bug，只測
        2 的冪次永遠抓不到。
    【測什麼】對 5 種長度的隨機訊號（固定 seed），往返後逐點
        誤差 < ATOL_EXACT (1e-12)。
    """
    rng = np.random.default_rng(0)
    x = rng.standard_normal(n)
    assert_allclose(reconstruct(forward(x, 1000.0)), x, atol=ATOL_EXACT, rtol=0)


@pytest.mark.parametrize("n", [512, 1023])
def test_T02_reconstruction_is_real_float64_and_full_length(n):
    """
    【為什麼】協定 D-2 強制用 rfft/irfft 而非 fft/ifft，就是為了讓
        「輸出是實數」成為資料結構的保證，而不是事後 .real 硬砍。
        如果實作者違反 D-2 改用 ifft，輸出會是 complex128——這條
        測試就是 D-2 的執法者。長度檢查同時抓「奇數 N 少一點」。
    【測什麼】還原輸出 dtype == float64、shape == (n,)。
    """
    x = np.random.default_rng(1).standard_normal(n)
    out = reconstruct(forward(x, 1000.0))
    assert out.dtype == np.float64, f"dtype 是 {out.dtype}，違反 D-2（應為 float64）"
    assert out.shape == (n,), f"長度 {out.shape}，應為 ({n},)——irfft 少了 n= 參數？"


def test_T05_notch_removes_bin_aligned_noise_exactly():
    """
    【為什麼】這是「濾波器在理想條件下必須完美」的對照組。當主頻與
        雜訊頻率都精確落在 bin 上，雜訊的全部能量集中在單一 bin，
        陷波掉那個 bin 之後還原結果應該與乾淨訊號幾乎逐位元相同。
        這條過不了 = suppress/reconstruct 的頻帶選取或索引有錯。
        （T-06 是它的鏡像：非理想條件下「不可能完美」。兩條要一起
        看才構成完整的判準。）
    【測什麼】fs=1000, N=512（Δf 精確），把 50/125 Hz 捨入到 bin
        整數倍，生成→陷波雜訊 bin→還原，rmse(還原, clean) <
        ATOL_ALIGNED (1e-10)。實測正確實作為 ~5e-15。
    """
    df = make_spec().freq_resolution_hz
    spec = make_spec(
        main_freq_hz=align_to_bin(50.0, df),
        noise_freq_hz=align_to_bin(125.0, df),
    )
    b = generate(spec)
    filtered = suppress_tone(forward(b.noisy, spec.sample_rate_hz), spec.noise_freq_hz)
    err = rmse(reconstruct(filtered), b.clean)
    assert err < ATOL_ALIGNED, f"對齊 bin 的陷波還原誤差 {err:.3e} 超出 {ATOL_ALIGNED}"


def test_T06_leakage_error_is_bounded_on_both_sides():
    """
    【為什麼】真實世界的頻率幾乎不會剛好對齊 bin，矩形窗下能量必然
        洩漏到鄰近 bin——陷波後的還原「不可能」完美。這條測試的存在
        目的就是把這個物理事實釘進判準：
        - 上限擋掉「濾波器沒做事／做錯事」；
        - 下限擋掉「偷改參數成對齊 bin 讓誤差歸零」的作弊。
        雙邊界限由失敗模式校準（數據見 conftest.py 的 RTOL_LEAKY
        註解）：正確 0.116、部分修復 0.179、no-op 0.283、
        濾錯目標 0.755、作弊對齊 ~1e-15。窗 (0.02, 0.16) 唯一放行
        正確實作。
    【測什麼】f_main=137, f_noise=311, N=256, fs=1000（皆不對齊
        bin），陷波 311 Hz 後：
        RTOL_LEAK_MIN * A < rmse(還原, clean) < RTOL_LEAKY * A。
        禁止改動此組參數——改參數 = 改判準。
    """
    spec = make_spec(main_freq_hz=137.0, noise_freq_hz=311.0, n_samples=256)
    b = generate(spec)
    filtered = suppress_tone(forward(b.noisy, spec.sample_rate_hz), spec.noise_freq_hz)
    err = rmse(reconstruct(filtered), b.clean)
    lo = RTOL_LEAK_MIN * spec.main_amp
    hi = RTOL_LEAKY * spec.main_amp
    assert err > lo, (
        f"洩漏誤差 {err:.3e} 低於下限 {lo}——洩漏『必然存在』，"
        f"誤差趨近零代表測試參數被改成對齊 bin，或訊號生成有誤")
    assert err < hi, (
        f"洩漏誤差 {err:.4f} 超過上限 {hi}——陷波沒有移除雜訊主要能量"
        f"（no-op 為 0.283、只除一個 bin 為 0.179、濾錯目標為 0.755）")


def test_T12_suppress_does_not_mutate_input_and_output_differs():
    """
    【為什麼】協定 §2 規定 Spectrum 不可變：轉換一律回傳新物件。
        就地修改 coeffs 會讓「濾除前後對照圖」畫出兩條一樣的線，
        而且這種 bug 在單獨呼叫時完全無症狀，只在複用同一 Spectrum
        的流程裡爆炸——最難除錯的一類。
        同時檢查輸出「確實有變」：不然一個什麼都不做的 suppress
        也能通過不可變性檢查（空操作天然不可變）。
    【測什麼】呼叫 suppress_tone 後：(1) 原 spectrum.coeffs 與呼叫前
        的副本逐位元相同；(2) 回傳物件的 coeffs 與輸入不同（目標 bin
        已歸零）。
    """
    spec = make_spec()
    s = forward(generate(spec).noisy, spec.sample_rate_hz)
    before = s.coeffs.copy()
    out = suppress_tone(s, spec.noise_freq_hz)
    assert_allclose(s.coeffs, before, atol=0, rtol=0,
                    err_msg="輸入 Spectrum 被就地修改，違反不可變性契約")
    assert not np.array_equal(out.coeffs, before), \
        "輸出與輸入完全相同——suppress 是 no-op？"
