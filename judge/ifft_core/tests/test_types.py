# -*- coding: utf-8 -*-
"""
tests/test_types.py — 參數驗證測試（T-07）

【為什麼要測「拒絕」】
    模擬器的輸入來自 UI，使用者一定會輸入爛值。驗證層若有漏洞，
    爛值會往下滲，最後在 numpy 深處以看不懂的錯誤炸開（或更糟：
    默默算出錯的圖）。這裡逐條驗證協定 §4 的表：每一種爛值都
    必須在 SignalSpec 建構時，就以「正確的例外型別」被擋下。
"""
import pytest

from ifft_sim.core.types import (
    SignalSpec, InvalidParameterError, NyquistViolationError,
)
from tests.conftest import make_spec


# 協定 §4 驗證表，逐列展開。(欄位覆寫, 期望例外)
_CASES = [
    # 頻率必須為正
    (dict(main_freq_hz=0.0), InvalidParameterError),
    (dict(main_freq_hz=-5.0), InvalidParameterError),
    (dict(noise_freq_hz=0.0), InvalidParameterError),
    (dict(noise_freq_hz=-1.0), InvalidParameterError),
    # 取樣點數：下限與型別（bool 是 int 的子類別，必須明確擋掉——
    # isinstance(True, int) == True 是 Python 的陷阱）
    (dict(n_samples=7), InvalidParameterError),
    (dict(n_samples=0), InvalidParameterError),
    (dict(n_samples=512.0), InvalidParameterError),
    (dict(n_samples=True), InvalidParameterError),
    # 取樣率必須為正
    (dict(sample_rate_hz=0.0), InvalidParameterError),
    (dict(sample_rate_hz=-100.0), InvalidParameterError),
    # 振幅域
    (dict(main_amp=0.0), InvalidParameterError),
    (dict(main_amp=-1.0), InvalidParameterError),
    (dict(noise_amp=-0.1), InvalidParameterError),
    (dict(gaussian_sigma=-0.5), InvalidParameterError),
    # Nyquist：fs 必須「嚴格大於」2*max(f)。等於也不行——
    # fs == 2f 時對正弦波的取樣可能全落在零交越點上。
    (dict(main_freq_hz=60.0, noise_freq_hz=80.0, sample_rate_hz=100.0),
     NyquistViolationError),
    (dict(main_freq_hz=50.0, noise_freq_hz=30.0, sample_rate_hz=100.0),
     NyquistViolationError),  # fs == 2*f_main，邊界本身
]


@pytest.mark.parametrize("overrides,exc", _CASES,
                         ids=[str(c[0]) for c in _CASES])
def test_T07_invalid_parameters_are_rejected(overrides, exc):
    """
    【測什麼】每組爛參數建構 SignalSpec 都 raise 指定例外，
        且例外訊息非空（協定 §4：訊息必須含參數名與值）。
    """
    with pytest.raises(exc) as excinfo:
        make_spec(**overrides)
    assert str(excinfo.value), "例外訊息為空——除錯時等於瞎子"


def test_T07_validation_order_numeric_before_nyquist():
    """
    【為什麼】協定 §4 規定 Nyquist 檢查必須在其他數值檢查「之後」。
        沒有固定順序時，同時有兩種錯的輸入會依實作細節丟出不同
        例外，UI 的錯誤訊息就變成賭博。
    【測什麼】main_freq 非法「且」fs 違反 Nyquist 時，
        丟出的是 InvalidParameterError（數值檢查先攔到），
        不是 NyquistViolationError。
    """
    with pytest.raises(InvalidParameterError):
        make_spec(main_freq_hz=-60.0, sample_rate_hz=10.0)


def test_T07_nyquist_error_names_both_values():
    """
    【為什麼】Nyquist 違反是使用者最常踩到的錯，UI 直接顯示這個
        訊息（協定 §6.3）。訊息裡沒有「目前 fs」與「需求下限」，
        使用者就不知道往哪調。
    【測什麼】例外訊息同時包含 fs 值與 2*max(f) 值的字樣。
    """
    with pytest.raises(NyquistViolationError) as excinfo:
        make_spec(main_freq_hz=60.0, noise_freq_hz=80.0, sample_rate_hz=100.0)
    msg = str(excinfo.value)
    assert "100" in msg and "160" in msg, f"訊息缺少關鍵數值: {msg!r}"
