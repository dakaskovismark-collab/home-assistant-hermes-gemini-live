import json
import base64
import wave
import io
import os
import urllib.request
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.event import Event
from wyoming.server import AsyncEventHandler, AsyncTcpServer
from wyoming.asr import Transcript
from wyoming.tts import Synthesize
from wyoming.info import Describe, Info, AsrProgram, AsrModel, TtsProgram, TtsVoice, Attribution
import websockets

# ==========================================
#          НАСТРОЙКИ ШЛЮЗА
# ==========================================
# Ключ читается из окружения (экспортируется из /root/.env перед запуском)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
PORT = int(os.getenv("PORT", "10300"))

# 1. УШИ (ASR): Сверхбыстрая легковесная модель через REST API (большие лимиты)
REST_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key={GOOGLE_API_KEY}"

# 2. ГОЛОС (TTS): Нативная аудио-модель через WebSocket Live API
MODEL_TTS = "models/gemini-2.5-flash-native-audio-latest"
BIDI_URL = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent?key={GOOGLE_API_KEY}"


class BridgeEventHandler(AsyncEventHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.audio_buffer = bytes()
        self.is_recording = False

    async def handle_event(self, event: Event) -> bool:
        # Регистрация возможностей шлюза в Home Assistant
        if Describe.is_type(event.type):
            await self.write_event(
                Info(
                    asr=[
                        AsrProgram(
                            name="gemini_live_asr",
                            description="Gemini Flash Lite ASR",
                            attribution=Attribution(name="Google", url="https://google.com"),
                            installed=True,
                            version="1.0",
                            models=[
                                AsrModel(
                                    name="gemini",
                                    description="Gemini",
                                    attribution=Attribution(name="Google", url="https://google.com"),
                                    installed=True,
                                    version="1.0",
                                    languages=["ru"]
                                )
                            ]
                        )
                    ],
                    tts=[
                        TtsProgram(
                            name="gemini_live_tts",
                            description="Gemini Native TTS",
                            attribution=Attribution(name="Google", url="https://google.com"),
                            installed=True,
                            version="1.0",
                            voices=[
                                TtsVoice(
                                    name="Orus",
                                    description="Orus Voice",
                                    attribution=Attribution(name="Google", url="https://google.com"),
                                    installed=True,
                                    version="1.0",
                                    languages=["ru"]
                                )
                            ]
                        )
                    ]
                ).event()
            )
            return True

        # --- ЗАХВАТ ЗВУКА С КУБИКА (ASR) ---
        if AudioStart.is_type(event.type):
            self.is_recording = True
            self.audio_buffer = bytes()
            return True

        if AudioChunk.is_type(event.type):
            if self.is_recording:
                chunk = AudioChunk.from_event(event)
                self.audio_buffer += chunk.audio
            return True

        if AudioStop.is_type(event.type):
            self.is_recording = False
            transcript = await self.process_stt(self.audio_buffer)
            if transcript:
                print(f"[ASR] Распознано: {transcript}")
            await self.write_event(Transcript(text=transcript).event())
            return True

        # --- СИНТЕЗ ГОЛОСА (TTS) ЧЕРЕЗ LIVE API ---
        # v6.6: ПОТОКОВАЯ озвучка — чанки PCM летят на кубик сразу при приходе от
        # Gemini Live. Сессия pipeline постоянно «живая», таймаут не рвёт длинные
        # ответы, первая секунда звука начинается раньше.
        if Synthesize.is_type(event.type):
            synth = Synthesize.from_event(event)
            print(f"[TTS] Отвечаю: {synth.text}")
            await self.write_event(AudioStart(rate=24000, width=2, channels=1).event())
            total = await self.process_tts_stream(synth.text)
            await self.write_event(AudioStop().event())
            print(f"[TTS] Стрим завершён: {total} байт PCM")
            return True

        return True

    # --- СИНХРОННЫЙ ВЫЗОВ REST API (STT / РАСПОЗНАВАНИЕ) ---
    def process_stt_sync(self, pcm_data):
        # Noise Gate: игнорируем тишину, клики и микро-шумы короче ~0.6 сек (16000 Гц * 2 байта = 32000 байт/сек)
        if len(pcm_data) < 20000:
            return ""

        try:
            # Упаковываем сырой PCM звук в правильный WAV прямо в RAM
            with io.BytesIO() as wav_io:
                with wave.open(wav_io, 'wb') as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(16000)
                    wav_file.writeframes(pcm_data)
                wav_data = wav_io.getvalue()

            b64_data = base64.b64encode(wav_data).decode('utf-8')

            payload = {
                "contents": [{
                    "parts": [
                        {"text": "Переведи аудио в текст на русском языке. Выведи ТОЛЬКО распознанный текст без знаков препинания и без комментариев."},
                        {"inlineData": {"mimeType": "audio/wav", "data": b64_data}}
                    ]
                }]
            }

            req = urllib.request.Request(
                REST_URL,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode())
                return data['candidates'][0]['content']['parts'][0]['text'].strip()
        except Exception as e:
            print(f"Ошибка ASR REST API: {e}")
            return ""

    async def process_stt(self, pcm_data):
        # Выносим блокирующий HTTP-запрос в отдельный поток
        return await asyncio.to_thread(self.process_stt_sync, pcm_data)

    # --- WEBSOCKET LIVE API (TTS / СИНТЕЗ) ---
    async def process_tts(self, text):
        # Ретрай: сетевые флапы к Google дают timeout на handshake — пробуем дважды
        last_err = None
        for attempt in range(2):
            try:
                return await self._tts_once(text)
            except Exception as e:
                last_err = e
                print(f"Ошибка TTS Live API (попытка {attempt + 1}/2): {e}")
                if attempt == 0:
                    await asyncio.sleep(2)
        print(f"Ошибка TTS Live API: обе попытки исчерпаны ({last_err})")
        return bytes()

    async def process_tts_stream(self, text):
        """v6.6: потоковый TTS — каждый чанк PCM немедленно уходит на кубик.
        Возвращает суммарное число отправленных байт."""
        total = 0
        last_err = None
        for attempt in range(2):
            try:
                async with websockets.connect(BIDI_URL) as ws:
                    setup_msg = {
                        "setup": {
                            "model": MODEL_TTS,
                            "generationConfig": {
                                "responseModalities": ["AUDIO"],
                                "speechConfig": {
                                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Orus"}}
                                }
                            }
                        }
                    }
                    await ws.send(json.dumps(setup_msg))
                    await ws.recv()

                    await ws.send(json.dumps({
                        "clientContent": {
                            "turns": [{"role": "user", "parts": [{"text": f"Произнеси текст: {text}"}]}],
                            "turnComplete": True
                        }
                    }))
                    carry = bytes()
                    chunk_size = 1024
                    async for msg in ws:
                        resp = json.loads(msg)
                        if "serverContent" in resp and "modelTurn" in resp["serverContent"]:
                            for part in resp["serverContent"]["modelTurn"]["parts"]:
                                if "inlineData" in part:
                                    carry += base64.b64decode(part["inlineData"]["data"])
                                    # Отдаём полные 1024-байтные чанки немедленно,
                                    # хвост (<1024) держим до следующей порции
                                    while len(carry) >= chunk_size:
                                        await self.write_event(AudioChunk(
                                            rate=24000, width=2, channels=1,
                                            audio=carry[:chunk_size]
                                        ).event())
                                        total += chunk_size
                                        carry = carry[chunk_size:]
                        if resp.get("serverContent", {}).get("turnComplete"):
                            break
                    # Досылаем хвост
                    if carry:
                        await self.write_event(AudioChunk(
                            rate=24000, width=2, channels=1, audio=carry
                        ).event())
                        total += len(carry)
                    return total
            except Exception as e:
                last_err = e
                print(f"[TTS stream] ошибка (попытка {attempt + 1}/2): {e}")
                if attempt == 0:
                    await asyncio.sleep(2)
        print(f"[TTS stream] обе попытки исчерпаны ({last_err})")
        return total

    async def _tts_once(self, text):
        try:
            async with websockets.connect(BIDI_URL) as ws:
                setup_msg = {
                    "setup": {
                        "model": MODEL_TTS,
                        "generationConfig": {
                            "responseModalities": ["AUDIO"],
                            "speechConfig": {
                                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Orus"}}
                            }
                        }
                    }
                }
                await ws.send(json.dumps(setup_msg))
                await ws.recv()

                await ws.send(json.dumps({
                    "clientContent": {
                        "turns": [{"role": "user", "parts": [{"text": f"Произнеси текст: {text}"}]}],
                        "turnComplete": True
                    }
                }))
                audio_bytes = bytes()
                async for msg in ws:
                    resp = json.loads(msg)
                    if "serverContent" in resp and "modelTurn" in resp["serverContent"]:
                        for part in resp["serverContent"]["modelTurn"]["parts"]:
                            if "inlineData" in part:
                                audio_bytes += base64.b64decode(part["inlineData"]["data"])
                    if resp.get("serverContent", {}).get("turnComplete"):
                        break
                return audio_bytes
        except Exception as e:
            print(f"Ошибка TTS Live API: {e}")
            return bytes()


async def main():
    server = AsyncTcpServer("0.0.0.0", PORT)
    print(f"Шлюз гибридного API запущен на порту {PORT}...")
    await server.run(BridgeEventHandler)


if __name__ == "__main__":
    asyncio.run(main())
