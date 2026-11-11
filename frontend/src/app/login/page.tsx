"use client";

import React, { useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { Sparkles, ShieldAlert, Lock, Loader2, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { apiFetch } from "@/lib/backend";

function GoogleIcon() {
  return (
    <svg className="w-5 h-5 shrink-0" viewBox="0 0 24 24">
      <path
        fill="#4285F4"
        d="M23.745 12.27c0-.7-.06-1.4-.19-2.07H12v4.51h6.6c-.29 1.52-1.14 2.82-2.4 3.68v3.05h3.88c2.27-2.09 3.665-5.17 3.665-9.17Z"
      />
      <path
        fill="#34A853"
        d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.88-3.05c-1.08.72-2.45 1.16-4.05 1.16-3.12 0-5.77-2.1-6.72-4.93H1.24v3.15C3.26 21.36 7.33 24 12 24Z"
      />
      <path
        fill="#FBBC05"
        d="M5.28 14.27c-.25-.72-.38-1.49-.38-2.27s.13-1.55.38-2.27V6.58H1.24C.45 8.15 0 9.92 0 12s.45 3.85 1.24 5.42l4.04-3.15Z"
      />
      <path
        fill="#EA4335"
        d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.33 0 3.26 2.64 1.24 6.58l4.04 3.15c.95-2.83 3.6-4.98 6.72-4.98Z"
      />
    </svg>
  );
}

// Fixed wording per error code: the page never displays text taken from the URL, so a crafted link cannot put its own
// words in the sign-in banner.
const LOGIN_MESSAGES: Record<string, string> = {
  invalid_state: "That sign-in link has expired or was opened in a different browser. Please start again.",
  unverified_email: "Google has not verified this email address, so it cannot be used to sign in.",
  ambiguous_account: "This email address is set up for more than one company, so it cannot sign in here. Ask your EstateOS administrator to remove the extra profile.",
  no_email: "Google did not return an email address for this account.",
  no_code: "Google did not complete the sign-in. Please try again.",
  not_configured: "Sign-in is not configured on this server. Contact your EstateOS administrator.",
  token_exchange_failed: "Google sign-in failed. Please try again.",
  profile_unavailable: "Could not read your Google profile. Please try again.",
  provider_unreachable: "Google could not be reached. Please try again in a moment.",
};

function LoginForm() {
  const searchParams = useSearchParams();
  const errorParam = searchParams.get("error");
  const rejectedEmail = searchParams.get("email");

  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Local development only (the fake identity provider): sign in as the dev owner without Google.
  const handleDevLogin = async () => {
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const res = await apiFetch("/api/v1/auth/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id_token: "test-owner-token" }),
      });
      if (!res.ok) {
        throw new Error("Dev sign-in is not available. Is the backend running in dev with the fake login provider?");
      }
      window.location.assign("/");
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Dev sign-in failed.");
      setIsLoading(false);
    }
  };

  const handleGoogleLogin = async () => {
    setIsLoading(true);
    setErrorMessage(null);
    try {
      let res: Response;
      try {
        res = await apiFetch("/api/auth/login/google/url", {
          method: "GET",
          headers: { Accept: "application/json" },
        });
      } catch (networkErr: any) {
        throw new Error("Cannot reach the EstateOS backend. Is it running?");
      }

      if (!res.ok) {
        const errJson = await res.json().catch(() => null);
        throw new Error(errJson?.detail || `Authentication service returned error (${res.status}).`);
      }

      const data = await res.json();
      if (data.url) {
        window.location.href = data.url;
      } else {
        throw new Error("Invalid login response received from server.");
      }
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to initiate Google sign-in.");
      setIsLoading(false);
    }
  };

  return (
    <div className="w-full max-w-[420px] rounded-2xl bg-[#14171A] border border-[#27272a] shadow-2xl p-7 sm:p-9 flex flex-col items-center text-center animate-in fade-in duration-300">
      {/* 1. Brand Logo */}
      <div className="w-12 h-12 rounded-2xl bg-[#1a73e8]/15 border border-[#1a73e8]/30 flex items-center justify-center text-[#1a73e8] shadow-[0_0_24px_rgba(26,115,232,0.3)] mb-4">
        <Sparkles className="w-6 h-6 animate-pulse" />
      </div>

      <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight">
        Sign in to EstateOS
      </h1>
      <p className="text-xs sm:text-[13px] text-[#94a3b8] mt-1.5 leading-relaxed max-w-[300px]">
        Enterprise portfolio management and autonomous operations
      </p>

      {/* 2. Error / Access Denied Alert Banner */}
      {(errorParam || errorMessage) && (
        <div className="w-full mt-5 p-3.5 rounded-xl border border-rose-500/30 bg-rose-950/30 text-rose-300 text-left text-xs space-y-1 animate-in fade-in-50">
          <div className="flex items-center gap-1.5 font-semibold text-rose-200">
            <ShieldAlert className="w-4 h-4 text-rose-400 shrink-0" />
            <span>
              {errorParam === "access_denied" ? "Access Denied" : "Sign-in Notice"}
            </span>
          </div>
          <p className="text-[11.5px] leading-relaxed text-rose-300/90 pl-5.5">
            {errorParam === "access_denied" ? (
              <>
                {rejectedEmail ? (
                  <strong className="text-white underline">{rejectedEmail}</strong>
                ) : (
                  "Your email account"
                )}{" "}
                is not on the authorized whitelist for this platform. Please contact your EstateOS administrator for access.
              </>
            ) : (
              errorMessage || (errorParam ? (LOGIN_MESSAGES[errorParam] ?? "Sign-in failed. Please try again.") : null)
            )}
          </p>
        </div>
      )}

      {/* 3. Action Buttons */}
      <div className="w-full mt-6 space-y-3">
        <button
          type="button"
          onClick={handleGoogleLogin}
          disabled={isLoading}
          className={cn(
            "w-full h-12 rounded-xl border border-[#374151] bg-[#1F2937] hover:bg-[#283548] hover:border-[#4B5563] text-white font-medium text-sm transition-all flex items-center justify-center gap-3 cursor-pointer shadow-md select-none disabled:opacity-50 disabled:cursor-not-allowed",
            "active:scale-[0.99]"
          )}
        >
          {isLoading ? (
            <>
              <Loader2 className="w-5 h-5 animate-spin text-[#1a73e8]" />
              <span>Connecting to Google...</span>
            </>
          ) : (
            <>
              <GoogleIcon />
              <span>Continue with Google</span>
              <ArrowRight className="w-4 h-4 text-[#94a3b8] ml-auto opacity-70" />
            </>
          )}
        </button>
        {process.env.NODE_ENV !== "production" && (
          <button
            type="button"
            onClick={handleDevLogin}
            disabled={isLoading}
            className="w-full h-10 rounded-xl border border-dashed border-[#374151] text-[#94a3b8] hover:text-white hover:border-[#4B5563] text-xs font-mono transition-all cursor-pointer select-none disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Continue as dev owner (local only)
          </button>
        )}
      </div>

      {/* 4. Whitelist Policy Badge */}
      <div className="mt-8 pt-5 border-t border-[#222830] w-full flex items-center justify-center gap-1.5 text-[11px] font-mono text-[#64748B]">
        <Lock className="w-3.5 h-3.5 text-[#1a73e8]/70" />
        <span>Whitelist Access Only · Closed Portal</span>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <div className="min-h-screen w-screen bg-[#0A1B2F] flex flex-col items-center justify-center p-4 relative overflow-hidden select-none">
      {/* Subtle background ambient glow */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] bg-[#1a73e8]/5 rounded-full blur-3xl pointer-events-none" />

      <Suspense
        fallback={
          <div className="flex items-center gap-2 text-white text-xs">
            <Loader2 className="w-4 h-4 animate-spin text-[#1a73e8]" />
            <span>Loading...</span>
          </div>
        }
      >
        <LoginForm />
      </Suspense>

      {/* Footer copyright */}
      <div className="mt-8 text-[11.5px] font-mono text-[#475569] text-center">
        EstateOS Autonomous Real Estate Operating System
      </div>
    </div>
  );
}
