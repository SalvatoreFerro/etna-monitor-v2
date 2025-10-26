import math

import pytest

from alerts.engine import AlertComputation, compute_moving_average, evaluate_threshold


def test_compute_moving_average_basic():
    values = [1, 2, 3, 4, 5]
    assert math.isclose(compute_moving_average(values, window=3), 4.0)
    assert math.isclose(compute_moving_average(values, window=5), 3.0)


def test_compute_moving_average_invalid_window():
    with pytest.raises(ValueError):
        compute_moving_average([1, 2, 3], window=0)


def test_evaluate_threshold_triggered():
    result = evaluate_threshold([1, 2, 3, 6], window=3, threshold=3.5)
    assert isinstance(result, AlertComputation)
    assert result.triggered is True
    assert math.isclose(result.moving_average, 3.6666666666, rel_tol=1e-6)
    assert result.latest_value == 6
    assert result.sample_size == 3


def test_evaluate_threshold_not_triggered_with_insufficient_data():
    result = evaluate_threshold([1, 1], window=5, threshold=2)
    assert result.triggered is False
    assert result.moving_average == pytest.approx(1.0)
    assert result.sample_size == 2


def test_evaluate_threshold_no_data():
    result = evaluate_threshold([], window=3, threshold=1.5)
    assert result.triggered is False
    assert result.moving_average is None
    assert result.latest_value is None
    assert result.sample_size == 0
