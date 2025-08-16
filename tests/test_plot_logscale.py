from app.utils.plot import make_tremor_figure

def test_yaxis_is_log():
    fig = make_tremor_figure([1,2,3], [0.1, 1, 2], threshold=2.0)
    assert fig.to_dict()["layout"]["yaxis"]["type"] == "log"
