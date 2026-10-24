from pathlib import Path
from streamlit.testing.v1 import AppTest

def test_dashboard_load_and_qbr_generation():
    app=AppTest.from_file(str(Path(__file__).parents[1]/'app.py')).run(timeout=30)
    assert not app.exception
    assert app.metric[3].value=='PASS'
    app.button[0].click().run(timeout=30)
    assert not app.exception
    assert any('Cloud Finance Review' in m.value for m in app.markdown)

def test_invalid_date_range_has_clear_error():
    app=AppTest.from_file(str(Path(__file__).parents[1]/'app.py')).run(timeout=30)
    app.date_input[0].set_value('2026-09-30')
    app.date_input[1].set_value('2026-09-01')
    app.run(timeout=30)
    assert not app.exception
    assert any('Start is after end' in e.value for e in app.error)
