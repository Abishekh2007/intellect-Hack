import { useState, useEffect, useRef } from "react";

/* The Web Speech API has no lib.dom types, so the shapes this hook actually
   touches are declared here. Typing them beats `any`: a rename in the loop
   below is now a compile error rather than a runtime one. */
interface SpeechAlternative {
  transcript: string;
}
interface SpeechResult {
  isFinal: boolean;
  readonly length: number;
  [index: number]: SpeechAlternative;
}
interface SpeechResultList {
  readonly length: number;
  [index: number]: SpeechResult;
}
interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: SpeechResultList;
}
interface SpeechRecognitionErrorEventLike {
  error: string;
}
interface SpeechRecognitionLike {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

declare global {
  interface Window {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  }
}

export function useSpeechRecognition() {
  const [isListening, setIsListening] = useState(false);
  const [interimTranscript, setInterimTranscript] = useState("");
  const [finalTranscript, setFinalTranscript] = useState("");
  const [error, setError] = useState<string | null>(null);
  // Must start false so the server render and the first client render agree.
  // Reading `window` during render instead makes the mic button appear only on
  // the client, and React throws away the whole tree on a hydration mismatch.
  const [hasSupport, setHasSupport] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  useEffect(() => {
    const Ctor =
      typeof window === "undefined"
        ? undefined
        : (window.SpeechRecognition ?? window.webkitSpeechRecognition);

    if (Ctor) {
      setHasSupport(true);
      const recognition = new Ctor();
      recognitionRef.current = recognition;
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = "en-US";

      recognition.onresult = (event: SpeechRecognitionEventLike) => {
        let currentInterim = "";
        let currentFinal = "";

        for (let i = event.resultIndex; i < event.results.length; ++i) {
          const result = event.results[i];
          const text = result?.[0]?.transcript;
          if (!text) continue;
          if (result.isFinal) {
            currentFinal += text;
          } else {
            currentInterim += text;
          }
        }

        if (currentFinal) {
          setFinalTranscript((prev) => (prev ? prev + " " : "") + currentFinal.trim());
        }
        setInterimTranscript(currentInterim);
      };

      recognition.onerror = (event: SpeechRecognitionErrorEventLike) => {
        setError(event.error);
        setIsListening(false);
      };

      recognition.onend = () => {
        setIsListening(false);
      };
    }

    return () => {
      // Without this the microphone stays live after the component unmounts:
      // the browser keeps the recording indicator on and the handlers keep
      // firing setState on a component that no longer exists.
      const recognition = recognitionRef.current;
      if (!recognition) return;
      recognition.onresult = null;
      recognition.onerror = null;
      recognition.onend = null;
      try {
        recognition.abort();
      } catch {
        /* already stopped */
      }
      recognitionRef.current = null;
    };
  }, []);

  const startListening = () => {
    setFinalTranscript("");
    setInterimTranscript("");
    setError(null);
    if (recognitionRef.current) {
      try {
        recognitionRef.current.start();
        setIsListening(true);
      } catch {
        // Already running: leave the existing session alone rather than
        // claiming to have started a second one.
      }
    } else {
      setError("Speech recognition not supported in this browser.");
    }
  };

  const stopListening = () => {
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch {
        /* not running */
      }
      setIsListening(false);
    }
  };

  return {
    isListening,
    transcript: (finalTranscript + (interimTranscript ? " " + interimTranscript : "")).trim(),
    resetTranscript: () => {
      setFinalTranscript("");
      setInterimTranscript("");
    },
    startListening,
    stopListening,
    error,
    hasSupport,
  };
}
