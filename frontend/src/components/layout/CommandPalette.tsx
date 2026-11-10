"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Building2, FileText, Search, User, Wrench } from "lucide-react";
import { searchEverything, type SearchHit } from "@/lib/searchApi";
import { cn } from "@/lib/utils";

const DEBOUNCE_MS = 200;
const MIN_QUERY_CHARS = 2;
const HIDDEN_ON = ["/login"];

const KIND_LABEL: Record<SearchHit["kind"], string> = {
  person: "People",
  unit: "Properties",
  case: "Cases",
  document: "Documents",
};

const KIND_ICON = {
  person: User,
  unit: Building2,
  case: Wrench,
  document: FileText,
} as const;

/** Pages have no deep-link params yet, so a hit opens the page that owns that kind of record. */
export function destinationFor(hit: SearchHit): string {
  switch (hit.kind) {
    case "person":
      return hit.person_kind === "tenant" ? "/tenants" : "/contacts";
    case "unit":
      return "/properties";
    case "case":
      return "/maintenance";
    case "document":
      return "/inbox";
  }
}

export function CommandPalette() {
  const router = useRouter();
  const pathname = usePathname();
  const inputRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<{ query: string; hits: SearchHit[] | null } | null>(null);
  const [active, setActive] = useState(0);
  const trimmed = query.trim();
  const searchable = trimmed.length >= MIN_QUERY_CHARS;
  const hits = (searchable && result?.hits) || [];
  const failed = searchable && result?.query === trimmed && result.hits === null;
  const loading = searchable && result?.query !== trimmed;

  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
    setResult(null);
    setActive(0);
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((prev) => !prev);
      } else if (event.key === "Escape") {
        close();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [close]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open || trimmed.length < MIN_QUERY_CHARS) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      const found = await searchEverything(trimmed, controller.signal);
      if (!controller.signal.aborted) {
        setResult({ query: trimmed, hits: found });
        setActive(0);
      }
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [trimmed, open]);

  const choose = useCallback(
    (hit: SearchHit) => {
      close();
      router.push(destinationFor(hit));
    },
    [close, router],
  );

  function onInputKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" && hits.length > 0) {
      event.preventDefault();
      setActive((prev) => (prev + 1) % hits.length);
    } else if (event.key === "ArrowUp" && hits.length > 0) {
      event.preventDefault();
      setActive((prev) => (prev - 1 + hits.length) % hits.length);
    } else if (event.key === "Enter" && hits[active]) {
      event.preventDefault();
      choose(hits[active]);
    }
  }

  if (!open || HIDDEN_ON.includes(pathname)) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 px-4 pt-[15vh]"
      onMouseDown={close}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Search EstateOS"
        className="w-full max-w-xl overflow-hidden rounded-xl border border-[#27272a] bg-[#1B1B1B] shadow-2xl"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-[#27272a] px-4">
          <Search className="h-4 w-4 text-zinc-400" aria-hidden />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onInputKeyDown}
            placeholder="Search people, properties, cases, documents"
            className="h-12 flex-1 bg-transparent text-sm text-white outline-none placeholder:text-zinc-500"
            maxLength={100}
          />
          <kbd className="rounded border border-[#27272a] px-1.5 py-0.5 text-[10px] text-zinc-400">Esc</kbd>
        </div>
        <ul className="max-h-[50vh] overflow-y-auto py-1" role="listbox">
          {hits.map((hit, index) => {
            const Icon = KIND_ICON[hit.kind];
            const startsGroup = index === 0 || hits[index - 1].kind !== hit.kind;
            return (
              <React.Fragment key={`${hit.kind}:${hit.id}`}>
                {startsGroup && (
                  <li className="px-4 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wide text-zinc-500">
                    {KIND_LABEL[hit.kind]}
                  </li>
                )}
                <li
                  role="option"
                  aria-selected={index === active}
                  className={cn(
                    "flex cursor-pointer items-center gap-3 px-4 py-2 text-sm text-zinc-200",
                    index === active && "bg-white/10",
                  )}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => choose(hit)}
                >
                  <Icon className="h-4 w-4 shrink-0 text-zinc-400" aria-hidden />
                  <span className="truncate">{hit.title}</span>
                  {hit.subtitle && <span className="ml-auto shrink-0 text-xs text-zinc-500">{hit.subtitle}</span>}
                </li>
              </React.Fragment>
            );
          })}
          {failed && (
            <li className="px-4 py-6 text-center text-sm text-amber-400">Search is unavailable right now. Try again.</li>
          )}
          {searchable && !loading && !failed && hits.length === 0 && (
            <li className="px-4 py-6 text-center text-sm text-zinc-500">Nothing found for “{trimmed}”</li>
          )}
          {!searchable && (
            <li className="px-4 py-6 text-center text-sm text-zinc-500">Type at least 2 characters</li>
          )}
        </ul>
      </div>
    </div>
  );
}
