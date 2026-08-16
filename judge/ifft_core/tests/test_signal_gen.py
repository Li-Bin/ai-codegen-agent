# -*- coding: utf-8 -*-
"""
tests/test_signal_gen.py — 訊號生成測試（T-09）

【為什麼】所有下游測試（T-05, T-06）都以 generate() 的輸出為基準；
    生成端不可靠，整套判準跟著失效。這裡釘死兩件事：
    (1) 可重現性——同 seed 同輸出，這是 agent 自我修正迴圈與
        除錯的前提；
    (2) 疊加恆等式 noisy == clean + noise——之後所有「還原誤差」
        的計算都默認這條成立。
"""
import numpy as np
from numpy.testing import assert_allclose

from ifft_sim.core.signal_gen import generate
from tests.conftest import ATOL_EXACT, make_spec


def test_T09_same_seed_reproduces_exactly():
    """
    【測什麼】gaussian_sigma > 0 時，同 seed 兩次 generate 的
        noisy 逐位元相同（atol=0）。
    """
    spec = make_spec(gaussian_sigma=0.2, seed=42)
    b1, b2 = generate(spec), generate(spec)
    assert_allclose(b1.noisy, b2.noisy, atol=0, rtol=0,
                    err_msg="同 seed 結果不同——rng 沒有用 seed 建立，"
                            "或用了全域 np.random.* 而非 default_rng")


def test_T09_different_seeds_differ():
    """
    【為什麼】「同 seed 相同」單獨成立時有個退化解：白噪根本
        沒被加進去（永遠零，當然可重現）。這條把退化解堵掉。
    【測什麼】不同 seed 的 noisy 不逐點相同。
    """
    a = generate(make_spec(gaussian_sigma=0.2, seed=1))
    b = generate(make_spec(gaussian_sigma=0.2, seed=2))
    assert not np.array_equal(a.noisy, b.noisy), \
        "不同 seed 產出相同訊號——白噪未生效？"


def test_T09_superposition_identity_holds():
    """
    【測什麼】noisy == clean + noise，atol=ATOL_EXACT。
        含白噪與不含白噪兩種情形都要成立。
    """
    for spec in (make_spec(), make_spec(gaussian_sigma=0.3, seed=7)):
        b = generate(spec)
        assert_allclose(b.noisy, b.clean + b.noise, atol=ATOL_EXACT, rtol=0,
                        err_msg="noisy != clean + noise——疊加恆等式破裂")


def test_T09_time_axis_starts_at_zero_with_correct_step():
    """
    【為什麼】t 軸錯一個 offset 或 step，波形圖的 x 軸就是錯的，
        而且相位相關的一切計算跟著錯——但圖「看起來」還是很正常。
    【測什麼】t[0]==0、步長==1/fs、長度==N。
    """
    spec = make_spec()
    b = generate(spec)
    assert b.t[0] == 0.0
    assert len(b.t) == spec.n_samples
    assert_allclose(np.diff(b.t), 1.0 / spec.sample_rate_hz,
                    rtol=1e-12, atol=0,
                    err_msg="時間步長 != 1/fs")
