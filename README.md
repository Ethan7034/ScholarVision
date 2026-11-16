[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-Containerized-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)
[![VLM](https://img.shields.io/badge/VLM-Multimodal-FF6F00?style=flat-square&logo=openai&logoColor=white)]()
[![arXiv](https://img.shields.io/badge/Data_Source-arXiv-B31B1B?style=flat-square&logo=arxiv&logoColor=white)](https://arxiv.org/)

# 🏛️ Scholar Vision

**An Agentic Multimodal Academic Pipeline.**

## 💡 About This Project
Scholar Vision is a cloud-native multimodal agent designed for automated academic paper retrieval and deep chart/data analysis. Unlike traditional text-based search engines, Scholar Vision utilizes Vision-Language Models (VLM) and Agent Orchestration to "read" complex scientific figures, extracting structured insights from unstructured academic PDFs.

## 🏗️ System Architecture (8-Tier Cloud-Native Design)

The system is designed with a highly decoupled 8-tier microservices architecture to handle heavy multimodal data loads and ensure high availability.

### 1. 🌐 Presentation Layer (Frontend)
*   Native Web UI for user interaction, multimodal rendering, and displaying extracted academic insights.

### 2. 🛡️ Security & Gateway Layer (Traffic Control)
*   **Inbound**: API Rate Limiting (WAF), JWT Authentication for secure access.
*   **Outbound**: Proxy pool rotation and User-Agent spoofing to bypass anti-scraping mechanisms when fetching external data.

### 3. ⚙️ Business Logic Layer (API)
*   Built with **FastAPI** and **Asyncio** for high-concurrency asynchronous task scheduling and RESTful routing.

### 4. 🧠 Agent Orchestration Layer (The Brain) 
*   Utilizes Agent frameworks (e.g., LangChain) to autonomously plan task flows. It decides whether to trigger text summarization, VLM image parsing, or both based on the user's complex academic query.

### 5. 🤖 AI & VLM Processing Layer (Intelligence)
*   **Text**: LLM integration (e.g., GLM-4) for abstract summarization.
*   **Vision**: VLM integration (e.g., GLM-4V) for parsing charts and tables.
*   **Queue**: RabbitMQ / Redis queue for peak shaving and rate-limit prevention.

### 6. ✂️ Parsing & Extraction Layer (Data Processing)
*   Advanced PDF parsing pipelines (**PyMuPDF**) to strictly separate text blocks from visual elements (charts, figures).

### 7. 💾 Data & Cache Layer (Storage)
*   **Redis**: For caching hot queries and recent analysis results.
*   **PostgreSQL/MongoDB**: For structured storage of parsed academic data and text embeddings.

### 8. 🐳 Infrastructure & Deployment Layer (Environment)
*   Fully containerized via **Docker** for environment isolation.
*   **Cloudflare Tunnel** for secure, out-of-the-box network exposure and local deployment testing.

## 🛠️ Tech Stack
*   **Backend**: Python, FastAPI, Asyncio, PyMuPDF
*   **AI/ML**: VLM (GLM-4V / LLaVA), Agent Frameworks (LangChain), LLM APIs
*   **Infrastructure**: Docker, Cloudflare Tunnel, Microservices
*   **Data Source**: arXiv API, Semantic Scholar API

---
*Note: The foundational microservices architecture and cloud-native deployment templates are migrated and upgraded from my previous project, `News-Retriever V2.0`, to support heavy multimodal workloads.*