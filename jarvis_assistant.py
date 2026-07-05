import json
import math
import os
import sys
import threading
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
import webbrowser


APP_TITLE = "Jarvis Assistant"
MEMORY_FILE = Path(__file__).with_name("jarvis_memory.json")
SETTINGS_FILE = Path(__file__).with_name("jarvis_settings.json")


def load_optional_voice():
    try:
        import pyttsx3  # type: ignore
    except ImportError:
        pyttsx3 = None

    try:
        import speech_recognition as sr  # type: ignore
    except ImportError:
        sr = None

    return pyttsx3, sr


@dataclass
class AssistantResponse:
    text: str
    speak: bool = True


class MemoryStore:
    def __init__(self, path: Path):
        self.path = path
        self._data = self._load()

    def _load(self):
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def save(self):
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(self._data, handle, indent=2, ensure_ascii=True)

    def remember(self, key: str, value: str):
        self._data[key.lower().strip()] = value.strip()
        self.save()

    def forget(self, key: str):
        self._data.pop(key.lower().strip(), None)
        self.save()

    def get(self, key: str):
        return self._data.get(key.lower().strip())

    def all_items(self):
        return sorted(self._data.items())

    def clear(self):
        self._data = {}
        self.save()


class SettingsStore:
    def __init__(self, path: Path):
        self.path = path
        self._data = self._load()

    def _load(self):
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def save(self):
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(self._data, handle, indent=2, ensure_ascii=True)

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value):
        self._data[key] = value
        self.save()


class AssistantCore:
    def __init__(self):
        self.memory = MemoryStore(MEMORY_FILE)

    def handle(self, text: str) -> AssistantResponse:
        cleaned = text.strip()
        lowered = cleaned.lower()

        if not cleaned:
            return AssistantResponse("Say something and I will respond.", speak=False)

        if lowered in {"hi", "hello", "hey", "jarvis"}:
            return AssistantResponse("Online. What can I do for you?")

        if lowered in {"help", "commands"}:
            return AssistantResponse(
                "Try: time, date, remember X is Y, what do you remember, open youtube, forget X."
            )

        if lowered == "time":
            return AssistantResponse(datetime.now().strftime("It is %I:%M %p.").lstrip("0"))

        if lowered == "date":
            return AssistantResponse(datetime.now().strftime("Today is %A, %B %d, %Y."))

        if lowered in {"what do you remember", "show memory", "list memory"}:
            items = self.memory.all_items()
            if not items:
                return AssistantResponse("I do not remember anything yet.")
            joined = "; ".join(f"{key} = {value}" for key, value in items)
            return AssistantResponse(f"I remember: {joined}")

        if lowered.startswith("remember "):
            payload = cleaned[9:].strip()
            separator = "=" if "=" in payload else " is "
            if separator not in payload:
                return AssistantResponse("Use: remember topic is value")
            key, value = payload.split(separator, 1)
            self.memory.remember(key, value)
            return AssistantResponse(f"Saved {key.strip()} = {value.strip()}.")

        if lowered.startswith("forget "):
            key = cleaned[7:].strip()
            self.memory.forget(key)
            return AssistantResponse(f"Forgot {key}.")

        if lowered.startswith("what is "):
            key = cleaned[8:].strip().rstrip("?")
            value = self.memory.get(key)
            if value is not None:
                return AssistantResponse(f"{key} is {value}.")

        if lowered.startswith("open "):
            target = cleaned[5:].strip()
            return self._open_target(target)

        return AssistantResponse(f"I heard: {cleaned}")

    def _open_target(self, target: str) -> AssistantResponse:
        shortcuts = {
            "youtube": "https://www.youtube.com",
            "google": "https://www.google.com",
            "github": "https://github.com",
            "gmail": "https://mail.google.com",
        }

        if target.lower() in shortcuts:
            webbrowser.open(shortcuts[target.lower()])
            return AssistantResponse(f"Opening {target}.")

        if target.startswith("http://") or target.startswith("https://"):
            webbrowser.open(target)
            return AssistantResponse(f"Opening {target}.")

        if os.path.exists(target):
            try:
                os.startfile(target)  # type: ignore[attr-defined]
                return AssistantResponse(f"Opening {target}.")
            except OSError as exc:
                return AssistantResponse(f"Could not open {target}: {exc}", speak=False)

        webbrowser.open(f"https://www.google.com/search?q={target.replace(' ', '+')}")
        return AssistantResponse(f"Searching for {target}.")


class JarvisApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1280x720")
        self.attributes("-fullscreen", True)

        self.core = AssistantCore()
        self.settings = SettingsStore(SETTINGS_FILE)
        self.tts, self.sr = load_optional_voice()
        self.voice_engine = self.tts.init() if self.tts else None
        if self.voice_engine:
            self.voice_engine.setProperty("rate", 175)
        self.voice_options = []
        self.voice_choice = tk.StringVar(value="Default voice")
        self._animation_phase = 0.0
        self._speaking = False
        self._animation_running = True
        self._canvas_width = 1280
        self._canvas_height = 720
        self._build_ui()
        self._load_voices()
        self._animate_hud()
        self._append_bot("Jarvis online. Type a command or use voice if available.")

    def _build_ui(self):
        self.hud = tk.Canvas(
            self,
            bg="#02070b",
            highlightthickness=0,
            bd=0,
        )
        self.hud.pack(fill="both", expand=True)
        self.hud.bind("<Configure>", self._on_canvas_resize)
        self.hud.bind("<Button-1>", lambda event: self.focus_set())

        self.overlay = ttk.Frame(self, padding=14)
        self.overlay.place(relx=0.5, rely=1.0, anchor="s", y=-16, relwidth=0.88)
        self.overlay.columnconfigure(0, weight=1)

        self.chat = tk.Text(self.overlay, wrap="word", state="disabled", height=6)
        self.chat.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 10))

        self.entry = ttk.Entry(self.overlay)
        self.entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self.entry.bind("<Return>", lambda event: self.send())

        send_btn = ttk.Button(self.overlay, text="Send", command=self.send)
        send_btn.grid(row=1, column=1, sticky="ew", padx=(0, 8))

        listen_btn = ttk.Button(self.overlay, text="Listen", command=self.listen)
        listen_btn.grid(row=1, column=2, sticky="ew", padx=(0, 8))

        ttk.Button(self.overlay, text="Exit", command=self._close).grid(row=1, column=3, sticky="ew")

        voice_bar = ttk.Frame(self.overlay)
        voice_bar.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        voice_bar.columnconfigure(1, weight=1)

        ttk.Label(voice_bar, text="Voice:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.voice_menu = ttk.Combobox(
            voice_bar,
            textvariable=self.voice_choice,
            state="readonly",
            values=["Loading voices..."],
        )
        self.voice_menu.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(voice_bar, text="Apply", command=self.apply_voice).grid(row=0, column=2, sticky="e")

        self.status = ttk.Label(self.overlay, text=self._voice_status())
        self.status.grid(row=3, column=0, columnspan=4, sticky="w", pady=(10, 0))

        self.bind("<Escape>", lambda event: self._close())
        self.bind("<F11>", lambda event: self._toggle_fullscreen())
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _build_hud(self):
        self.hud.delete("all")
        self.hud.create_oval(35, 15, 265, 245, outline="#0d3a53", width=2, tags="outer")
        self.hud.create_oval(55, 35, 245, 225, outline="#1a6d8a", width=2, tags="ring1")
        self.hud.create_oval(78, 58, 222, 202, outline="#2dc7ff", width=2, tags="ring2")
        self.hud.create_oval(108, 88, 192, 172, outline="#66e7ff", width=3, fill="#07212f", tags="core")
        self.hud.create_text(
            150,
            130,
            text="JARVIS",
            fill="#9deeff",
            font=("Segoe UI", 18, "bold"),
            tags="label",
        )

    def _voice_status(self):
        if self.tts and self.sr:
            return "Voice ready."
        return "Voice modules not installed; text mode is ready."

    def _load_voices(self):
        if not self.tts or not self.voice_engine:
            self.voice_menu.configure(values=["Default voice"], state="disabled")
            self.voice_choice.set("Default voice")
            return

        voices = self.voice_engine.getProperty("voices")
        self.voice_options = voices
        labels = ["Default voice"]
        current_voice_id = self.settings.get("voice_id")
        selected_label = "Default voice"

        for voice in voices:
            label = f"{voice.name} ({voice.id})"
            labels.append(label)
            if current_voice_id and voice.id == current_voice_id:
                selected_label = label

        self.voice_menu.configure(values=labels)
        self.voice_choice.set(selected_label)
        self._apply_voice_by_label(selected_label)

    def _apply_voice_by_label(self, label: str):
        if not self.voice_engine:
            return

        if label == "Default voice":
            self.voice_engine.setProperty("voice", self.voice_engine.getProperty("voice"))
            self.settings.set("voice_id", None)
            return

        for voice in self.voice_options:
            candidate = f"{voice.name} ({voice.id})"
            if candidate == label:
                self.voice_engine.setProperty("voice", voice.id)
                self.settings.set("voice_id", voice.id)
                return

    def apply_voice(self):
        self._apply_voice_by_label(self.voice_choice.get())
        self.status.configure(text=f"Selected voice: {self.voice_choice.get()}")

    def _append(self, speaker: str, message: str):
        self.chat.configure(state="normal")
        self.chat.insert("end", f"{speaker}: {message}\n")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def _append_user(self, message: str):
        self._append("You", message)

    def _append_bot(self, message: str):
        self._append("Jarvis", message)
        self._speak(message)

    def _speak(self, message: str):
        if not self.voice_engine:
            return

        self._set_speaking(True)

        def run():
            try:
                self.voice_engine.say(message)
                self.voice_engine.runAndWait()
            finally:
                self.after(0, lambda: self._set_speaking(False))

        threading.Thread(target=run, daemon=True).start()

    def _set_speaking(self, speaking: bool):
        self._speaking = speaking
        self.status.configure(text="Jarvis speaking..." if speaking else self._voice_status())

    def _animate_hud(self):
        if not self._animation_running:
            return

        self._animation_phase += 0.08
        phase = self._animation_phase

        pulse = 1.0 + (0.03 * math.sin(phase * 0.8))
        speaking_boost = 1.0 + (0.06 * math.sin(phase * 1.7)) if self._speaking else 1.0
        scale = pulse * speaking_boost

        shake_x = math.sin(phase * 7.0) * (4 if self._speaking else 0.6)
        shake_y = math.cos(phase * 6.0) * (3 if self._speaking else 0.5)

        self.hud.delete("ambient")
        self.hud.delete("sweep")
        self.hud.delete("bg")
        self.hud.delete("ring")
        self.hud.delete("particles")
        self.hud.delete("glow")
        self.hud.delete("scan")

        cx = self._canvas_width / 2 + shake_x
        cy = self._canvas_height / 2 - 40 + shake_y
        self._draw_ambient(cx, cy, scale)
        self._draw_dynamic_hud(cx, cy, scale)

        if self._speaking:
            sweep_angle = (phase * 70) % 360
            self._draw_sweep(sweep_angle, cx, cy, scale)

        self._draw_background(cx, cy, scale)
        self.after(30, self._animate_hud)

    def _draw_ambient(self, cx: float, cy: float, scale: float):
        width = self._canvas_width
        height = self._canvas_height

        for index in range(0, 30):
            y = (height / 2) + math.sin(self._animation_phase * 0.45 + index * 0.3) * (22 + index * 0.2)
            x_offset = math.cos(self._animation_phase * 0.3 + index * 0.27) * 18
            self.hud.create_line(
                x_offset,
                y,
                width + x_offset,
                y + math.sin(self._animation_phase + index * 0.2) * 2,
                fill="#4a3200",
                width=1,
                tags="ambient",
            )

        for index in range(8):
            radius = min(width, height) * (0.14 + index * 0.09) * scale
            self.hud.create_oval(
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
                outline="#2f2100",
                width=1,
                dash=(2, 10),
                tags="ambient",
            )

    def _draw_dynamic_hud(self, cx: float, cy: float, scale: float):
        outer_r = min(self._canvas_width, self._canvas_height) * 0.29 * scale
        ring1_r = outer_r * 0.83
        ring2_r = outer_r * 0.61
        core_r = outer_r * 0.20

        steps = 420
        points = []
        for index in range(steps + 1):
            angle = (index / steps) * math.tau
            wobble = (
                math.sin(angle * 6.0 + self._animation_phase * 2.4) * 12
                + math.sin(angle * 11.0 - self._animation_phase * 1.9) * 6
                + math.sin(angle * 17.0 + self._animation_phase * 0.9) * 2.8
            ) * scale
            radius = ring1_r + wobble
            px = cx + math.cos(angle) * radius
            py = cy + math.sin(angle) * radius
            points.extend([px, py])

        self.hud.create_oval(
            cx - outer_r * 1.14,
            cy - outer_r * 1.14,
            cx + outer_r * 1.14,
            cy + outer_r * 1.14,
            outline="#1b1600",
            width=6,
            tags="bg",
        )
        self.hud.create_oval(
            cx - outer_r,
            cy - outer_r,
            cx + outer_r,
            cy + outer_r,
            outline="#7a6200",
            width=2,
            tags="ring",
        )
        self.hud.create_oval(
            cx - ring2_r,
            cy - ring2_r,
            cx + ring2_r,
            cy + ring2_r,
            outline="#ffd84d",
            width=2,
            tags="ring",
        )
        self.hud.create_oval(
            cx - core_r,
            cy - core_r,
            cx + core_r,
            cy + core_r,
            outline="#fff1a8",
            width=3,
            fill="#241d00",
            tags="ring",
        )
        pulse_core = core_r * (1.0 + (0.08 * math.sin(self._animation_phase * 3.8)) if self._speaking else 1.0)
        self.hud.create_oval(
            cx - pulse_core,
            cy - pulse_core,
            cx + pulse_core,
            cy + pulse_core,
            outline="#fff3bf",
            width=1,
            fill="#071c25",
            tags="ring",
        )
        self.hud.create_text(
            cx,
            cy,
            text="JARVIS",
            fill="#fff7c7",
            font=("Segoe UI", max(18, int(outer_r * 0.14)), "bold"),
            tags="ring",
        )
        self.hud.create_line(
            *points,
            fill="#ffd84d",
            width=3 if self._speaking else 2,
            smooth=True,
            splinesteps=40,
            tags="ring",
        )
        self.hud.create_line(
            *points,
            fill="#4b3300",
            width=1,
            smooth=True,
            splinesteps=40,
            tags="ring",
        )
        for index in range(0, steps, 6):
            angle = (index / steps) * math.tau
            jitter = (
                math.sin(angle * 9.0 + self._animation_phase * 2.1) * 8
                + math.sin(angle * 21.0 - self._animation_phase * 1.2) * 3
            ) * scale
            radius = ring1_r + jitter
            px = cx + math.cos(angle) * radius
            py = cy + math.sin(angle) * radius
            self.hud.create_oval(
                px - 2.4,
                py - 2.4,
                px + 2.4,
                py + 2.4,
                outline="",
                fill="#fff3b0",
                tags="particles",
            )
            if index % 15 == 0:
                tail = 12 + (4 if self._speaking else 0)
                tx = px + math.cos(angle) * tail
                ty = py + math.sin(angle) * tail
                self.hud.create_line(
                    px,
                    py,
                    tx,
                    ty,
                    fill="#ffcc3d",
                    width=2,
                    tags="particles",
                )
            if index % 24 == 0:
                self.hud.create_arc(
                    px - 12,
                    py - 12,
                    px + 12,
                    py + 12,
                    start=(index * 2 + self._animation_phase * 80) % 360,
                    extent=35,
                    style="arc",
                    outline="#ffea8a",
                    width=1,
                    tags="particles",
                )
        for angle in range(0, 360, 30):
            radians = math.radians(angle)
            inner = ring2_r * 0.95
            outer = outer_r * 1.02
            x1 = cx + math.cos(radians) * inner
            y1 = cy + math.sin(radians) * inner
            x2 = cx + math.cos(radians) * outer
            y2 = cy + math.sin(radians) * outer
            self.hud.create_line(x1, y1, x2, y2, fill="#b58a00", width=2, tags="particles")
        for angle in range(12, 372, 18):
            start = angle + (self._animation_phase * 35) % 360
            extent = 10 + (4 * math.sin(self._animation_phase * 1.5 + angle))
            self.hud.create_arc(
                cx - outer_r * 0.98,
                cy - outer_r * 0.98,
                cx + outer_r * 0.98,
                cy + outer_r * 0.98,
                start=start,
                extent=extent,
                style="arc",
                outline="#ffd84d",
                width=2 if self._speaking else 1,
                tags="particles",
            )
        for index in range(32):
            angle = (index / 32) * math.tau + self._animation_phase * 0.9
            radius = ring2_r * (0.75 + 0.08 * math.sin(self._animation_phase * 2.2 + index))
            x = cx + math.cos(angle) * radius
            y = cy + math.sin(angle) * radius
            self.hud.create_oval(
                x - 1.5,
                y - 1.5,
                x + 1.5,
                y + 1.5,
                outline="",
                fill="#fff0a6",
                tags="particles",
            )

    def _draw_background(self, cx: float, cy: float, scale: float):
        glow_r = min(self._canvas_width, self._canvas_height) * 0.46 * scale
        self.hud.create_oval(
            cx - glow_r,
            cy - glow_r,
            cx + glow_r,
            cy + glow_r,
            outline="#5d4300",
            width=1,
            tags="glow",
        )
        self.hud.create_oval(
            cx - glow_r * 0.72,
            cy - glow_r * 0.72,
            cx + glow_r * 0.72,
            cy + glow_r * 0.72,
            outline="#2a1f00",
            width=1,
            tags="glow",
        )
        self.hud.create_oval(
            cx - glow_r * 1.25,
            cy - glow_r * 1.25,
            cx + glow_r * 1.25,
            cy + glow_r * 1.25,
            outline="#090700",
            width=24,
            tags="glow",
        )
        self.hud.create_oval(
            cx - glow_r * 0.42,
            cy - glow_r * 0.42,
            cx + glow_r * 0.42,
            cy + glow_r * 0.42,
            outline="#fff1a8",
            width=2,
            tags="glow",
        )

    def _draw_sweep(self, angle: float, cx: float, cy: float, scale: float):
        radians = math.radians(angle)
        sweep_length = min(self._canvas_width, self._canvas_height) * 0.26 * scale
        x2 = cx + math.cos(radians) * sweep_length
        y2 = cy + math.sin(radians) * sweep_length
        self.hud.create_line(
            cx,
            cy,
            x2,
            y2,
            fill="#ffd84d",
            width=3,
            capstyle="round",
            tags="sweep",
        )
        self.hud.create_oval(
            x2 - 6,
            y2 - 6,
            x2 + 6,
            y2 + 6,
            outline="#fff0aa",
            width=2,
            tags="sweep",
        )
        tail_x = cx + math.cos(radians) * (sweep_length * 0.7)
        tail_y = cy + math.sin(radians) * (sweep_length * 0.7)
        self.hud.create_line(
            cx,
            cy,
            tail_x,
            tail_y,
            fill="#f0c63a",
            width=2,
            dash=(2, 4),
            tags="sweep",
        )

    def _on_canvas_resize(self, event):
        self._canvas_width = max(1, event.width)
        self._canvas_height = max(1, event.height)

    def _toggle_fullscreen(self):
        self.attributes("-fullscreen", not bool(self.attributes("-fullscreen")))

    def send(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self._append_user(text)
        response = self.core.handle(text)
        self._append_bot(response.text)

    def listen(self):
        if not self.sr:
            messagebox.showinfo("Voice unavailable", "speech_recognition is not installed.")
            return

        try:
            recognizer = self.sr.Recognizer()
            with self.sr.Microphone() as source:
                self.status.configure(text="Listening...")
                audio = recognizer.listen(source, phrase_time_limit=6)
            transcript = recognizer.recognize_google(audio)
        except self.sr.UnknownValueError:
            self.status.configure(text="Could not understand speech.")
            return
        except self.sr.RequestError as exc:
            self.status.configure(text=f"Speech service error: {exc}")
            return
        except OSError as exc:
            self.status.configure(text=f"Microphone error: {exc}")
            return

        self.status.configure(text=self._voice_status())
        self._append_user(transcript)
        response = self.core.handle(transcript)
        self._append_bot(response.text)

    def _close(self):
        self._animation_running = False
        self.destroy()


def main():
    app = JarvisApp()
    app.mainloop()


if __name__ == "__main__":
    main()
