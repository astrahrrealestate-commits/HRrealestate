"use client";

import { useState, useRef, useEffect, useCallback } from "react";

export interface UseVoiceInputOptions {
  initialLang?: "en" | "nl";
  silenceTimeoutMs?: number;
  onTranscript?: (newTranscript: string, isFinal: boolean) => void;
  onSilencePause?: (finalText: string) => void;
}

export function useVoiceInput({
  initialLang = "en",
  silenceTimeoutMs,
  onTranscript,
  onSilencePause,
}: UseVoiceInputOptions = {}) {
  const [speechLang, setSpeechLang] = useState<"en" | "nl">(initialLang);
  const [isListening, setIsListening] = useState(false);
  const [isPausing, setIsPausing] = useState(false);

  const recognitionRef = useRef<any>(null);
  const silenceTimerRef = useRef<NodeJS.Timeout | null>(null);
  const latestTranscriptRef = useRef<string>("");
  const basePrefixRef = useRef<string>("");

  const cancelSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
    setIsPausing(false);
  }, []);

  const stopListening = useCallback(() => {
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
      cancelSilenceTimer();
      if (recognitionRef.current) {
        try {
          recognitionRef.current.abort();
        } catch {}
      }
    };
  }, [cancelSilenceTimer]);

  const startListening = useCallback(
    (existingText = "", overrideLang?: "en" | "nl") => {
      if (typeof window === "undefined") return;
      const SpeechRec = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      if (!SpeechRec) {
        alert(
          "Speech recognition is not supported in this browser. Please use Google Chrome, Microsoft Edge, or Safari."
        );
        return;
      }

      // Stop any existing session
      if (isListening) {
        stopListening();
        return;
      }

      try {
        const activeLang = overrideLang || speechLang;
        const recognition = new SpeechRec();
        recognition.lang = activeLang === "nl" ? "nl-NL" : "en-US";
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.maxAlternatives = 1;

        basePrefixRef.current = existingText.trim() ? existingText.trim() + " " : "";
        latestTranscriptRef.current = basePrefixRef.current;

        recognition.onstart = () => {
          setIsListening(true);
          cancelSilenceTimer();
        };

        recognition.onresult = (event: any) => {
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
          if (liveText) {
            const combined = basePrefixRef.current + liveText;
            latestTranscriptRef.current = combined;
            onTranscript?.(combined, false);

            if (silenceTimeoutMs && silenceTimeoutMs > 0) {
              cancelSilenceTimer();
              setIsPausing(true);
              silenceTimerRef.current = setTimeout(() => {
                const textToSend = latestTranscriptRef.current.trim();
                stopListening();
                onSilencePause?.(textToSend);
              }, silenceTimeoutMs);
            }
          }
        };

        recognition.onerror = (event: any) => {
          if (event.error !== "no-speech") {
            console.warn("Speech recognition notice:", event.error);
          }
          if (event.error === "not-allowed" || event.error === "service-not-allowed") {
            setIsListening(false);
            cancelSilenceTimer();
          }
        };

        recognition.onend = () => {
          setIsListening(false);
          setIsPausing(false);
        };

        recognitionRef.current = recognition;
        recognition.start();
      } catch (err) {
        console.warn("Speech recognition initialization error:", err);
        setIsListening(false);
      }
    },
    [isListening, speechLang, silenceTimeoutMs, onTranscript, onSilencePause, cancelSilenceTimer, stopListening]
  );

  const toggleVoiceInput = useCallback(
    (existingText = "", overrideLang?: "en" | "nl") => {
      if (isListening) {
        stopListening();
      } else {
        startListening(existingText, overrideLang);
      }
    },
    [isListening, stopListening, startListening]
  );

  return {
    isListening,
    isPausing,
    speechLang,
    setSpeechLang,
    startListening,
    stopListening,
    toggleVoiceInput,
  };
}
