"use client";

import React, { useState, useEffect } from "react";
import {
  BrainCircuit,
  Plus,
  RefreshCw,
  Trash2,
  CheckCircle2,
  Shield,
  User,
  Building,
  Home,
  Check,
  X,
  AlertCircle,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import {
  MemoryItem,
  getStandingRules,
  createStandingRule,
  retireStandingRule,
  approveStandingRule,
} from "@/lib/api";

const SEED_RULES: MemoryItem[] = [
  {
    id: "seed-1",
    company_id: "00000000-0000-0000-0000-000000000001",
    scope: "company",
    scope_id: null,
    kind: "preference",
    text: "Emergency plumbing call-out cap is €350 without requiring prior owner approval.",
    status: "active",
    origin: "owner",
    source_refs: [],
    confidence: 1.0,
    evidence_count: 3,
    last_used_at: null,
    valid_until: null,
    created_at: new Date(Date.now() - 86400000 * 3).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: "seed-2",
    company_id: "00000000-0000-0000-0000-000000000001",
    scope: "person",
    scope_id: null,
    kind: "preference",
    text: "Tenant Pieter Bakker prefers WhatsApp notifications over email.",
    status: "active",
    origin: "owner",
    source_refs: [],
    confidence: 1.0,
    evidence_count: 5,
    last_used_at: null,
    valid_until: null,
    created_at: new Date(Date.now() - 86400000 * 7).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: "seed-3",
    company_id: "00000000-0000-0000-0000-000000000001",
    scope: "company",
    scope_id: null,
    kind: "rule",
    text: "Always require contractor invoice PDF attachment before releasing final payment.",
    status: "active",
    origin: "distilled",
    source_refs: [],
    confidence: 0.95,
    evidence_count: 8,
    last_used_at: null,
    valid_until: null,
    created_at: new Date(Date.now() - 86400000 * 12).toISOString(),
    updated_at: new Date().toISOString(),
  },
];

export function MemoryRulesManager() {
  const [rules, setRules] = useState<MemoryItem[]>(SEED_RULES);
  const [isLoading, setIsLoading] = useState(false);
  const [filterScope, setFilterScope] = useState<string>("all");
  const [isAdding, setIsAdding] = useState(false);
  const [newText, setNewText] = useState("");
  const [newScope, setNewScope] = useState<"company" | "unit" | "person">("company");
  const [newKind, setNewKind] = useState<"preference" | "rule">("preference");
  const [submitting, setSubmitting] = useState(false);

  const fetchRules = async () => {
    setIsLoading(true);
    try {
      const items = await getStandingRules({ limit: 50 });
      if (items && items.length > 0) {
        setRules(items);
      } else {
        setRules(SEED_RULES);
      }
    } catch {
      setRules(SEED_RULES);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchRules();
  }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newText.trim()) return;

    setSubmitting(true);
    try {
      const created = await createStandingRule({
        text: newText.trim(),
        scope: newScope,
        kind: newKind,
      });

      if (created) {
        setRules((prev) => [created, ...prev]);
      } else {
        // Optimistic local add
        const optimisticItem: MemoryItem = {
          id: `local-${Date.now()}`,
          company_id: "00000000-0000-0000-0000-000000000001",
          scope: newScope,
          scope_id: null,
          kind: newKind,
          text: newText.trim(),
          status: "active",
          origin: "owner",
          source_refs: [],
          confidence: 1.0,
          evidence_count: 1,
          last_used_at: null,
          valid_until: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        };
        setRules((prev) => [optimisticItem, ...prev]);
      }

      setNewText("");
      setIsAdding(false);
    } finally {
      setSubmitting(false);
    }
  };

  const handleRetire = async (id: string) => {
    setRules((prev) =>
      prev.map((r) => (r.id === id ? { ...r, status: "retired" } : r))
    );
    await retireStandingRule(id);
  };

  const handleApprove = async (id: string) => {
    setRules((prev) =>
      prev.map((r) => (r.id === id ? { ...r, status: "active" } : r))
    );
    await approveStandingRule(id);
  };

  const filteredRules = rules.filter((r) => {
    if (filterScope === "all") return true;
    return r.scope === filterScope;
  });

  const activeCount = rules.filter((r) => r.status === "active").length;

  return (
    <div className="space-y-6">
      {/* Top Banner & Action */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-[var(--pane)] p-5 border border-[var(--line)] rounded-[var(--radius-pane)]">
        <div>
          <div className="flex items-center gap-2">
            <BrainCircuit className="w-5 h-5 text-indigo-600" />
            <h3 className="font-heading font-bold text-[17px] text-[var(--ink)]">
              AI Standing Rules & Memory (T5)
            </h3>
          </div>
          <p className="text-xs text-[var(--ink-2)] mt-1 max-w-xl">
            Rules, contractor caps, and tenant preferences continuously compiled into Astra and Inbox Proposer contexts.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={fetchRules}
            disabled={isLoading}
            className="text-xs gap-1.5 h-8"
          >
            <RefreshCw className={cn("w-3.5 h-3.5", isLoading && "animate-spin")} />
            Sync
          </Button>

          <Button
            size="sm"
            onClick={() => setIsAdding(true)}
            className="text-xs gap-1.5 h-8 bg-indigo-600 hover:bg-indigo-700 text-white"
          >
            <Plus className="w-3.5 h-3.5" />
            Add Rule
          </Button>
        </div>
      </div>

      {/* Inline Creation Form */}
      {isAdding && (
        <form
          onSubmit={handleCreate}
          className="p-5 bg-[var(--pane)] border-2 border-indigo-500/30 rounded-[var(--radius-pane)] space-y-4 shadow-sm"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-indigo-600">
              New Standing Rule
            </span>
            <button
              type="button"
              onClick={() => setIsAdding(false)}
              className="text-[var(--ink-3)] hover:text-[var(--ink)]"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div>
            <label className="block text-xs font-semibold text-[var(--ink)] mb-1">
              Rule Instruction or Preference
            </label>
            <input
              type="text"
              value={newText}
              onChange={(e) => setNewText(e.target.value)}
              placeholder="e.g. Cap plumbing emergency repairs to €350 without owner sign-off"
              className="w-full text-sm px-3.5 py-2.5 rounded-lg border border-[var(--line)] bg-[var(--bg)] text-[var(--ink)] focus:outline-none focus:ring-2 focus:ring-indigo-500"
              maxLength={300}
              autoFocus
            />
            <span className="block text-right text-[11px] text-[var(--ink-3)] mt-1">
              {newText.length}/300
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-[var(--ink)] mb-1">
                Scope
              </label>
              <select
                value={newScope}
                onChange={(e) => setNewScope(e.target.value as any)}
                className="w-full text-xs px-3 py-2 rounded-lg border border-[var(--line)] bg-[var(--bg)] text-[var(--ink)]"
              >
                <option value="company">Company-wide (All units & tenants)</option>
                <option value="unit">Unit-specific</option>
                <option value="person">Tenant-specific</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-[var(--ink)] mb-1">
                Classification
              </label>
              <select
                value={newKind}
                onChange={(e) => setNewKind(e.target.value as any)}
                className="w-full text-xs px-3 py-2 rounded-lg border border-[var(--line)] bg-[var(--bg)] text-[var(--ink)]"
              >
                <option value="preference">Landlord Preference</option>
                <option value="rule">Strict Policy Instruction</option>
              </select>
            </div>
          </div>

          <div className="flex items-center justify-end gap-2 pt-2">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => setIsAdding(false)}
              className="text-xs h-8"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={submitting || !newText.trim()}
              className="text-xs h-8 bg-indigo-600 hover:bg-indigo-700 text-white"
            >
              Save Rule
            </Button>
          </div>
        </form>
      )}

      {/* Filter Tabs & Counter */}
      <div className="flex items-center justify-between gap-3 text-xs">
        <div className="flex items-center gap-1.5 p-1 bg-[var(--line)]/40 rounded-lg">
          {(["all", "company", "person", "unit"] as const).map((sc) => (
            <button
              key={sc}
              onClick={() => setFilterScope(sc)}
              className={cn(
                "px-3 py-1 rounded-md font-medium capitalize transition-colors",
                filterScope === sc
                  ? "bg-[var(--pane)] text-[var(--ink)] shadow-2xs font-semibold"
                  : "text-[var(--ink-2)] hover:text-[var(--ink)]"
              )}
            >
              {sc === "person" ? "Tenants" : sc}
            </button>
          ))}
        </div>

        <span className="text-xs text-[var(--ink-3)] font-mono">
          {activeCount} active rules in memory
        </span>
      </div>

      {/* Rule Cards List */}
      <div className="divide-y divide-[var(--line)] border border-[var(--line)] rounded-[var(--radius-pane)] bg-[var(--pane)] overflow-hidden">
        {filteredRules.length === 0 ? (
          <div className="p-8 text-center text-xs text-[var(--ink-3)]">
            No rules recorded under this filter.
          </div>
        ) : (
          filteredRules.map((rule) => {
            const isRetired = rule.status === "retired";

            return (
              <div
                key={rule.id}
                className={cn(
                  "p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 transition-colors",
                  isRetired ? "opacity-50 bg-[var(--bg)]/40" : "hover:bg-[var(--selected)]/20"
                )}
              >
                <div className="space-y-1.5 min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span
                      className={cn(
                        "text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full",
                        rule.scope === "company" && "bg-blue-500/10 text-blue-700 border border-blue-500/20",
                        rule.scope === "person" && "bg-amber-500/10 text-amber-700 border border-amber-500/20",
                        rule.scope === "unit" && "bg-purple-500/10 text-purple-700 border border-purple-500/20"
                      )}
                    >
                      {rule.scope}
                    </span>

                    <span
                      className={cn(
                        "text-[10px] font-semibold px-2 py-0.5 rounded-full flex items-center gap-1",
                        rule.status === "active" && "bg-emerald-500/10 text-emerald-700 border border-emerald-500/20",
                        rule.status === "retired" && "bg-gray-500/10 text-gray-600 border border-gray-500/20",
                        rule.status === "proposed" && "bg-amber-500/10 text-amber-700 border border-amber-500/20"
                      )}
                    >
                      <span
                        className={cn(
                          "w-1.5 h-1.5 rounded-full",
                          rule.status === "active" && "bg-emerald-500",
                          rule.status === "retired" && "bg-gray-400",
                          rule.status === "proposed" && "bg-amber-500 animate-pulse"
                        )}
                      />
                      {rule.status}
                    </span>

                    <span className="text-[11px] text-[var(--ink-3)] font-mono">
                      {Math.round(rule.confidence * 100)}% verified · {rule.origin}
                    </span>
                  </div>

                  <p className="text-sm font-semibold text-[var(--ink)] leading-snug">
                    {rule.text}
                  </p>
                </div>

                {/* Actions */}
                <div className="shrink-0 flex items-center gap-2 pt-2 sm:pt-0">
                  {rule.status === "proposed" && (
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => handleApprove(rule.id)}
                      className="text-xs h-7 px-2.5 text-emerald-700 border-emerald-200 hover:bg-emerald-50"
                    >
                      <Check className="w-3.5 h-3.5 mr-1" />
                      Approve
                    </Button>
                  )}

                  {rule.status === "active" && (
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => handleRetire(rule.id)}
                      className="text-xs h-7 px-2.5 text-[var(--ink-2)] hover:text-red-600 hover:border-red-200"
                    >
                      <Trash2 className="w-3.5 h-3.5 mr-1" />
                      Retire
                    </Button>
                  )}

                  {rule.status === "retired" && (
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => handleApprove(rule.id)}
                      className="text-xs h-7 px-2.5 text-[var(--ink-3)] hover:text-[var(--ink)]"
                    >
                      Reactivate
                    </Button>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
