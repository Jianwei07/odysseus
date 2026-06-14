# Getting Started with Odysseus

## 1. Prerequisites

You will need a few basic tools installed on your computer:

- **Docker Desktop**: Download and install Docker Desktop. Ensure the Docker app is running in the background.
- **Git**: Download and install Git.

## 2. Download and Launch

1. Open your terminal (or Command Prompt/PowerShell on Windows).

2. Clone the repository and navigate into the folder by running:

   ```bash
   git clone https://github.com/pewdiepie-archdaemon/odysseus.git
   cd odysseus
   ```

3. Prepare the environment file:

   ```bash
   cp .env.example .env
   ```

4. Start Odysseus with Docker:
   ```bash
   docker compose up -d --build
   ```

## 3. Log in and Set Up Your Account

1. Open your web browser and navigate to `http://localhost:7000`.

2. The first-time setup requires a temporary admin password. Find it in your terminal logs by running:

   ```bash
   docker compose logs | grep password
   ```

3. Log in using `admin` (or your defined username) and the temporary password.

4. Go to **Settings > Account** to update your password.

## 4. Connect AI Models

Odysseus requires AI models to function, which can either be local LLMs or external APIs.

- **Local model**: The easiest method is using Ollama. Download Ollama, pull a model (e.g., `ollama pull qwen2`), and add it in Odysseus via **Settings > Add Models > Local**, then enter your Ollama endpoint (`http://localhost:11434`).
- **Cloud APIs**: Connect external services like OpenAI, Anthropic, or DeepSeek by providing your API keys via **Settings > Add Models > API**.
