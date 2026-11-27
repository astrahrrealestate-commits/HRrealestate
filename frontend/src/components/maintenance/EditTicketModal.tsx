"use client";

import React, { useState, useEffect } from "react";
import { MaintenanceTicket } from "@/lib/api";
import { X, Check, Wrench, Shield, MessageSquare, AlertCircle } from "lucide-react";
import { useLanguage } from "@/context/LanguageContext";

interface EditTicketModalProps {
  ticket: MaintenanceTicket;
  isOpen: boolean;
  onClose: () => void;
  onSave: (updatedTicket: MaintenanceTicket) => Promise<boolean>;
  onShowToast?: (msg: string) => void;
}

export function EditTicketModal({
  ticket,
  isOpen,
  onClose,
  onSave,
  onShowToast,
}: EditTicketModalProps) {
  const { t } = useLanguage();
  const [issueTitle, setIssueTitle] = useState(ticket.issueTitle || "");
  const [unitLabel, setUnitLabel] = useState(ticket.unitLabel || "");
  const [urgency, setUrgency] = useState(ticket.urgency || "normal");
  const [contractorName, setContractorName] = useState(ticket.contractorName || "");
  const [contractorTrade, setContractorTrade] = useState(ticket.contractorTrade || "");
  const [contractorPhone, setContractorPhone] = useState(ticket.contractorPhone || "");
  const [contractorEmail, setContractorEmail] = useState(ticket.contractorEmail || "");
  const [poBudgetCap, setPoBudgetCap] = useState(ticket.poBudgetCap || "");
  const [notes, setNotes] = useState(ticket.notes || "");
  const [contractorDraft, setContractorDraft] = useState(ticket.contractorDraft || "");
  const [tenantDraft, setTenantDraft] = useState(ticket.tenantDraft || "");
  const [isSaving, setIsSaving] = useState(false);

  // Seeded when the dialog opens or shows another ticket, never on a refetched copy of the same one: that would
  // overwrite what is being typed (a poll, an optimistic save and its rollback all rebuild the object).
  useEffect(() => {
    if (isOpen) {
      setIssueTitle(ticket.issueTitle || "");
      setUnitLabel(ticket.unitLabel || "");
      setUrgency(ticket.urgency || "normal");
      setContractorName(ticket.contractorName || "");
      setContractorTrade(ticket.contractorTrade || "");
      setContractorPhone(ticket.contractorPhone || "");
      setContractorEmail(ticket.contractorEmail || "");
      setPoBudgetCap(ticket.poBudgetCap || "");
      setNotes(ticket.notes || "");
      setContractorDraft(ticket.contractorDraft || "");
      setTenantDraft(ticket.tenantDraft || "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the ticket id, on purpose (see above)
  }, [isOpen, ticket.id]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // 1. Validate required non-empty text fields
    if (!issueTitle.trim()) {
      onShowToast?.("Work order issue description cannot be empty.");
      return;
    }
    if (!unitLabel.trim()) {
      onShowToast?.("Unit / property label cannot be empty.");
      return;
    }
    if (!contractorName.trim()) {
      onShowToast?.("Contractor name cannot be empty.");
      return;
    }

    // 2. Validate Budget Cap (strictly positive number, 0 and negative prohibited)
    const cleanedBudget = poBudgetCap.replace(/[^0-9.,]/g, "").replace(",", ".");
    const numBudget = parseFloat(cleanedBudget);
    if (isNaN(numBudget) || numBudget <= 0) {
      onShowToast?.("Budget cap must be a valid positive amount greater than 0.");
      return;
    }
    if (numBudget > 50000) {
      onShowToast?.("Budget cap cannot exceed € 50,000.");
      return;
    }

    // 3. Validate contractor phone if provided (6-25 characters)
    if (contractorPhone.trim() && !/^[+0-9\s\-()]{6,25}$/.test(contractorPhone.trim())) {
      onShowToast?.("Please enter a valid contractor phone number (6-25 digits).");
      return;
    }

    // 4. Validate email format if provided
    if (contractorEmail.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(contractorEmail.trim())) {
      onShowToast?.("Please enter a valid contractor email address.");
      return;
    }

    // 5. Validate outbound drafts (cannot be empty strings)
    if (!contractorDraft.trim()) {
      onShowToast?.("Contractor work order draft preview cannot be empty.");
      return;
    }
    if (!tenantDraft.trim()) {
      onShowToast?.("Tenant confirmation reply preview cannot be empty.");
      return;
    }

    setIsSaving(true);
    try {
      const formattedBudget = poBudgetCap.includes("€") ? poBudgetCap.trim() : `€ ${numBudget.toLocaleString("nl-NL")}`;
      const updated: MaintenanceTicket = {
        ...ticket,
        issueTitle: issueTitle.trim(),
        unitLabel: unitLabel.trim(),
        urgency: urgency as any,
        contractorName: contractorName.trim(),
        contractorTrade: contractorTrade.trim(),
        contractorPhone: contractorPhone.trim(),
        contractorEmail: contractorEmail.trim(),
        poBudgetCap: formattedBudget,
        notes: notes.trim(),
        contractorDraft: contractorDraft.trim(),
        tenantDraft: tenantDraft.trim(),
      };
      // Not saved: the page already said why; keep the dialog and its edits.
      if (!(await onSave(updated))) return;
      onShowToast?.(`Ticket ${ticket.ticketNumber} updated successfully.`);
      onClose();
    } catch {
      onShowToast?.("Failed to update ticket. Please try again.");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs animate-in fade-in duration-200">
      <div
        className="w-full max-w-[620px] bg-[var(--pane)] border border-[var(--line)] rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh] text-[var(--ink)]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div className="px-6 py-4.5 border-b border-[var(--line)] flex items-center justify-between shrink-0 bg-[var(--pane)]">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-[var(--accent)]/10 text-[var(--accent-ink)] flex items-center justify-center">
              <Wrench className="w-4.5 h-4.5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono font-bold text-[15px]">{ticket.ticketNumber}</span>
                <span className="text-[var(--ink-3)]">·</span>
                <span className="text-[14px] font-semibold text-[var(--ink)] truncate max-w-[280px]">
                  {t("Edit Work Order & Budget", "Werkorder & Budget Bewerken")}
                </span>
              </div>
              <p className="text-[12px] text-[var(--ink-3)] mt-0.5">
                {t("Customize contractor assignment, spending cap, and outbound messages", "Pas aannemertoewijzing, budgetlimiet en uitgaande berichten aan")}
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--ink-3)] hover:text-[var(--ink)] hover:bg-[var(--selected)] transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Body Form */}
        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto px-6 py-5 space-y-5 text-xs">
          {/* Section 1: Ticket Essentials */}
          <div className="space-y-3">
            <span className="text-[11px] font-bold uppercase tracking-wider text-[var(--ink-3)] block">
              1. Work Order Details
            </span>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-[12px] font-medium text-[var(--ink-2)]">Issue Description</label>
                <span className="text-[10px] text-[var(--ink-3)] font-mono">{issueTitle.length}/120</span>
              </div>
              <input
                type="text"
                value={issueTitle}
                onChange={(e) => setIssueTitle(e.target.value)}
                maxLength={120}
                required
                className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--line)] rounded-lg text-xs font-medium text-[var(--ink)] focus:outline-hidden focus:border-[var(--accent)] transition-colors"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[12px] font-medium text-[var(--ink-2)] mb-1">Unit / Property</label>
                <input
                  type="text"
                  value={unitLabel}
                  onChange={(e) => setUnitLabel(e.target.value)}
                  maxLength={60}
                  required
                  className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--line)] rounded-lg text-xs font-medium text-[var(--ink)] focus:outline-hidden focus:border-[var(--accent)] transition-colors"
                />
              </div>

              <div>
                <label className="block text-[12px] font-medium text-[var(--ink-2)] mb-1">Urgency</label>
                <select
                  value={urgency}
                  onChange={(e) => setUrgency(e.target.value as any)}
                  className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--line)] rounded-lg text-xs font-medium text-[var(--ink)] focus:outline-hidden focus:border-[var(--accent)] transition-colors"
                >
                  <option value="emergency">Emergency (4h SLA)</option>
                  <option value="high">High Priority (24h SLA)</option>
                  <option value="normal">Normal (48h SLA)</option>
                  <option value="low">Low Priority (7d SLA)</option>
                </select>
              </div>
            </div>
          </div>

          {/* Section 2: Contractor & Authorized PO Budget Cap */}
          <div className="space-y-3 pt-2 border-t border-[var(--line)]/70">
            <span className="text-[11px] font-bold uppercase tracking-wider text-[var(--ink-3)] block">
              2. Contractor & Authorized Budget Cap
            </span>

            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-1">
                <label className="block text-[12px] font-medium text-[var(--ink-2)] mb-1">Contractor Name</label>
                <input
                  type="text"
                  value={contractorName}
                  onChange={(e) => setContractorName(e.target.value)}
                  maxLength={80}
                  required
                  className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--line)] rounded-lg text-xs font-medium text-[var(--ink)] focus:outline-hidden focus:border-[var(--accent)] transition-colors"
                />
              </div>

              <div className="col-span-1">
                <label className="block text-[12px] font-medium text-[var(--ink-2)] mb-1">Trade Specialty</label>
                <input
                  type="text"
                  value={contractorTrade}
                  onChange={(e) => setContractorTrade(e.target.value)}
                  maxLength={60}
                  className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--line)] rounded-lg text-xs font-medium text-[var(--ink)] focus:outline-hidden focus:border-[var(--accent)] transition-colors"
                />
              </div>

              <div className="col-span-1">
                <label className="block text-[12px] font-medium text-[var(--ink-2)] mb-1">
                  PO Budget Cap
                </label>
                <div className="relative">
                  <input
                    type="text"
                    value={poBudgetCap}
                    onChange={(e) => setPoBudgetCap(e.target.value)}
                    maxLength={20}
                    placeholder="e.g. € 450"
                    required
                    className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--line)] rounded-lg text-xs font-mono font-bold text-[var(--ink)] focus:outline-hidden focus:border-[var(--accent)] transition-colors"
                  />
                  <Shield className="w-3.5 h-3.5 text-[var(--ink-3)] absolute right-2.5 top-2.5 pointer-events-none" />
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[12px] font-medium text-[var(--ink-2)] mb-1">Contractor Phone (WhatsApp)</label>
                <input
                  type="text"
                  value={contractorPhone}
                  onChange={(e) => setContractorPhone(e.target.value)}
                  maxLength={25}
                  placeholder="+31 6 12 34 56 78"
                  className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--line)] rounded-lg text-xs font-mono text-[var(--ink)] focus:outline-hidden focus:border-[var(--accent)] transition-colors"
                />
              </div>

              <div>
                <label className="block text-[12px] font-medium text-[var(--ink-2)] mb-1">Contractor Email (Work Order Dispatch)</label>
                <input
                  type="email"
                  value={contractorEmail}
                  onChange={(e) => setContractorEmail(e.target.value)}
                  maxLength={80}
                  placeholder="e.g. planning@chahalbouw.nl"
                  className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--line)] rounded-lg text-xs font-mono text-[var(--ink)] focus:outline-hidden focus:border-[var(--accent)] transition-colors"
                />
              </div>
            </div>

            <div>
              <label className="block text-[12px] font-medium text-[var(--ink-2)] mb-1">Internal Notes & Access</label>
              <input
                type="text"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                maxLength={200}
                placeholder="e.g. Lockbox code 4182"
                className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--line)] rounded-lg text-xs text-[var(--ink)] focus:outline-hidden focus:border-[var(--accent)] transition-colors"
              />
            </div>
          </div>

          {/* Section 3: Drafted Outbound Messages */}
          <div className="space-y-3 pt-2 border-t border-[var(--line)]/70">
            <span className="text-[11px] font-bold uppercase tracking-wider text-[var(--ink-3)] block">
              3. Outbound Message Previews
            </span>

            {/* Contractor Dispatch Message */}
            <div className="p-3 bg-[var(--bg)] border border-[var(--line)] rounded-xl space-y-1.5">
              <div className="flex items-center justify-between text-[11px]">
                <div className="flex items-center gap-1.5 font-semibold text-[var(--ink)]">
                  <Wrench className="w-3.5 h-3.5 text-[var(--accent-ink)]" />
                  <span>
                    {contractorName.trim()
                      ? `Work Order for Contractor (${contractorName.trim()})`
                      : "Work Order for Contractor (No contractor assigned)"}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-[var(--ink-3)] font-mono">{contractorDraft.length}/1500</span>
                  <span className="text-[var(--ink-3)] font-mono">
                    {contractorEmail.trim() && !contractorPhone.trim() ? "Email Dispatch" : "WhatsApp Dispatch"}
                  </span>
                </div>
              </div>
              <textarea
                rows={3}
                value={contractorDraft}
                onChange={(e) => setContractorDraft(e.target.value)}
                maxLength={1500}
                className="w-full p-2 bg-[var(--pane)] border border-[var(--line)] rounded-lg text-xs leading-relaxed text-[var(--ink)] focus:outline-hidden focus:border-[var(--accent)] resize-y"
              />
            </div>

            {/* Tenant Confirmation Message */}
            <div className="p-3 bg-[var(--bg)] border border-[var(--line)] rounded-xl space-y-1.5">
              <div className="flex items-center justify-between text-[11px]">
                <div className="flex items-center gap-1.5 font-semibold text-[var(--ink)]">
                  <MessageSquare className="w-3.5 h-3.5 text-blue-500" />
                  <span>Confirmation Reply for Tenant ({ticket.tenantName})</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-[var(--ink-3)] font-mono">{tenantDraft.length}/1500</span>
                  <span className="text-[var(--ink-3)] font-mono">Tenant Update</span>
                </div>
              </div>
              <textarea
                rows={3}
                value={tenantDraft}
                onChange={(e) => setTenantDraft(e.target.value)}
                maxLength={1500}
                className="w-full p-2 bg-[var(--pane)] border border-[var(--line)] rounded-lg text-xs leading-relaxed text-[var(--ink)] focus:outline-hidden focus:border-[var(--accent)] resize-y"
              />
            </div>
          </div>

          {/* Modal Footer Controls */}
          <div className="pt-3 border-t border-[var(--line)] flex items-center justify-between gap-3">
            <button
              type="button"
              onClick={onClose}
              disabled={isSaving}
              className="px-4 py-2 rounded-xl text-xs font-medium text-[var(--ink-2)] hover:text-[var(--ink)] hover:bg-[var(--selected)] transition-colors cursor-pointer border border-[var(--line)]"
            >
              {t("Cancel")}
            </button>

            <button
              type="submit"
              disabled={isSaving}
              className="px-5 py-2 rounded-xl text-xs font-semibold bg-[var(--ink)] text-white hover:bg-[var(--ink)]/90 transition-all cursor-pointer flex items-center gap-2 shadow-sm"
            >
              <Check className="w-3.5 h-3.5 text-[var(--accent)]" />
              <span>{isSaving ? t("Saving...", "Opslaan...") : t("Save Work Order Changes", "Wijzigingen opslaan")}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
