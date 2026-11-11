import React from "react";

export function FlagUK({ className = "w-3.5 h-2.5" }: { className?: string }) {
  return (
    <svg
      className={`${className} rounded-[2px] overflow-hidden inline-block shrink-0 shadow-2xs border border-white/10`}
      viewBox="0 0 60 30"
      aria-hidden="true"
    >
      <clipPath id="uk-flag-clip">
        <rect width="60" height="30" />
      </clipPath>
      <g clipPath="url(#uk-flag-clip)">
        <rect width="60" height="30" fill="#012169" />
        <path d="M0,0 L60,30 M60,0 L0,30" stroke="#FFFFFF" strokeWidth="6" />
        <path d="M0,0 L60,30 M60,0 L0,30" stroke="#C8102E" strokeWidth="4" />
        <path d="M30,0 v30 M0,15 h60" stroke="#FFFFFF" strokeWidth="10" />
        <path d="M30,0 v30 M0,15 h60" stroke="#C8102E" strokeWidth="6" />
      </g>
    </svg>
  );
}

export function FlagNL({ className = "w-3.5 h-2.5" }: { className?: string }) {
  return (
    <svg
      className={`${className} rounded-[2px] overflow-hidden inline-block shrink-0 shadow-2xs border border-white/10`}
      viewBox="0 0 9 6"
      aria-hidden="true"
    >
      <rect width="9" height="2" fill="#AE1C28" />
      <rect y="2" width="9" height="2" fill="#FFFFFF" />
      <rect y="4" width="9" height="2" fill="#21468B" />
    </svg>
  );
}

