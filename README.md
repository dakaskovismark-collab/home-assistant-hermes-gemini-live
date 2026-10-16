# 🎙️ NeuroOutpost: Autonomous Real-Time Voice Assistant
### Home Assistant + Hermes Agent + Google Gemini Live API (Wyoming Protocol)

🌐 **Language / Язык:** [🇬🇧 English](#-english-documentation) | [🇷🇺 Русский](#-документация-на-русском)

---

<a name="-english-documentation"></a>
# 🇬🇧 English Documentation

An open-source hardware voice terminal ("cube") project with ultra-low response latency (~300 ms), streaming PCM audio over WebSocket (`v6.6`), long-term conversational memory, and direct smart home entity control via the **Model Context Protocol (MCP)**.

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
* **Network Ports:**
  * `10300/TCP` — Wyoming Bridge (`gemini_live_asr` / `gemini_live_tts`).
  * `8642/TCP` — Hermes Agent Gateway API.
  * `8123/TCP` — Home Assistant instance.

---

## 🚀 2. Step 1: Deploying the Wyoming Bridge (`bridge.py`)

The hybrid bridge captures raw 16kHz PCM audio from the voice cube over the Wyoming protocol, filters out clicks/silence with a built-in Noise Gate (`< 20,000 bytes`), sends WAV in-memory to **Gemini 3.1 Flash Lite** (REST API) for fast ASR, and streams 24kHz PCM chunks back in real time via **Gemini 2.5 Native Audio** (Bidi WebSocket Live API, voice `Orus`).

### 2.1. Environment Setup
```bash
# Clone the repository and create a virtual environment
git clone [https://github.com/dakaskovismark-collab/home-assistant-hermes-gemini-live.git](https://github.com/dakaskovismark-collab/home-assistant-hermes-gemini-live.git) /opt/wyoming_gemini_bridge
cd /opt/wyoming_gemini_bridge

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install wyoming websockets
```

### 2.2. Configuration (`.env`)
Create `/opt/wyoming_gemini_bridge/.env`:
```ini
GOOGLE_API_KEY="AIzaSyYourSecretGeminiApiKeyHere"
PORT=10300
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
journalctl -u wyoming-gemini.service -f
```

---

## 🧠 3. Step 2: Configuring Hermes Agent & MCP Server

Hermes acts as the logical brain: it processes intent, maintains long-term conversation context, and executes smart home tool calls via MCP.

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

| Pipeline Role | Model ID in Code | Protocol | Audio / Limits |
| :--- | :--- | :--- | :--- |
| **Hearing (ASR)** | `gemini-3.1-flash-lite` | REST API (`v1beta`) | 16 kHz WAV in RAM, high RPM/RPD quota |
| **Voice (TTS)** | `models/gemini-2.5-flash-native-audio-latest` | Bidi WebSocket (`v1alpha`) | 24 kHz PCM stream (`1024B` chunks, voice `Orus`), 1M TPM |
| **Logic (LLM)** | `gemini-2.5-flash` | Hermes Native Engine | 15 RPM / 1M TPM / 1500 RPD |

### 4.2. System Prompt for Extended OpenAI Conversation
Set the following system prompt in your Home Assistant conversation agent settings:
```text
You are a smart home voice assistant. Reply briefly and concisely, without bullet points or Markdown formatting, as your response is read aloud directly via TTS.
If asked to control a device, first call the appropriate Home Assistant function via the MCP server, then confirm the action in a single short sentence.
```

### 4.3. Building the Assistant in Home Assistant
1. **Wyoming:** Go to **Settings → Devices & Services → Add Integration → Wyoming Protocol** (Host: `127.0.0.1`, Port: `10300`). This registers `gemini_live_asr` and `gemini_live_tts` (voice `Orus`).
2. **LLM:** Add **Extended OpenAI Conversation**:
   * **Server URL:** `http://127.0.0.1:8642/v1`
   * **API Key:** `dummy-key`
   * **Model:** `hermes-agent`
3. **Assistant Pipeline:** Go to **Settings → Voice Assistants** and assemble the pipeline:
   * **STT (Speech-to-Text):** `gemini_live_asr`
   * **Conversation Agent:** `Extended OpenAI Conversation`
   * **TTS (Text-to-Speech):** `gemini_live_tts` (Voice: `Orus`)

---

## 🛠️ 5. Troubleshooting (FAQ & Known Issues)

* **Q1: Why use `gemini-2.5-flash-native-audio-latest` for TTS instead of newer preview live models?**
  * **Answer:** Some experimental live models have a strict 65K TPM quota, which burns out in 2–3 audio turns (`429 Too Many Requests`). The `2.5 Native Audio` model provides a **1,000,000 TPM** quota and supports instant 1024-byte PCM chunk streaming (`process_tts_stream`), preventing pipeline timeouts on long responses.
* **Q2: Why does `process_tts_stream` have a 2-attempt retry loop?**
  * **Answer:** Network flaps to Google's WebSocket endpoint can occasionally cause handshake timeouts. The built-in retry automatically reconnects after 2 seconds without dropping the Home Assistant session.
* **Q3: Error `sqlite3.ProgrammingError: SQLite objects created in a thread...`**
  * **Answer:** Background workers in Hermes access the `memohood` SQLite database created in the main thread. Run the `sed` command from **Step 3.3** (`check_same_thread=False`).
* **Q4: Assistant triggers on background room noise or clicks**
  * **Answer:** `bridge.py` includes a software Noise Gate (`if len(pcm_data) < 20000: return ""`). Any audio shorter than ~0.6 seconds (at 16,000 Hz, 16-bit mono) is dropped before hitting the REST API, saving your daily ASR quota.

---
---

<a name="-документация-на-русском"></a>
# 🇷🇺 Документация на русском

Проект аппаратного голосового терминала («кубика») с ультранизкой задержкой отклика (~300 мс), потоковой отдачей звука (`v6.6`), долговременной памятью диалогов и прямым управлением сущностями умного дома через **Model Context Protocol (MCP)**.

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
* **Сетевые порты:**
  * `10300/TCP` — Шлюз Wyoming Bridge (`gemini_live_asr` / `gemini_live_tts`).
  * `8642/TCP` — Hermes Agent Gateway API.
  * `8123/TCP` — Доступ к инстансу Home Assistant.

---

## 🚀 2. Шаг 1: Поднятие шлюза Wyoming Bridge (`bridge.py`)

Гибридный шлюз принимает входящий аудиопоток (16 кГц PCM) с кубика по протоколу Wyoming, отсекает щелчки и короткие шумы встроенным Noise Gate (`< 20 000 байт`), упаковывает звук в WAV прямо в RAM для мгновенного распознавания через **Gemini 3.1 Flash Lite** (REST API), а ответы синтезирует потоком (чанки по `1024 байта`, 24 кГц PCM, голос `Orus`) через **Gemini 2.5 Native Audio** (WebSocket Live API).

### 2.1. Установка и настройка окружения
```bash
# Клонирование и создание виртуального окружения
git clone [https://github.com/dakaskovismark-collab/home-assistant-hermes-gemini-live.git](https://github.com/dakaskovismark-collab/home-assistant-hermes-gemini-live.git) /opt/wyoming_gemini_bridge
cd /opt/wyoming_gemini_bridge

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install wyoming websockets
```

### 2.2. Конфигурация (`.env`)
Создайте файл `/opt/wyoming_gemini_bridge/.env`:
```ini
GOOGLE_API_KEY="AIzaSyYourSecretGeminiApiKeyHere"
PORT=10300
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

Запустите службу и проверьте лог:
```bash
systemctl daemon-reload
systemctl enable --now wyoming-gemini.service
journalctl -u wyoming-gemini.service -f
```

---

## 🧠 3. Шаг 2: Настройка Hermes Agent & MCP Server

Hermes выступает логическим мозгом: он обрабатывает смысл запроса, хранит контекст разговоров и выполняет вызовы инструментов умного дома через MCP.

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

| Роль в тракте | Идентификатор модели в коде | Протокол взаимодействия | Параметры и лимиты |
| :--- | :--- | :--- | :--- |
| **Уши (ASR)** | `gemini-3.1-flash-lite` | REST API (`v1beta`) | 16 кГц WAV в RAM, высокие лимиты RPM/RPD |
| **Голос (TTS)** | `models/gemini-2.5-flash-native-audio-latest` | Bidi WebSocket (`v1alpha`) | 24 кГц PCM стрим (чанки `1024B`, голос `Orus`), 1M TPM |
| **Логика (LLM)** | `gemini-2.5-flash` | Hermes Native Engine | 15 RPM / 1M TPM / 1500 RPD |

### 4.2. Системный промпт для Extended OpenAI Conversation
В настройках диалогового агента в Home Assistant задайте системную инструкцию:
```text
Ты — домашний голосовой ассистент. Отвечай кратко, емко, без списков с маркерами и форматирования Markdown, так как твой ответ сразу читается вслух через синтезатор речи.
Если тебя просят управлять устройством — сначала вызови соответствующую функцию Home Assistant через MCP-сервер, а затем подтверди результат одним предложением.
```

### 4.3. Сборка ассистента в Home Assistant
1. **Wyoming:** Перейдите в **Настройки → Устройства и службы → Добавить интеграцию → Wyoming Protocol** (Адрес: `127.0.0.1`, Порт: `10300`). Появятся сущности `gemini_live_asr` и `gemini_live_tts` (голос `Orus`).
2. **LLM:** Добавьте интеграцию **Extended OpenAI Conversation**:
   * **Server URL:** `http://127.0.0.1:8642/v1`
   * **API Key:** `dummy-key`
   * **Model:** `hermes-agent`
3. **Ассистент:** В разделе **Настройки → Голосовые ассистенты** соберите пайплайн:
   * **Распознавание речи (STT):** `gemini_live_asr`
   * **Разговорный агент:** `Extended OpenAI Conversation`
   * **Синтез речи (TTS):** `gemini_live_tts` (Голос: `Orus`)

---

## 🛠️ 5. Частые грабли (FAQ & Known Issues)

* **Q1: Почему для озвучки (TTS) выбрана модель `gemini-2.5-flash-native-audio-latest`?**
  * **Ответ:** У ряда новых превью-моделей Live API квота жестко ограничена 65K TPM, которые сгорают за 2–3 реплики (`429 Too Many Requests`). Модель `2.5 Native Audio` дает лимит **1,000,000 TPM**, а потоковая отдача чанками по 1024 байта (`process_tts_stream`) в `bridge.py` держит сессию Home Assistant «живой» на длинных ответах и начинает воспроизведение с первой секунды.
* **Q2: Зачем в `process_tts_stream` цикл на 2 попытки (`for attempt in range(2)`)?**
  * **Ответ:** Сетевые флапы до WebSocket-серверов Google иногда дают таймаут на этапе handshake. Двойной ретрай с паузой в 2 секунды маскирует микроразрывы без потери ответа ассистента.
* **Q3: Ошибка `sqlite3.ProgrammingError: SQLite objects created in a thread...`**
  * **Ответ:** Фоновые воркеры Hermes обращаются к базе памяти `memohood`, созданной в основном потоке. Обязательно выполните команду из **Шага 3.3** (`check_same_thread=False`).
* **Q4: Ассистент реагирует на посторонний шум или щелчки в комнате**
  * **Ответ:** В `bridge.py` встроен программный Noise Gate (`if len(pcm_data) < 20000: return ""`). Любой шум короче ~0.6 сек (16000 Гц * 2 байта = 32000 байт/сек) отбрасывается на лету и не тратит суточные квоты REST API.

---

## 📄 License & Links / Лицензия и ссылки

Distributed under the MIT License. / Проект распространяется под лицензией MIT.

* **YouTube:** [@neurooutpost](https://www.youtube.com/@neurooutpost)
