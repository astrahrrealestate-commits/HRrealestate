"use client";

import React, { useState, useEffect } from "react";
import { X, UserPlus, Mail, Shield, Building, Check } from "lucide-react";
import { Button } from "@/components/ui/Button";

interface InvitePersonFormProps {
  isOpen: boolean;
  onClose: () => void;
  onInvite: (user: { name: string; email: string; role: string; complex: string }) => void;
}

/**
 * Mobile Full-Screen Form / Desktop Modal Dialog
 * Adheres strictly to Section 5.6.1:
 * "Invite person as a full-screen form"
 */
export function InvitePersonForm({
  isOpen,
  onClose,
  onInvite,
}: InvitePersonFormProps) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("Property Manager");
  const [complex, setComplex] = useState("All 3 Complexes (110 units)");

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    if (isOpen) {
      window.addEventListener("keydown", handleKeyDown);
    }
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !email.trim()) return;
    onInvite({ name, email, role, complex });
    setName("");
    setEmail("");
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs md:p-4">
      {/* Full-screen on mobile (< 768px), 520px dialog on desktop */}
      <div className="w-full h-full md:h-auto md:max-w-[520px] md:rounded-[var(--radius-pane)] bg-[var(--pane)] border-0 md:border border-[var(--line)] flex flex-col shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        
        {/* Header */}
        <div className="h-14 px-5 border-b border-[var(--line)] flex items-center justify-between shrink-0 bg-[var(--pane)]">
          <div className="flex items-center gap-2.5">
            <UserPlus className="w-4 h-4 text-[var(--ink-2)]" />
            <h3 className="text-sm font-bold text-[var(--ink)]">
              Invite Team Member
            </h3>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 text-[var(--ink-3)] hover:text-[var(--ink)] rounded-md cursor-pointer"
            aria-label="Close invite form"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-5 sm:p-6 space-y-4 text-xs">
          <div>
            <label className="text-xs font-semibold text-[var(--ink)] block mb-1">
              Full Name
            </label>
            <input
              type="text"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Saskia de Vries"
              className="w-full px-3 py-2 text-sm bg-[var(--bg)] border border-[var(--line)] rounded-md text-[var(--ink)] placeholder:text-[var(--ink-3)] focus:outline-none focus:border-[var(--ink-2)]"
            />
          </div>

          <div>
            <label className="text-xs font-semibold text-[var(--ink)] block mb-1">
              Email Address
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="saskia@estateos.com"
              className="w-full px-3 py-2 text-sm bg-[var(--bg)] border border-[var(--line)] rounded-md text-[var(--ink)] placeholder:text-[var(--ink-3)] focus:outline-none focus:border-[var(--ink-2)]"
            />
          </div>

          <div>
            <label className="text-xs font-semibold text-[var(--ink)] block mb-1">
              Organizational Role
            </label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="w-full px-3 py-2 text-sm bg-[var(--bg)] border border-[var(--line)] rounded-md text-[var(--ink)] focus:outline-none focus:border-[var(--ink-2)]"
            >
              <option value="Property Manager">Property Manager (Full Access)</option>
              <option value="Assistant Manager">Assistant Manager (Triage & Messages)</option>
              <option value="External Accountant">External Accountant (Financial Read-Only)</option>
            </select>
          </div>

          <div>
            <label className="text-xs font-semibold text-[var(--ink)] block mb-1">
              Complex Scope Allocation
            </label>
            <select
              value={complex}
              onChange={(e) => setComplex(e.target.value)}
              className="w-full px-3 py-2 text-sm bg-[var(--bg)] border border-[var(--line)] rounded-md text-[var(--ink)] focus:outline-none focus:border-[var(--ink-2)]"
            >
              <option value="All 3 Complexes (110 units)">All 3 Complexes (110 units)</option>
              <option value="Keizersgracht (42-46)">Keizersgracht (42-46)</option>
              <option value="Prinsengracht (118-124)">Prinsengracht (118-124)</option>
              <option value="Herengracht Historic">Herengracht Historic</option>
            </select>
          </div>

          <p className="text-[11px] text-[var(--ink-3)] pt-2 leading-relaxed">
            Invited members will receive an email link with mandatory 2FA enrollment. Roles are managed in accordance with GDPR tenant data protection standards.
          </p>

          {/* Sticky/Bottom Footer */}
          <div className="pt-4 border-t border-[var(--line)] flex items-center justify-end gap-2.5">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onClose}
              className="text-xs border border-[var(--line)]"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="ghost"
              size="sm"
              className="text-xs border border-[var(--line)] bg-[var(--ink)] text-white hover:bg-[var(--ink)]/90 font-semibold"
            >
              Send Invite
            </Button>
          </div>
        </form>

      </div>
    </div>
  );
}
