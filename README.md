[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-Containerized-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)
[![VLM](https://img.shields.io/badge/VLM-Multimodal-FF6F00?style=flat-square&logo=openai&logoColor=white)]()
[![arXiv](https://img.shields.io/badge/Data_Source-arXiv-B31B1B?style=flat-square&logo=arxiv&logoColor=white)](https://arxiv.org/)

# 🏛️ Scholar Vision

**An Agentic Multimodal Academic Pipeline.**

## 💡 About This Project
Scholar Vision is a cloud-native multimodal agent designed for automated academic paper retrieval and deep chart/data analysis. Unlike traditional text-based search engines, Scholar Vision utilizes Vision-Language Models (VLM) to "read" complex scientific figures, extracting structured insights from unstructured academic PDFs.

## ⚙️ Core Architecture & Features

*   **Cloud-Native Infrastructure**: Reuses the robust microservices architecture and high-availability backend templates from `News-Retriever V2.0`. Built with FastAPI and fully containerized via Docker for environment isolation.
*   **Automated PDF Parsing**: Employs advanced PDF parsing pipelines to extract both textual content and visual elements (charts, tables, figures) from academic documents.
*   **VLM-Powered Analysis**: Integrates state-of-the-art Vision-Language Models (e.g., GLM-4V) to interpret complex data representations and generate structural summaries.
*   **High-Concurrency Data Ingestion**: Fetches and processes data efficiently through official academic APIs (e.g., arXiv API), bypassing traditional anti-scraping limitations.

## 🛠️ Tech Stack
*   **Backend**: Python, FastAPI, Asyncio
*   **AI/ML**: VLM Integration (GLM-4V / LLaVA), NLP
*   **Deployment**: Docker, Cloudflare Tunnel, Microservices Architecture
*   **Data Source**: arXiv API, Semantic Scholar API

## 🚀 Status
Active Development. 
*(Note: The base engine is migrated and upgraded from the News-Retriever project to handle heavy multimodal data loads.)*
