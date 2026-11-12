"use client";

import { useState, useRef, useEffect, useCallback } from "react";

interface SpeechAlternativeLike {
  transcript: string;
}
interface SpeechResultLike {
  isFinal: boolean;
  0: SpeechAlternativeLike;
}
interface SpeechResultEventLike {
  results: ArrayLike<SpeechResultLike>;
}
interface SpeechErrorEventLike {
  error: string;
}
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onstart: (() => void) | null;
  onresult: ((event: SpeechResultEventLike) => void) | null;
  onerror: ((event: SpeechErrorEventLike) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

export interface UseVoiceInputOptions {
  initialLang?: "en" | "nl";
  silenceTimeoutMs?: number;
  onTranscript?: (newTranscript: string, isFinal: boolean) => void;
  onSilencePause?: (finalText: string) => void;
}

/** How many times a session restarts after the browser ends it with nothing heard, before giving up. */
const MAX_SILENT_RESTARTS = 3;

const ERROR_MESSAGES: Record<string, string> = {
  unsupported: "Speech recognition is not supported in this browser. Use Chrome, Edge or Safari.",
  "not-allowed": "Microphone access is blocked. Allow the microphone for this site and try again.",
  "service-not-allowed": "Speech recognition is switched off in this browser's settings.",
  "audio-capture": "No microphone was found. Connect one and try again.",
  network: "Speech recognition needs an internet connection. Check the connection and try again.",
};

/**
 * Dictation on the Web Speech API (Chrome, Edge, Safari). One hook for every composer:
 * - keeps listening across the browser's own session ends (it stops after a pause) by restarting,
 *   carrying finished sentences over as the new prefix;
 * - reports problems as `error` text for the UI instead of an alert();
 * - optional auto-send: after `silenceTimeoutMs` of no new speech, `onSilencePause(fullText)` fires once.
 */
export function useVoiceInput({
  initialLang = "en",
  silenceTimeoutMs,
  onTranscript,
  onSilencePause,
}: UseVoiceInputOptions = {}) {
  const [speechLang, setSpeechLang] = useState<"en" | "nl">(initialLang);
  const [isListening, setIsListening] = useState(false);
  const [isPausing, setIsPausing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const silenceTimerRef = useRef<NodeJS.Timeout | null>(null);
  const latestTranscriptRef = useRef<string>("");
  const basePrefixRef = useRef<string>("");
  const wantListeningRef = useRef(false); // true between start and an explicit stop; onend restarts while it holds
  const silentRestartsRef = useRef(0);
  const langRef = useRef<"en" | "nl">(initialLang);
  const callbacksRef = useRef({ onTranscript, onSilencePause });
  useEffect(() => {
    callbacksRef.current = { onTranscript, onSilencePause };
  }, [onTranscript, onSilencePause]);
  const beginSessionRef = useRef<() => void>(() => {});

  const cancelSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
    setIsPausing(false);
  }, []);

  const stopListening = useCallback(() => {
    wantListeningRef.current = false;
    cancelSilenceTimer();
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch {}
    }
    setIsListening(false);
    setIsPausing(false);
  }, [cancelSilenceTimer]);

  useEffect(() => {
    return () => {
      wantListeningRef.current = false;
      cancelSilenceTimer();
      if (recognitionRef.current) {
        try {
          recognitionRef.current.abort();
        } catch {}
      }
    };
  }, [cancelSilenceTimer]);

  const beginSession = useCallback(() => {
    const speech =
      typeof window === "undefined"
        ? undefined
        : (window as unknown as {
            SpeechRecognition?: SpeechRecognitionCtor;
            webkitSpeechRecognition?: SpeechRecognitionCtor;
          });
    const SpeechRec = speech && (speech.SpeechRecognition || speech.webkitSpeechRecognition);
    if (!SpeechRec) {
      setError(ERROR_MESSAGES.unsupported);
      wantListeningRef.current = false;
      return;
    }
    const recognition = new SpeechRec();
    recognition.lang = langRef.current === "nl" ? "nl-NL" : "en-US";
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;
    let heardSomething = false;

    recognition.onstart = () => {
      setIsListening(true);
      setError(null);
      cancelSilenceTimer();
    };

    recognition.onresult = (event: SpeechResultEventLike) => {
      if (recognitionRef.current !== recognition) return; // a superseded session must not touch live state
      let interimTranscript = "";
      let finalTranscript = "";
      for (let i = 0; i < event.results.length; ++i) {
        if (event.results[i].isFinal) {
          finalTranscript += event.results[i][0].transcript + " ";
        } else {
          interimTranscript += event.results[i][0].transcript;
        }
      }
      const liveText = (finalTranscript + interimTranscript).trim();
      if (!liveText) return;
      heardSomething = true;
      silentRestartsRef.current = 0;
      const combined = basePrefixRef.current + liveText;
      latestTranscriptRef.current = combined;
      callbacksRef.current.onTranscript?.(combined, false);

      if (silenceTimeoutMs && silenceTimeoutMs > 0) {
        cancelSilenceTimer();
        setIsPausing(true);
        silenceTimerRef.current = setTimeout(() => {
          const textToSend = latestTranscriptRef.current.trim();
          stopListening();
          callbacksRef.current.onSilencePause?.(textToSend);
        }, silenceTimeoutMs);
      }
    };

    recognition.onerror = (event: SpeechErrorEventLike) => {
      if (recognitionRef.current !== recognition) return;
      if (event.error === "aborted" || event.error === "no-speech") return; // onend decides what happens next
      const message = ERROR_MESSAGES[event.error];
      if (message) {
        setError(message);
        wantListeningRef.current = false;
        cancelSilenceTimer();
        setIsListening(false);
      } else {
        console.warn("Speech recognition notice:", event.error);
      }
    };

    recognition.onend = () => {
      if (recognitionRef.current !== recognition) return; // a newer session owns the state now
      // Browsers end the session on their own after a pause; keep going until the user stops it.
      if (wantListeningRef.current) {
        if (!heardSomething) silentRestartsRef.current += 1;
        if (silentRestartsRef.current <= MAX_SILENT_RESTARTS) {
          basePrefixRef.current = latestTranscriptRef.current.trim()
            ? latestTranscriptRef.current.trim() + " "
            : "";
          try {
            beginSessionRef.current();
            return;
          } catch {}
        }
        wantListeningRef.current = false;
      }
      setIsListening(false);
      setIsPausing(false);
    };

    recognitionRef.current = recognition;
    recognition.start();
  }, [cancelSilenceTimer, silenceTimeoutMs, stopListening]);

  useEffect(() => {
    beginSessionRef.current = beginSession;
  }, [beginSession]);

  const startListening = useCallback(
    (existingText = "", overrideLang?: "en" | "nl") => {
      if (typeof window === "undefined") return;
      if (wantListeningRef.current) {
        stopListening();
        return;
      }
      langRef.current = overrideLang || speechLang;
      basePrefixRef.current = existingText.trim() ? existingText.trim() + " " : "";
      latestTranscriptRef.current = basePrefixRef.current;
      wantListeningRef.current = true;
      silentRestartsRef.current = 0;
      setError(null);
      try {
        beginSession();
      } catch (err) {
        console.warn("Speech recognition initialization error:", err);
        wantListeningRef.current = false;
        setIsListening(false);
      }
    },
    [speechLang, beginSession, stopListening]
  );

  const toggleVoiceInput = useCallback(
    (existingText = "", overrideLang?: "en" | "nl") => {
      if (wantListeningRef.current) {
        stopListening();
      } else {
        startListening(existingText, overrideLang);
      }
    },
    [stopListening, startListening]
  );

  return {
    isListening,
    isPausing,
    error,
    speechLang,
    setSpeechLang,
    startListening,
    stopListening,
    toggleVoiceInput,
    /** Cancels a pending silence auto-send without stopping the microphone (the user started typing). */
    cancelPause: cancelSilenceTimer,
  };
}
