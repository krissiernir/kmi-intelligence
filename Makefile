PYTHON ?= python3

.PHONY: init run fetch parse kvik wiki-films producers klapptre imdb-datasets imdb-verify imdb-setup imdb-enrich imdb-resolve build packs health embed embed-setup rag-search publish mcp mcp-setup all

init:           ## install dashboard deps (streamlit/pandas) into the active env
	$(PYTHON) -m pip install -r requirements.txt

# --- knowledge base pipeline (see docs/ARCHITECTURE.md) ---
build:          ## curated/*.json (+ data/raw/imdb_full fold) -> build/kmi.db (validates provenance)
	$(PYTHON) -m src.kmi_intelligence.compile

parse:          ## raw úthlutanir PDFs -> data/staged/allocations.json
	$(PYTHON) -m src.kmi_intelligence.ingest.parse_uthlutanir

kvik:           ## ingest kvikmyndir.is Icelandic SERIES -> data/staged/productions_series.json
	$(PYTHON) -m src.kmi_intelligence.ingest.kvikmyndir

wiki-films:     ## ingest Wikipedia Icelandic FILMS -> data/staged/productions_films.json
	$(PYTHON) -m src.kmi_intelligence.ingest.wikipedia_films

producers:      ## ingest SÍK member companies (producers.is félagaskrá) -> Zone 2 company entities
	$(PYTHON) -m src.kmi_intelligence.ingest.producers_is

klapptre:       ## Zone 3: Klapptré fact articles -> data/raw/klapptre/ (KMI_CATS=all for whole site)
	$(PYTHON) -m src.kmi_intelligence.ingest.klapptre

imdb-datasets:  ## FALLBACK: principal cast/crew from official IMDb bulk datasets -> data/raw/imdb/
	$(PYTHON) -m src.kmi_intelligence.ingest.imdb datasets

imdb-verify:    ## validate our tconsts against IMDb title.basics -> data/raw/imdb/verify.json
	$(PYTHON) -m src.kmi_intelligence.ingest.imdb verify

imdb-setup:     ## one-time: py3.12 venv + imdbinfo (needs uv) for enrich/resolve
	uv venv --python 3.12 .venv-imdb
	VIRTUAL_ENV=.venv-imdb uv pip install imdbinfo

imdb-enrich:    ## PRIMARY: full IMDb credits (crew/companies/box-office) -> data/raw/imdb_full/ (folded by build)
	PYTHONPATH=src .venv-imdb/bin/python -m kmi_intelligence.ingest.imdb enrich

imdb-resolve:   ## find tconsts for catalog titles lacking one -> data/curated/imdb_links.json
	PYTHONPATH=src .venv-imdb/bin/python -m kmi_intelligence.ingest.imdb resolve

packs:          ## build/kmi.db -> build/prompt_packs/
	$(PYTHON) -m src.kmi_intelligence.packs

health:         ## data-health cockpit -> build/HEALTH.md (coverage, queues, drift vs last run)
	$(PYTHON) -m src.kmi_intelligence.health

EMBED_PY ?= .venv-rag/bin/python
EMBED_BACKEND ?= local        # local | hash | openai | voyage

embed-setup:    ## one-time: py3.12 venv + sentence-transformers (needs uv)
	uv venv --python 3.12 .venv-rag
	uv pip install --python .venv-rag sentence-transformers

embed:          ## build/kmi.db -> build/embeddings/ (RAG; local multilingual-e5 by default)
	PYTHONPATH=src $(EMBED_PY) -m kmi_intelligence.rag embed --backend $(EMBED_BACKEND)

rag-search:     ## SEARCH="..." -> top-k semantic results
	PYTHONPATH=src $(EMBED_PY) -m kmi_intelligence.rag search "$(SEARCH)" --backend $(EMBED_BACKEND)

publish: parse build packs   ## rebuild DB + regenerate the committed export/ for other projects
	@echo "export/ refreshed — point other projects at export/kmi_full.md|.json or kmi_context.md"

mcp-setup:      ## one-time: add the MCP SDK to .venv-rag
	uv pip install --python .venv-rag mcp

mcp:            ## run the MCP server (stdio) for live querying from MCP clients
	PYTHONPATH=src .venv-rag/bin/python -m kmi_intelligence.mcp_server

all: parse build packs embed

UI_PY ?= .venv/bin/python

run:            ## launch the producer dashboard (Streamlit) over build/kmi.db
	$(UI_PY) -m streamlit run app/streamlit_app.py
