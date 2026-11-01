import numpy as np
import pytest

from engine.features import (FEATURE_NAMES, WINDOW_STAT_NAMES, BlinkDetector, PersonalBaseline,
                             extract_frame_features, summarise_window, vector)
from engine.features import face_features as ff
from engine.storage import Database, StorageError


def fake_landmarks(eye_open=0.3, mouth_open=0.05, yaw_shift=0.0, iris_dx=0.0):
    """Hand-built geometric face on a 478-point array (only indices used by the extractor are set)."""
    p = np.zeros((478, 3))
    def eye(e, cx, iris, sign):
        w = 0.06
        p[e["outer"], :2] = (cx - sign * w, 0.4); p[e["inner"], :2] = (cx + sign * w, 0.4)
        h = eye_open * 2 * w / 2
        for k in ("upper1", "upper2"): p[e[k], :2] = (cx, 0.4 - h)
        for k in ("lower1", "lower2"): p[e[k], :2] = (cx, 0.4 + h)
        p[iris, :2] = (cx + iris_dx * w, 0.4)
    eye(ff.L_EYE, 0.38, ff.L_IRIS, -1); eye(ff.R_EYE, 0.62, ff.R_IRIS, 1)
    for i in ff.L_BROW + ff.R_BROW: p[i, :2] = (0.4, 0.33)
    p[ff.L_BROW_INNER, :2] = (0.46, 0.34); p[ff.R_BROW_INNER, :2] = (0.54, 0.34)
    p[ff.MOUTH_UP, :2] = (0.5, 0.65); p[ff.MOUTH_LOW, :2] = (0.5, 0.65 + mouth_open)
    p[ff.MOUTH_L, :2] = (0.44, 0.65); p[ff.MOUTH_R, :2] = (0.56, 0.65)
    p[ff.NOSE_TIP, :2] = (0.5 + yaw_shift, 0.52); p[ff.CHIN, :2] = (0.5, 0.8); p[ff.FOREHEAD, :2] = (0.5, 0.25)
    p[ff.CHEEK_L, :2] = (0.3, 0.5); p[ff.CHEEK_R, :2] = (0.7, 0.5)
    return p


def test_feature_extraction_responds_to_real_geometry():
    base = extract_frame_features(fake_landmarks())
    assert set(base) == set(FEATURE_NAMES)
    wide = extract_frame_features(fake_landmarks(eye_open=0.4))
    assert wide["ear_left"] > base["ear_left"]
    mouth = extract_frame_features(fake_landmarks(mouth_open=0.12))
    assert mouth["mouth_open"] > base["mouth_open"] * 2
    turned = extract_frame_features(fake_landmarks(yaw_shift=0.1))
    assert turned["yaw"] > 15 and abs(base["yaw"]) < 1e-6
    looking = extract_frame_features(fake_landmarks(iris_dx=0.4))
    assert looking["iris_x_left"] > 0.3


def test_rejects_bad_landmarks():
    with pytest.raises(ValueError):
        extract_frame_features(np.zeros((100, 3)))


def test_blink_detector_separates_involuntary_and_deliberate():
    b = BlinkDetector()
    events, t = [], 0.0
    def run(ear, dur):
        nonlocal t
        for _ in range(int(dur * 30)):
            t += 1 / 30
            e = b.update(ear, t)
            if e: events.append(e)
    run(0.3, 1); run(0.05, 0.2); run(0.3, 0.2); run(0.05, 0.9); run(0.3, 0.2)
    assert [e.deliberate for e in events] == [False, True]


def test_baseline_welford_matches_numpy_and_roundtrips():
    rng = np.random.default_rng(0)
    data = rng.normal(2.0, 0.5, (300, len(FEATURE_NAMES)))
    bl = PersonalBaseline()
    for row in data: bl.update(row)
    assert bl.is_ready()
    np.testing.assert_allclose(bl.mean, data.mean(0), atol=1e-9)
    np.testing.assert_allclose(bl.std, data.std(0, ddof=1), atol=1e-9)
    z = bl.zscore(data[0])
    assert z.shape == (len(FEATURE_NAMES),)
    again = PersonalBaseline.from_dict(bl.to_dict())
    np.testing.assert_allclose(again.mean, bl.mean)


def test_window_summary_shape_and_slope():
    t = np.linspace(0, 2, 40)
    frames = np.zeros((40, len(FEATURE_NAMES))); frames[:, 0] = t  # ramp in feature 0
    s = summarise_window(frames, t, blink_count=2)
    assert s.shape == (len(WINDOW_STAT_NAMES),)
    assert s[4] == pytest.approx(1.0)  # slope of feature 0
    assert s[-3] == 2 and s[-2] == pytest.approx(1.0)
    with pytest.raises(ValueError):
        summarise_window(frames[:2], t[:2])


def test_storage_settings_logs_and_personal_data_deletion(tmp_path):
    db = Database(tmp_path / "oracle.db")
    db.set_setting("dwell_s", 1.2); db.set_setting("dwell_s", 1.5)
    assert db.get_setting("dwell_s") == 1.5 and db.get_setting("missing", 7) == 7
    db.log_safety_event(1.0, "stop", "user_shortcut")
    db.log_action("{}", "executed", "ok", 2)
    db.log_interaction("notepad.exe", "k", "Button", "click", "confirmed", 0.7)
    db.execute("INSERT INTO sessions(id, started_at, kind) VALUES('s1', 1, 'choice')")
    counts = db.delete_personal_data()
    assert counts["sessions"] == 1 and counts["interactions"] == 1
    assert db.query("SELECT COUNT(*) FROM interactions")[0][0] == 0
    assert db.query("SELECT COUNT(*) FROM safety_events")[0][0] == 1  # safety log preserved
    assert db.get_setting("dwell_s") == 1.5  # settings are not personal data
    db.close()
    assert Database(tmp_path / "oracle.db").get_setting("dwell_s") == 1.5  # persisted


def test_storage_errors_are_wrapped(tmp_path):
    db = Database()
    with pytest.raises(StorageError):
        db.execute("SELECT * FROM nope")
    bad = tmp_path / "bad.db"; bad.write_bytes(b"not a sqlite file" * 100)
    with pytest.raises(StorageError):
        Database(bad)
