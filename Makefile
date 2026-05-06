PYTHON ?= python3

.PHONY: init seed test run

init:
	$(PYTHON) -m pip install -r requirements.txt

seed:
	$(PYTHON) -m src.kmi_intelligence.seed

test:
	$(PYTHON) -m pytest -q

run:
	streamlit run app/streamlit_app.py
