# -*- coding: utf-8 -*-
"""
tests/test_properties.py — 性質測試（T-03, T-08，hypothesis）

例子型測試只驗證「這幾組輸入對」；性質測試驗證「數學恆等式對
任意輸入都成立」。hypothesis 會自動生成上百組輸入（含它擅長找的
邊角案例），並在失敗時自動縮小到最簡反例。

derandomize=True：每次執行生成相同案例序列，符合協定 §5.4
「不得使用未固定 seed 的亂數」——agent 自我修正迴圈需要確定性。
"""
import numpy as np
import pytest
from numpy.testing import assert_allclose
from hypothesis import given, settings, strategies as st
from hypothesis.extra.numpy import arrays

from ifft_sim.core.spectrum import forward
from tests.conftest import RTOL_EXACT, ATOL_EXACT, ATOL_ALIGNED

# 元素界限 |x| <= 10：夠大到暴露尺度問題，又不至於讓 float64
# 累積誤差本身淹沒判準。
_ELEMS = st.floats(min_value=-10.0, max_value=10.0,
                   allow_nan=False, allow_infinity=False, width=64)


@given(x=arrays(np.float64, shape=st.integers(8, 200), elements=_ELEMS))
@settings(deadline=None, derandomize=True, max_examples=100)
def test_T03_parseval_single_sided(x):
    """
    【為什麼】Parseval 定理（時域能量 == 頻域能量）是抓「正規化錯誤」
        的唯一手段。往返測試 T-01 抓不到這種 bug：若 forward 偷偷
        乘了 1/N、reconstruct 再乘回 N，往返照樣是恆等映射，但頻譜
        數值全錯、band_energy 全錯。Parseval 把頻域數值釘死在絕對
        尺度上。
        單邊（rfft）版本的權重是最容易寫錯的地方：中間 bin 因為
        代表共軛對要乘 2，DC 不乘，N 為偶數時 Nyquist bin 也不乘。
        這正是協定警告過「AI 常直接套雙邊公式」的陷阱——所以這條
        由 hypothesis 對隨機長度（含奇偶）驗證。
    【測什麼】對任意 8<=N<=200、|x|<=10 的實數訊號：
        Σx² == (1/N)(|C0|² + 2Σ中間|Ck|² + [N偶] |C_last|²)，
        相對容差 RTOL_EXACT (1e-9)。
        用相對而非絕對容差的理由見 conftest.py。
    """
    n = len(x)
    c = forward(x, 1000.0).coeffs
    mags2 = np.abs(c) ** 2
    lhs = float(np.sum(x * x))
    if n % 2 == 0:
        rhs = (mags2[0] + 2.0 * float(np.sum(mags2[1:-1])) + mags2[-1]) / n
    else:
        rhs = (mags2[0] + 2.0 * float(np.sum(mags2[1:]))) / n
    assert lhs == pytest.approx(rhs, rel=RTOL_EXACT, abs=ATOL_EXACT), (
        f"Parseval 不成立 (N={n}): 時域能量 {lhs:.9g} != 頻域能量 {rhs:.9g}"
        f"——檢查 forward 的正規化，以及單邊頻譜的 2 倍權重")


@given(data=st.data())
@settings(deadline=None, derandomize=True, max_examples=100)
def test_T08_forward_is_linear(data):
    """
    【為什麼】FFT 是線性變換：F(ax+by) == aF(x)+bF(y)。任何在
        forward 裡動手腳的行為——加窗、去均值、削波、依訊號內容
        自動縮放——都會破壞線性。這些「好心的預處理」單看輸出很難
        發現，但會讓濾除數學整個歪掉。線性測試一網打盡。
    【測什麼】隨機長度 N、隨機係數 |a|,|b|<=4、隨機訊號 |x|,|y|<=1：
        forward(a*x+b*y).coeffs ≈ a*forward(x).coeffs + b*forward(y).coeffs，
        rtol=RTOL_EXACT，atol=ATOL_ALIGNED（近零 bin 的絕對誤差地板）。
    """
    n = data.draw(st.integers(8, 128))
    elems = st.floats(min_value=-1.0, max_value=1.0,
                      allow_nan=False, allow_infinity=False, width=64)
    coef = st.floats(min_value=-4.0, max_value=4.0,
                     allow_nan=False, allow_infinity=False, width=64)
    x = data.draw(arrays(np.float64, n, elements=elems))
    y = data.draw(arrays(np.float64, n, elements=elems))
    a = data.draw(coef)
    b = data.draw(coef)
    lhs = forward(a * x + b * y, 1000.0).coeffs
    rhs = a * forward(x, 1000.0).coeffs + b * forward(y, 1000.0).coeffs
    assert_allclose(lhs, rhs, rtol=RTOL_EXACT, atol=ATOL_ALIGNED,
                    err_msg="forward 非線性——是否有加窗、去均值或自動縮放等預處理？")
