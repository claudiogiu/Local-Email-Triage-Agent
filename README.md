# Local Email Triage Agent via Ollama and LangGraph

## Introduction

This repository is designed for implementing an entirely local email triage system that classifies, prioritizes and drafts responses to incoming correspondence by adopting Ollama as the small-language-model runtime and LangGraph as the orchestration layer, integrating mailbox ingestion, distilled classification, deterministic priority signals and human-supervised action execution within a unified environment that preserves confidentiality by ensuring that no message content is transmitted to any remote inference endpoint.

Ollama provides the local execution engine for [distil-labs/distil-email-classifier](https://huggingface.co/distil-labs/distil-email-classifier), the distilled classification model, and for the reasoning model employed in prioritization and reply generation, while LangGraph supplies the durable orchestration primitives required to suspend the pipeline at each human approval gate, persist the intermediate state, and resume execution at the exact point of interruption once the operator has expressed a decision. The system is exposed through two cooperating services: a backend responsible for mailbox ingestion, model invocation and persistence, and a separate frontend that consumes the backend exclusively over its internal REST interface.

The system operates exclusively on newly received and unread correspondence, performs no implicit write operation on the mailbox, and requires explicit human authorization before the execution of any irreversible action.

## Getting Started

To set up the repository properly, follow these steps:

**1.** **Configure the Environment File**

- Initialize the environment configuration by copying the `.env.example` file template into the project root as `.env`:

  ```bash
  cp .env.example .env
  ```

- Assign valid values to all required variables. The mailbox credentials are optional in this file: a sign-in form is also available from the running interface, and either path stores or supplies the same application-specific password, which must never be the regular account password.

- The `DRY_RUN` variable, when enabled, suppresses every write operation on the mailbox regardless of the approvals granted, leaving classification and priority assessment fully observable without altering the mailbox state. It must remain disabled for the system to send, label, archive or mark messages for real.

**2.** **Execute the Service Provisioning with Makefile**

- The repository includes a **Makefile** that automates the initialization of all components required to run the local email triage system. It requires Docker Compose and `uv` on the host, since classifier provisioning downloads the distilled model through `uv run` before registering it inside the model runtime.

- Run the following command to start the complete service suite:

  ```bash
  make all
  ```

- This command sequentially performs the following operations:

  - Starts all required services using Docker Compose, ensuring that the backend, the frontend and the model runtime are correctly instantiated within the dedicated internal network.
  - Retrieves the reasoning model identified by the environment variable `OLLAMA_REASONING_MODEL`, employed for message prioritization and reply drafting.
  - Downloads the distilled classification model from the HuggingFace repository specified by `HF_CLASSIFIER_REPO` and registers it within the model runtime under the identifier declared in `OLLAMA_CLASSIFIER_MODEL`.
  - Creates the relational schema supporting the domain entities, the approval queue and the audit trail.

**3.** **Access the Interface**

- Once the services are running, the system is accessible at:

  - **Frontend, mailbox sign-in and triage interface:** `localhost:8080`
  - **Backend, Swagger UI for interactive docs:** `localhost:8000/docs`
  - **Message resources:** `api/v1/messages`
  - **Draft and transmission resources:** `api/v1/drafts`, `api/v1/sends`
  - **Mailbox credentials:** `api/v1/settings/mailbox-credentials`

- Both services are bound to the loopback interface and are therefore not reachable from the local network.


## License

This project is licensed under the **MIT License**, which allows for open-source use, modification, and distribution with minimal restrictions. For more details, refer to the file included in this repository.
