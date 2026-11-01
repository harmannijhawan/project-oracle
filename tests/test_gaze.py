import numpy as np
import pytest

from engine.gaze import (CalibratedEstimator, CalibrationError, DwellDetector, GazeCalibration,
                         GazeCursorPipeline, Monitor, OneEuroFilter, QualityInputs, QualityMonitor,
                         monitor_at, nine_point_targets)
from engine.safety import SafetyController, SafetyState

MON = Monitor("m", 0, 0, 1920, 1080, True)


def synth(n_rep=6, noise=0.003, seed=0):
    """Synthetic iris/head features with a mild non-linearity (stands in for webcam data)."""
    rng = np.random.default_rng(seed)
    targets = np.array(nine_point_targets())
    xs, ys = [], []
    for tx, ty in targets:
        for _ in range(n_rep):
            f = np.array([0.4 * tx - 0.2 + 0.05 * tx * ty, 0.3 * ty - 0.15 + 0.04 * tx ** 2, 0.1 * (tx - 0.5)])
            xs.append(f + rng.normal(0, noise, 3))
            ys.append([tx, ty])
    return np.array(xs), np.array(ys)


def test_nine_points_inside_screen():
    pts = nine_point_targets()
    assert len(pts) == 9 and all(0 < x < 1 and 0 < y < 1 for x, y in pts)


def test_calibration_recovers_mapping_and_reports_measured_error():
    f, t = synth()
    cal = GazeCalibration()
    report = cal.fit(f, t, (1920, 1080))
    assert report.loo_mean_error_px < 80  # on clean synthetic data
    est = CalibratedEstimator(cal).estimate(f[0])
    assert abs(est[0] - t[0][0]) < 0.05
    again = GazeCalibration.from_json(cal.to_json())
    assert again.predict(f[5]) == pytest.approx(cal.predict(f[5]))


def test_calibration_rejects_bad_input():
    f, t = synth()
    with pytest.raises(CalibrationError):
        GazeCalibration().fit(f[:10], t[:10], (1920, 1080))
    f2 = f.copy(); f2[0, 0] = np.nan
    with pytest.raises(CalibrationError):
        GazeCalibration().fit(f2, t, (1920, 1080))
    with pytest.raises(CalibrationError):
        GazeCalibration().predict(f[0])


def test_noisy_data_gives_larger_measured_error():
    clean = GazeCalibration().fit(*synth(noise=0.001), (1920, 1080))
    noisy = GazeCalibration().fit(*synth(noise=0.03), (1920, 1080))
    assert noisy.loo_mean_error_px > clean.loo_mean_error_px


def test_one_euro_reduces_jitter_but_follows_large_moves():
    rng = np.random.default_rng(1)
    f = OneEuroFilter(min_cutoff=0.5, beta=0.01)
    raw = 0.5 + rng.normal(0, 0.02, 120)
    out = [f(v, i / 30) for i, v in enumerate(raw)]
    assert np.std(out[30:]) < np.std(raw[30:]) * 0.6
    jump = [f(0.9, 4 + i / 30) for i in range(30)]
    assert jump[-1] > 0.8


def test_dwell_fires_once_then_cools_down_and_resets_on_move_or_tracking_loss():
    d = DwellDetector(duration_s=1.0, radius_px=30, cooldown_s=1.0)
    assert not d.update(100, 100, 0.0).fired
    assert d.update(105, 100, 0.5).progress == pytest.approx(0.5)
    assert d.update(105, 100, 1.0).fired
    assert not d.update(105, 100, 1.2).fired  # cooldown
    d.update(300, 300, 3.0)
    assert d.update(300, 300, 3.5).progress == pytest.approx(0.5)
    d.update(300, 300, 3.6, tracking_ok=False)
    assert d.update(300, 300, 3.7).progress == 0.0  # restarted after loss
    d.update(500, 500, 4.0)
    assert d.update(900, 900, 4.5).progress == 0.0  # moved away


def test_monitor_mapping_multi_monitor():
    right = Monitor("r", 1920, -200, 2560, 1440)
    assert monitor_at([MON, right], 2000, 10) is right
    assert monitor_at([MON, right], -5, 0) is None
    assert right.to_pixels(1.5, -1) == (1920 + 2559, -200)  # clamped
    assert MON.to_pixels(0.5, 0.5) == (round(0.5 * 1919), round(0.5 * 1079))


def test_quality_monitor():
    q = QualityMonitor()
    good = QualityInputs(True, 0.3, 3, 2, 0.4)
    assert q.update(good) > 0.9
    assert q.update(QualityInputs(False, 0, 0, 0, 0)) == 0.0
    assert q.update(QualityInputs(True, 0.3, 40, 0, 0.4)) == 0.0  # head turned away
    assert q.update(QualityInputs(True, 0.02, 0, 0, 0.4)) < 0.4  # eyes closed


def test_pipeline_pauses_on_sustained_loss_and_no_cursor_when_unreliable():
    clock = {"t": 0.0}
    safety = SafetyController(clock=lambda: clock["t"])
    f, t = synth()
    cal = GazeCalibration(); cal.fit(f, t, (1920, 1080))
    pipe = GazeCursorPipeline(CalibratedEstimator(cal), MON, safety)
    s = pipe.process(f[0], 0.9, 0.0)
    assert s is not None and 0 <= s.x < 1920
    for i in range(1, 8):
        clock["t"] = i * 0.5
        assert pipe.process(None, 0.0, clock["t"]) is None
    assert safety.state is SafetyState.AUTO_PAUSED
