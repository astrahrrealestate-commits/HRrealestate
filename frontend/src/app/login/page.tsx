"use client";

import React, { useState, Suspense } from "react";
import Image from "next/image";
import { useSearchParams } from "next/navigation";
import { ShieldAlert, Lock, Loader2, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { apiFetch } from "@/lib/backend";

function GoogleIcon() {
  return (
    <svg className="w-5 h-5 shrink-0" viewBox="0 0 24 24" aria-hidden="true">
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
      } catch {
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
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to initiate Google sign-in.");
      setIsLoading(false);
    }
  };

  return (
    <div
      className={cn(
        "w-full max-w-[400px] lg:max-w-[420px] flex flex-col items-center text-center",
        // Mobile: borderless floating layout directly over the slightly blurred image scrim
        "px-1 py-2",
        // Desktop: sleek deep midnight-blue translucent frosted glass panel on the right
        "lg:rounded-2xl lg:bg-[#060E1D]/72 lg:backdrop-blur-xl lg:border lg:border-white/15 lg:shadow-[0_24px_80px_rgba(0,0,0,0.65)] lg:p-9"
      )}
    >
      {/* 1. Architectural Brand Logo */}
      <div className="flex items-center gap-3 mb-4 sm:mb-6">
        <Image
          src="/images/hr-realestate-mark.png"
          alt="HR Real Estate"
          width={44}
          height={44}
          priority
          className="w-10 h-10 sm:w-11 sm:h-11 object-contain drop-shadow-[0_4px_16px_rgba(0,0,0,0.7)]"
        />
        <div className="w-[1.5px] h-6 sm:h-7 bg-white/40" />
        <span className="font-heading font-bold text-[15px] sm:text-[17px] tracking-[0.14em] text-white uppercase whitespace-nowrap drop-shadow-[0_2px_12px_rgba(0,0,0,0.75)]">
          REAL ESTATE
        </span>
      </div>

      <h1 className="text-[21px] sm:text-[25px] font-bold text-white tracking-tight drop-shadow-[0_2px_12px_rgba(0,0,0,0.75)]">
        Sign in to HR Real Estate
      </h1>
      <p className="text-[12.5px] sm:text-[13px] text-slate-200/90 mt-1 sm:mt-1.5 leading-relaxed max-w-[320px] drop-shadow-[0_1px_6px_rgba(0,0,0,0.75)]">
        Portfolio management and property operations
      </p>

      {/* 2. Error / Access Denied Alert Banner */}
      {(errorParam || errorMessage) && (
        <div className="w-full mt-5 p-3.5 rounded-xl border border-rose-400/35 bg-[#090F1D]/85 backdrop-blur-md text-rose-200 text-left text-xs space-y-1 shadow-lg">
          <div className="flex items-center gap-1.5 font-semibold text-rose-100">
            <ShieldAlert className="w-4 h-4 text-rose-400 shrink-0" />
            <span>
              {errorParam === "access_denied" ? "Access Denied" : "Sign-in Notice"}
            </span>
          </div>
          <p className="text-[11.5px] leading-relaxed text-rose-200/90 pl-5.5">
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
      <div className="w-full mt-5 sm:mt-7 space-y-2.5 sm:space-y-3">
        <button
          type="button"
          onClick={handleGoogleLogin}
          disabled={isLoading}
          className={cn(
            "w-full h-12 rounded-xl bg-white hover:bg-slate-100 text-[#070D19] font-semibold text-sm transition-all flex items-center justify-center gap-3 px-4 cursor-pointer shadow-[0_10px_30px_rgba(0,0,0,0.45)] select-none disabled:opacity-50 disabled:cursor-not-allowed",
            "active:scale-[0.99]"
          )}
        >
          {isLoading ? (
            <>
              <Loader2 className="w-5 h-5 animate-spin text-[#0B1E3B]" />
              <span>Connecting to Google...</span>
            </>
          ) : (
            <>
              <GoogleIcon />
              <span>Continue with Google</span>
              <ArrowRight className="w-4 h-4 text-[#070D19]/60 ml-auto" />
            </>
          )}
        </button>
      </div>

      {/* 4. Whitelist Policy Badge */}
      <div className="mt-5 sm:mt-7 pt-3.5 sm:pt-4 border-t border-white/15 w-full flex items-center justify-center gap-1.5 text-[11px] font-mono text-slate-300/90 drop-shadow-[0_1px_4px_rgba(0,0,0,0.75)]">
        <Lock className="w-3.5 h-3.5 text-slate-200/80" />
        <span>Whitelist Access Only · Closed Portal</span>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <div className="h-dvh max-h-dvh lg:h-auto lg:min-h-dvh lg:max-h-none w-full bg-[#050A14] relative overflow-hidden overscroll-none touch-none lg:touch-auto flex flex-col justify-end lg:justify-center select-none">
      {/* Full-bleed twilight architectural property background */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/images/login-property-hero.jpg"
        alt="Residential canal-side architectural property at dusk"
        className="absolute inset-0 h-full w-full object-cover object-[28%_center] sm:object-[32%_center] lg:object-center"
      />

      {/* Top atmospheric tint for contrast */}
      <div className="absolute inset-0 bg-gradient-to-b from-[#040914]/35 via-transparent to-[#040812]/80 lg:to-[#040812]/55 pointer-events-none" />

      {/* Mobile progressive slight blur behind floating text & controls (no hard box edges) */}
      <div
        aria-hidden="true"
        className="lg:hidden absolute inset-x-0 bottom-0 h-[66%] backdrop-blur-[7px] bg-gradient-to-t from-[#030712]/90 via-[#07142B]/62 to-transparent pointer-events-none"
        style={{
          WebkitMaskImage: "linear-gradient(to top, black 55%, rgba(0,0,0,0.65) 78%, transparent 100%)",
          maskImage: "linear-gradient(to top, black 55%, rgba(0,0,0,0.65) 78%, transparent 100%)",
        }}
      />

      {/* Desktop horizontal deep-blue / black gradient wash on the right flank */}
      <div
        aria-hidden="true"
        className="hidden lg:block absolute inset-0 bg-gradient-to-r from-[#040914]/15 via-[#050E1E]/55 to-[#040914]/92 pointer-events-none"
      />

      {/* Foreground Content */}
      <div className="relative z-10 w-full max-w-7xl mx-auto px-5 sm:px-8 lg:px-14 pt-6 sm:pt-12 pb-[max(1.25rem,env(safe-area-inset-bottom))] lg:py-12 flex flex-col lg:flex-row items-center justify-end lg:justify-between gap-4 sm:gap-8 flex-1 min-h-0">
        {/* Desktop subtle left-bottom property label */}
        <div className="hidden lg:flex lg:self-end flex-col gap-1.5 text-left pb-2">
          <div className="flex items-center gap-2">
            <Image
              src="/images/hr-realestate-mark.png"
              alt="HR Real Estate"
              width={20}
              height={20}
              className="w-5 h-5 object-contain opacity-90"
            />
            <span className="text-[11px] font-mono uppercase tracking-[0.2em] text-slate-300/80">
              HR Real Estate Portal
            </span>
          </div>
          <p className="text-sm font-medium text-white/90 drop-shadow-[0_2px_10px_rgba(0,0,0,0.8)]">
            Private Residential & Commercial Portfolio Operations
          </p>
        </div>

        <div className="w-full max-w-[400px] lg:max-w-[420px] flex flex-col items-center">
          <Suspense
            fallback={
              <div className="flex items-center gap-2 text-white text-xs py-10">
                <Loader2 className="w-4 h-4 animate-spin text-white" />
                <span>Loading...</span>
              </div>
            }
          >
            <LoginForm />
          </Suspense>

          <div className="mt-3.5 sm:mt-5 text-[10.5px] sm:text-[11px] font-mono text-slate-300/75 text-center drop-shadow-[0_1px_4px_rgba(0,0,0,0.8)]">
            HR Real Estate Autonomous Operating System
          </div>
        </div>
      </div>
    </div>
  );
}
