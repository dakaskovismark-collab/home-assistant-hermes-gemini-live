# 🎙️ NeuroOutpost: Autonomous Real-Time Voice Assistant
### Home Assistant + Hermes Agent + Google Gemini Live API (Wyoming Protocol)

🌐 **Language / Язык:** [🇬🇧 English](#-english-documentation) | [🇷🇺 Русский](#-документация-на-русском)

---

<a name="-english-documentation"></a>
# 🇬🇧 English Documentation

An open-source hardware voice terminal ("cube") project with ultra-low response latency (~300 ms), long-term conversational memory, and direct smart home entity control via the **Model Context Protocol (MCP)**.

---

## 📋 1. Prerequisites

Before starting, make sure your environment meets the following requirements:
* **Host OS:** Linux (Debian 12 / Ubuntu 22.04+ / Proxmox VE LXC).
* **Runtime:** Python 3.10+ with `venv`, `pip`, and `git` installed.
* **Home Assistant:** Version **2024.5.0** or newer (Supervised, OS, or Container).
  * Installed **HACS** (Home Assistant Community Store).
  * **Extended OpenAI Conversation** integration (available via HACS).
* **Google AI Studio API Key:**
  * Get a free API key at [aistudio.google.com](https://aistudio.google.com/).
  * Ensure your project has access to the Gemini 2.5 / 3.5 model family.
* **Network Ports:**
  * `10300/TCP` — Wyoming Bridge (ASR / TTS).
  * `8642/TCP` — Hermes Agent Gateway API.
  * `8123/TCP` — Home Assistant instance.

---

## 🚀 2. Step 1: Deploying the Wyoming Bridge

The bridge receives incoming audio streams over the Wyoming protocol, sends them for speech recognition (ASR), and synthesizes responses via a streaming WebSocket (TTS).

### 2.1. Environment Setup
```bash
# Clone the repository and create a virtual environment
git clone [https://github.com/dakaskovismark-collab/home-assistant-hermes-gemini-live.git](https://github.com/dakaskovismark-collab/home-assistant-hermes-gemini-live.git) /opt/wyoming_gemini_bridge
cd /opt/wyoming_gemini_bridge

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install websockets python-dotenv
```

### 2.2. Configuration (`.env`)
Create `/opt/wyoming_gemini_bridge/.env`:
```ini
GOOGLE_API_KEY="AIzaSyYourSecretGeminiApiKeyHere"
GEMINI_MODEL="gemini-3.5-flash-lite"
PORT=10300
BIND_ADDRESS="0.0.0.0"
```

### 2.3. Systemd Service
Create `/etc/systemd/system/wyoming-gemini.service`:
```ini
[Unit]
Description=Wyoming Gemini Live Bridge
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/wyoming_gemini_bridge
ExecStart=/opt/wyoming_gemini_bridge/venv/bin/python3 /opt/wyoming_gemini_bridge/bridge.py
Restart=always
RestartSec=3
EnvironmentFile=/opt/wyoming_gemini_bridge/.env

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
systemctl daemon-reload
systemctl enable --now wyoming-gemini.service
```

---

## 🧠 3. Step 2: Configuring Hermes Agent & MCP Server

Hermes acts as the logical brain: it processes intent, maintains long-term conversation context, and executes smart home tool calls.

### 3.1. Generate a Home Assistant Token
1. Open Home Assistant: **User Profile** (bottom-left corner) → **Security** tab.
2. Scroll down to **Long-Lived Access Tokens**.
3. Create a token named `hermes-agent` and copy it.

### 3.2. Hermes Gateway Configuration
Edit `/root/.hermes/config.yaml`:
```yaml
gateway:
  api_server:
    host: "0.0.0.0"
    port: 8642
    max_concurrent_runs: 10
    model_routes:
      hermes-agent:
        model: gemini-2.5-flash
        provider: google

providers:
  google:
    api_key: "${GOOGLE_API_KEY}"

mcp_servers:
  home_assistant:
    command: "python3"
    args: ["-m", "mcp_server_homeassistant"]
    env:
      HASS_HOST: "[http://192.168.1.100:8123](http://192.168.1.100:8123)"
      HASS_TOKEN: "Bearer eyJhbGciOiJIUz..."
```

### 3.3. CRITICAL: SQLite Multithreading Fix (Memohood)
By default, the memory plugin crashes when accessed from async worker threads. Apply this patch:
```bash
# Patch SQLite connection calls
sed -i 's/timeout=CONNECT_TIMEOUT_S/timeout=CONNECT_TIMEOUT_S, check_same_thread=False/g' /root/.hermes/plugins/memohood/db.py

# Restart the agent
systemctl --user restart hermes-gateway.service
```

---

## ⚡ 4. Step 3: Gemini Live API Integration & Pipeline Assembly

### 4.1. Model Specifications & Quotas

| Pipeline Role | Model ID | Protocol | Google Free Tier Limits |
| :--- | :--- | :--- | :--- |
| **Hearing (ASR)** | `gemini-3.5-flash-lite` | REST API | 15 RPM / 250K TPM / 500 RPD |
| **Voice (TTS)** | `models/gemini-2.5-flash-native-audio-latest` | Bidi WebSocket Live API | Unlimited RPM / 1M TPM |
| **Fallback TTS** | `gemini-3.8-flash-lite-tts` | REST API (Fallback) | 15 RPM / 250K TPM / 500 RPD |
| **Logic (LLM)** | `gemini-2.5-flash` | Hermes Native Engine | 15 RPM / 1M TPM / 1500 RPD |

### 4.2. System Prompt for Extended OpenAI Conversation
Set the following system prompt in your Home Assistant conversation agent settings:
```text
You are a smart home voice assistant. Reply briefly and concisely, without bullet points or Markdown formatting, as your response is read aloud directly via TTS.
If asked to control a device, first call the appropriate Home Assistant function via the MCP server, then confirm the action in a single short sentence.
```

### 4.3. Building the Assistant in Home Assistant
1. **Wyoming:** Add the **Wyoming Protocol** integration (Host: `127.0.0.1`, Port: `10300`). This exposes `gemini-asr` and `gemini-tts`.
2. **LLM:** Add **Extended OpenAI Conversation**:
   * **Server URL:** `http://127.0.0.1:8642/v1`
   * **API Key:** `dummy-key`
   * **Model:** `hermes-agent`
3. **Assistant Pipeline:** Go to **Settings → Voice Assistants** and create a pipeline:
   * **STT:** `gemini-asr`
   * **Conversation Agent:** `Extended OpenAI Conversation`
   * **TTS:** `gemini-tts`

---

## 🛠️ 5. Troubleshooting (FAQ & Known Issues)

* **Q1: Why does the Live API WebSocket drop with `429 Too Many Requests`?**
  * **Answer:** This happens if you use `gemini-3.8-live` instead of `gemini-2.5-flash-native-audio-latest`. The 3.8 models have a strict 65K TPM quota, which burns out in 2–3 audio exchanges. The `2.5 Native Audio` model provides a **1,000,000 TPM** quota.
* **Q2: Error `Upstream error from Sail Research: tool arguments invalid`**
  * **Answer:** Caused by third-party API aggregators (like OpenRouter) routing through cheap providers (e.g., Sail Research) that break Function Calling JSON schemas for Home Assistant.
  * **Fix:** Route Hermes requests directly to Google AI Studio (`provider: google`, model `gemini-2.5-flash`).
* **Q3: Error `sqlite3.ProgrammingError: SQLite objects created in a thread...`**
  * **Answer:** Background workers in Hermes access the `memohood` SQLite database created in the main thread. Run the `sed` command from **Step 3.3** (`check_same_thread=False`).
* **Q4: Assistant triggers on background room noise or clicks**
  * **Answer:** `bridge.py` includes a software Noise Gate. Audio chunks smaller than `20,000 bytes` are ignored so they don't consume daily ASR quota. Also check the microphone gain on your ESP32 board.

---
---

<a name="-документация-на-русском"></a>
# 🇷🇺 Документация на русском

Проект аппаратного голосового терминала («кубика») с ультранизкой задержкой отклика (~300 мс), долговременной памятью диалогов и прямым управлением сущностями умного дома через **Model Context Protocol (MCP)**.

---

## 📋 1. Предварительные требования (Prerequisites)

Перед началом убедитесь, что ваше окружение соответствует требованиям:
* **ОС Хоста:** Linux (Debian 12 / Ubuntu 22.04+ / Proxmox VE LXC).
* **Среда выполнения:** Python 3.10+ с модулями `venv`, `pip` и установленным `git`.
* **Home Assistant:** Версия **2024.5.0** или новее (Supervised, OS или Container).
  * Установленный **HACS** (Home Assistant Community Store).
  * Интеграция **Extended OpenAI Conversation** (доступна в HACS).
* **API Ключ Google AI Studio:**
  * Получить бесплатный ключ на [aistudio.google.com](https://aistudio.google.com/).
  * Убедитесь, что для вашего проекта доступен модельный ряд Gemini 2.5 / 3.5.
* **Сетевые порты:**
  * `10300/TCP` — Wyoming Bridge (ASR / TTS).
  * `8642/TCP` — Hermes Agent Gateway API.
  * `8123/TCP` — Доступ к инстансу Home Assistant.

---

## 🚀 2. Шаг 1: Поднятие шлюза Wyoming Bridge

Шлюз принимает входящий аудиопоток по протоколу Wyoming, передает его на распознавание (ASR), а ответы синтезирует через потоковый сокет (TTS).

### 2.1. Установка и настройка окружения
```bash
# Клонирование и создание окружения
git clone [https://github.com/dakaskovismark-collab/home-assistant-hermes-gemini-live.git](https://github.com/dakaskovismark-collab/home-assistant-hermes-gemini-live.git) /opt/wyoming_gemini_bridge
cd /opt/wyoming_gemini_bridge

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install websockets python-dotenv
```

### 2.2. Конфигурация (`.env`)
Создайте файл `/opt/wyoming_gemini_bridge/.env`:
```ini
GOOGLE_API_KEY="AIzaSyYourSecretGeminiApiKeyHere"
GEMINI_MODEL="gemini-3.5-flash-lite"
PORT=10300
BIND_ADDRESS="0.0.0.0"
```

### 2.3. Демонизация через systemd
Создайте службу `/etc/systemd/system/wyoming-gemini.service`:
```ini
[Unit]
Description=Wyoming Gemini Live Bridge
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/wyoming_gemini_bridge
ExecStart=/opt/wyoming_gemini_bridge/venv/bin/python3 /opt/wyoming_gemini_bridge/bridge.py
Restart=always
RestartSec=3
EnvironmentFile=/opt/wyoming_gemini_bridge/.env

[Install]
WantedBy=multi-user.target
```

Запустите и добавьте в автозагрузку:
```bash
systemctl daemon-reload
systemctl enable --now wyoming-gemini.service
```

---

## 🧠 3. Шаг 2: Настройка Hermes Agent & MCP Server

Hermes выступает логическим мозгом: он обрабатывает смысл запроса, хранит контекст разговоров и выполняет вызовы инструментов умного дома.

### 3.1. Получение токена Home Assistant
1. Перейдите в Home Assistant: **Профиль пользователя** (в левом нижнем углу) → вкладка **Безопасность**.
2. В самом низу найдите раздел **«Долгосрочные токены доступа»** (Long-Lived Access Tokens).
3. Создайте токен с именем `hermes-agent` и скопируйте его.

### 3.2. Конфигурация Hermes Gateway
Отредактируйте конфигурационный файл `/root/.hermes/config.yaml`:
```yaml
gateway:
  api_server:
    host: "0.0.0.0"
    port: 8642
    max_concurrent_runs: 10
    model_routes:
      hermes-agent:
        model: gemini-2.5-flash
        provider: google

providers:
  google:
    api_key: "${GOOGLE_API_KEY}"

mcp_servers:
  home_assistant:
    command: "python3"
    args: ["-m", "mcp_server_homeassistant"]
    env:
      HASS_HOST: "[http://192.168.1.100:8123](http://192.168.1.100:8123)"
      HASS_TOKEN: "Bearer eyJhbGciOiJIUz..."
```

### 3.3. КРИТИЧЕСКИ ВАЖНО: Фикс многопоточности SQLite (Memohood)
По умолчанию плагин памяти крашится при обращении из пула асинхронных потоков. Внесите исправление:
```bash
# Патчим вызовы подключения к SQLite
sed -i 's/timeout=CONNECT_TIMEOUT_S/timeout=CONNECT_TIMEOUT_S, check_same_thread=False/g' /root/.hermes/plugins/memohood/db.py

# Перезапускаем агент
systemctl --user restart hermes-gateway.service
```

---

## ⚡ 4. Шаг 3: Интеграция Gemini Live API и сборка пайплайна

### 4.1. Спецификация задействованных моделей

| Роль в тракте | Идентификатор модели в коде | Протокол взаимодействия | Лимиты Google Free Tier |
| :--- | :--- | :--- | :--- |
| **Слух (ASR)** | `gemini-3.5-flash-lite` | REST API | 15 RPM / 250K TPM / 500 RPD |
| **Голос (TTS)** | `models/gemini-2.5-flash-native-audio-latest` | Bidi WebSocket Live API | Unlimited RPM / 1M TPM |
| **Резерв TTS** | `gemini-3.8-flash-lite-tts` | REST API (Fallback) | 15 RPM / 250K TPM / 500 RPD |
| **Логика (LLM)** | `gemini-2.5-flash` | Hermes Native Engine | 15 RPM / 1M TPM / 1500 RPD |

### 4.2. Системный промпт для Extended OpenAI Conversation
В настройках диалогового агента в Home Assistant задайте системную инструкцию:
```text
Ты — домашний голосовой ассистент. Отвечай кратко, емко, без списков с маркерами и форматирования Markdown, так как твой ответ сразу читается вслух через синтезатор речи.
Если тебя просят управлять устройством — сначала вызови соответствующую функцию Home Assistant через MCP-сервер, а затем подтверди результат одним предложением.
```

### 4.3. Сборка ассистента в Home Assistant
1. **Wyoming:** Добавьте интеграцию **Wyoming Protocol** (Адрес: `127.0.0.1`, Порт: `10300`). Появятся сущности `gemini-asr` и `gemini-tts`.
2. **LLM:** Добавьте **Extended OpenAI Conversation**:
   * **Server URL:** `http://127.0.0.1:8642/v1`
   * **API Key:** `dummy-key`
   * **Model:** `hermes-agent`
3. **Ассистент:** В разделе **Настройки → Голосовые ассистенты** соберите пайплайн:
   * **STT:** `gemini-asr`
   * **Conversation Agent:** `Extended OpenAI Conversation`
   * **TTS:** `gemini-tts`

---

## 🛠️ 5. Частые грабли (FAQ & Known Issues)

* **Q1: Почему рвется WebSocket Live API (ошибка `429 Too Many Requests`)?**
  * **Ответ:** Это происходит, если вы пытаетесь использовать модель `gemini-3.8-live` вместо `gemini-2.5-flash-native-audio-latest`. У моделей 3.8 квота ограничена всего 65K TPM, что при передаче спектральных аудиочанков сгорает за 2–3 реплики. Модель `2.5 Native Audio` имеет лимит **1,000,000 TPM** и не упирается в потолок.
* **Q2: Ошибка `Upstream error from Sail Research: tool arguments invalid`**
  * **Ответ:** Ошибка возникает при использовании сторонних агрегаторов API (OpenRouter) и провайдеров дешевого хостинга моделей (Sail Research), у которых сломан парсинг Function Calling в JSON-схемах Home Assistant.
  * **Решение:** Направляйте запросы из Hermes напрямую в Google AI Studio (`provider: google`, модель `gemini-2.5-flash`).
* **Q3: Ошибка `sqlite3.ProgrammingError: SQLite objects created in a thread...`**
  * **Ответ:** Фоновые воркеры Hermes обращаются к базе памяти `memohood`, созданной в основном потоке. Обязательно выполните команду из **Шага 3.3** (`check_same_thread=False`).
* **Q4: Ассистент реагирует на посторонний шум или щелчки в комнате**
  * **Ответ:** В `bridge.py` встроен программный Noise Gate. Если длина аудиочанков меньше `20 000 байт`, пакет игнорируется и не тратит суточные запросы ASR. Проверьте чувствительность микрофона на стороне вашей платы ESP32.

---

## 📄 License & Links / Лицензия и ссылки

Distributed under the MIT License. / Проект распространяется под лицензией MIT.

* **YouTube:** [@neurooutpost](https://www.youtube.com/@neurooutpost)
