.PHONY: all start-services pull-models provision-classifier init-database lint

# Step 1: Environment variables provisioning
ifneq (,$(wildcard .env))
    include .env
    export $(shell sed 's/=.*//' .env)
endif

# Step 2: Service instantiation
start-services:
	@echo "[SERVICE INSTANTIATION] Initialization of Docker services initiated."
	@docker compose up -d >/dev/null 2>&1
	@echo "[SERVICE INSTANTIATION] Docker services successfully initialized."

# Step 3: Model synchronization
pull-models: start-services
	@echo "[MODEL SYNCHRONIZATION] Retrieval of required Ollama models initiated."
	@docker exec ollama ollama pull $(OLLAMA_REASONING_MODEL) >/dev/null 2>&1
	@echo "[MODEL SYNCHRONIZATION] Required Ollama models successfully retrieved."

# Step 4: Classifier provisioning
provision-classifier: pull-models
	@echo "[CLASSIFIER PROVISIONING] Acquisition of the distilled email classifier initiated."
	@uv run hf download $(HF_CLASSIFIER_REPO) --local-dir $(CLASSIFIER_LOCAL_DIR) >/dev/null 2>&1
	@docker exec ollama mkdir -p /models/email-classifier >/dev/null 2>&1
	@docker cp $(CLASSIFIER_LOCAL_DIR)/. ollama:/models/email-classifier >/dev/null 2>&1
	@docker exec -w /models/email-classifier ollama ollama create $(OLLAMA_CLASSIFIER_MODEL) -f Modelfile >/dev/null 2>&1
	@echo "[CLASSIFIER PROVISIONING] Distilled email classifier successfully registered within the model runtime."

# Step 5: Persistence layer initialization
init-database: start-services
	@echo "[PERSISTENCE INITIALIZATION] Creation of the relational schema initiated."
	@docker exec email_triage_api_service python -m src.persistence.migrate >/dev/null 2>&1
	@echo "[PERSISTENCE INITIALIZATION] Relational schema successfully created."

# Step 6: Static analysis
lint:
	@echo "[STATIC ANALYSIS] Linting of the application source initiated."
	@uv run ruff check src >/dev/null 2>&1
	@echo "[STATIC ANALYSIS] Linting of the application source successfully completed."

# Master target: full pipeline execution
all: start-services pull-models provision-classifier init-database
	@echo "[ALL] Complete environment initialization and model provisioning finalized."
