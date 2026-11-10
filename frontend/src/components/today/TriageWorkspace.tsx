"use client";

import React, { useState, useEffect } from "react";
import {
  MessageSquare,
  Mail,
  CheckCircle2,
  Clock,
  Sparkles,
  Send,
  Edit3,
  SkipForward,
  XCircle,
  Wrench,
  User,
  ShieldAlert,
  ArrowRight,
  Check,
  AlertTriangle,
  Zap,
  Globe,
  ChevronDown,
} from "lucide-react";
import { TriageItem, DraftOption, RecipientRole } from "@/types/dashboard";
import { cn } from "@/lib/utils";
import { getTriageCardData } from "@/lib/triageCardData";

interface TriageWorkspaceProps {
  items: TriageItem[];
  onApproveItem: (itemId: string, selectedDraft: DraftOption) => void;
  onSkipItem: (itemId: string) => void;
  onRejectItem: (itemId: string) => void;
  onResetItems?: () => void;
}

export function TriageWorkspace({
  items,
  onApproveItem,
  onSkipItem,
  onRejectItem,
  onResetItems,
}: TriageWorkspaceProps) {
  const [selectedId, setSelectedId] = useState<string>(items[0]?.id || "");
  const [filterChannel, setFilterChannel] = useState<string>("all");

  // Multi-party audience (Tenant vs Contractor) for items with dual-party dispatch
  const [targetAudience, setTargetAudience] = useState<"tenant" | "contractor">("tenant");
  // Draft version toggle: 0 for Draft 1, 1 for Draft 2
  const [activeDraftIndex, setActiveDraftIndex] = useState<number>(0);

  const [isEditing, setIsEditing] = useState<boolean>(false);
  const [editedText, setEditedText] = useState<string>("");
  const [recentlyApprovedId, setRecentlyApprovedId] = useState<string | null>(null);

  // Dropdown accordions for What I Understood and When You Approve
  const [isUnderstoodOpen, setIsUnderstoodOpen] = useState<boolean>(false);
  const [isApprovePlanOpen, setIsApprovePlanOpen] = useState<boolean>(false);

  // Sync selectedId when items change
  useEffect(() => {
    if (items.length > 0 && !items.find((i) => i.id === selectedId)) {
      setSelectedId(items[0].id);
      setActiveDraftIndex(0);
      setIsEditing(false);
      setIsUnderstoodOpen(false);
      setIsApprovePlanOpen(false);
    }
  }, [items, selectedId]);

  const activeItem = items.find((i) => i.id === selectedId) || items[0];

  // Channel is natively tied to the incoming message
  const nativeChannel = activeItem?.channel === "gmail" ? "gmail" : "whatsapp";

  // Resolve drafts for the native channel cleanly without any redundant channel switcher
  const getActiveDraftList = (): DraftOption[] => {
    if (!activeItem) return [];

    if (activeItem.multiPartyDrafts) {
      if (targetAudience === "contractor" && activeItem.multiPartyDrafts.contractorDrafts) {
        return nativeChannel === "gmail"
          ? activeItem.multiPartyDrafts.contractorDrafts.gmail
          : activeItem.multiPartyDrafts.contractorDrafts.whatsapp;
      }
      return nativeChannel === "gmail"
        ? activeItem.multiPartyDrafts.tenantDrafts.gmail
        : activeItem.multiPartyDrafts.tenantDrafts.whatsapp;
    }

    return activeItem.drafts || [];
  };

  const currentDraftList = getActiveDraftList();
  const currentDraft = currentDraftList[activeDraftIndex] || currentDraftList[0];

  // Reset custom edit text when draft changes
  useEffect(() => {
    if (currentDraft) {
      setEditedText(currentDraft.text);
      setIsEditing(false);
    }
  }, [activeItem?.id, targetAudience, activeDraftIndex, currentDraft?.id]);

  // Reset audience to tenant and close dropdowns when switching items
  useEffect(() => {
    setTargetAudience("tenant");
    setActiveDraftIndex(0);
    setIsEditing(false);
    setIsUnderstoodOpen(false);
    setIsApprovePlanOpen(false);
  }, [activeItem?.id]);

  // Keyboard shortcut listener: [A] Approve, [S] Skip, [R] Reject, [E] Edit, [1] Draft 1, [2] Draft 2
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (
        document.activeElement?.tagName === "INPUT" ||
        document.activeElement?.tagName === "TEXTAREA"
      ) {
        return;
      }

      if (e.key === "a" || e.key === "A") {
        if (activeItem && currentDraft) {
          handleApprove();
        }
      } else if (e.key === "s" || e.key === "S") {
        if (activeItem) {
          onSkipItem(activeItem.id);
        }
      } else if (e.key === "r" || e.key === "R") {
        if (activeItem) {
          onRejectItem(activeItem.id);
        }
      } else if (e.key === "e" || e.key === "E") {
        setIsEditing((prev) => !prev);
      } else if (e.key === "1") {
        setActiveDraftIndex(0);
      } else if (e.key === "2" && currentDraftList.length > 1) {
        setActiveDraftIndex(1);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [activeItem, currentDraft, isEditing, editedText, currentDraftList.length]);

  // Dynamic Accept: Dispatches whichever draft (Draft 1 or Draft 2) is active
  const handleApprove = () => {
    if (!activeItem || !currentDraft) return;
    setRecentlyApprovedId(activeItem.id);

    const draftToDispatch: DraftOption = {
      ...currentDraft,
      text: isEditing ? editedText : currentDraft.text,
    };

    setTimeout(() => {
      onApproveItem(activeItem.id, draftToDispatch);
      setRecentlyApprovedId(null);
    }, 150);
  };

  // Filter items for left list
  const filteredItems = items.filter((item) => {
    if (filterChannel === "all") return true;
    if (filterChannel === "tenants") return item.recipientRole === "tenant";
    if (filterChannel === "contractor") return item.recipientRole === "contractor";
    if (filterChannel === "urgent") return item.urgency === "emergency" || item.urgency === "high";
    if (filterChannel === "whatsapp") return item.channel === "whatsapp";
    if (filterChannel === "gmail") return item.channel === "gmail";
    return true;
  });

  // Empty state: All items cleared
  if (items.length === 0) {
    return (
      <div className="bg-white rounded-2xl border border-neutral-200/90 p-16 text-center shadow-xs flex flex-col items-center justify-center my-8">
        <div className="w-16 h-16 rounded-full bg-emerald-50 border border-emerald-200 flex items-center justify-center text-emerald-600 mb-5 shadow-2xs">
          <CheckCircle2 className="w-8 h-8" strokeWidth={2} />
        </div>
        <h3 className="text-xl font-bold text-neutral-900 mb-2">
          Inbox Zero · All Triage Clear
        </h3>
        <p className="text-sm text-neutral-500 max-w-md mx-auto mb-6 leading-relaxed">
          You've reviewed and approved all pending inbound requests from WhatsApp and Gmail.
          Zero messages are left in escrow.
        </p>
        {onResetItems && (
          <button
            onClick={onResetItems}
            className="px-5 py-2.5 rounded-full bg-black text-white text-xs font-semibold hover:bg-neutral-800 transition-all cursor-pointer shadow-xs"
          >
            Reset Demo Triage Queue
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* 2-Pane Split: Left Queue (w-2/5) & Right Action Workspace (w-3/5) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Pane: Needs You Queue */}
        <div className="lg:col-span-5 bg-white rounded-2xl border border-neutral-200/90 shadow-xs overflow-hidden flex flex-col">
          {/* Header & Filter Pills */}
          <div className="p-5 border-b border-neutral-100 space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <h2 className="text-lg font-bold text-neutral-900 tracking-tight">
                  Needs you
                </h2>
                <span className="text-xs font-bold text-neutral-500 bg-neutral-100 px-2 py-0.5 rounded-full">
                  {items.length}
                </span>
              </div>
            </div>

            {/* Filter Pills: All, Tenants, Contractors, Urgent, WhatsApp, Gmail */}
            <div className="flex items-center gap-1.5 flex-wrap">
              {[
                { id: "all", label: `All ${items.length}` },
                {
                  id: "tenants",
                  label: `Tenants ${items.filter((i) => i.recipientRole === "tenant").length}`,
                },
                {
                  id: "contractor",
                  label: `Contractors ${items.filter((i) => i.recipientRole === "contractor").length}`,
                },
                {
                  id: "urgent",
                  label: `▲ Urgent ${items.filter((i) => i.urgency === "emergency" || i.urgency === "high").length}`,
                },
                {
                  id: "whatsapp",
                  label: `WhatsApp ${items.filter((i) => i.channel === "whatsapp").length}`,
                },
                {
                  id: "gmail",
                  label: `Gmail ${items.filter((i) => i.channel === "gmail").length}`,
                },
              ].map((pill) => (
                <button
                  key={pill.id}
                  onClick={() => setFilterChannel(pill.id)}
                  className={cn(
                    "text-xs px-3 py-1.5 rounded-full font-medium transition-all cursor-pointer",
                    filterChannel === pill.id
                      ? "bg-neutral-900 text-white font-semibold"
                      : "bg-neutral-100 text-neutral-600 hover:bg-neutral-200/70"
                  )}
                >
                  {pill.label}
                </button>
              ))}
            </div>
          </div>

          {/* Queue Items List */}
          <div className="divide-y divide-neutral-100 overflow-y-auto max-h-[640px]">
            {filteredItems.map((item) => {
              const isSelected = item.id === selectedId;
              const isUrgent = item.urgency === "emergency" || item.urgency === "high";

              return (
                <div
                  key={item.id}
                  onClick={() => {
                    setSelectedId(item.id);
                    setActiveDraftIndex(0);
                    setIsEditing(false);
                  }}
                  className={cn(
                    "p-4 cursor-pointer transition-all relative flex items-start gap-3.5",
                    isSelected
                      ? "bg-gray-50 border-l-2 border-l-black"
                      : "hover:bg-gray-50/60 border-l-2 border-l-transparent",
                    recentlyApprovedId === item.id ? "opacity-40 scale-98" : ""
                  )}
                >
                  {/* Channel / Role Icon Circle */}
                  <div
                    className={cn(
                      "w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5",
                      isSelected
                        ? "bg-black text-white"
                        : "bg-gray-100 text-gray-700 border border-gray-200"
                    )}
                  >
                    {item.channel === "whatsapp" ? (
                      <MessageSquare className="w-4 h-4" />
                    ) : (
                      <Mail className="w-4 h-4" />
                    )}
                  </div>

                  {/* Item Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <span className="text-sm font-semibold text-gray-900 truncate">
                        {item.tenantMessage.length > 36
                          ? item.tenantMessage.slice(0, 36) + "..."
                          : item.tenantMessage}
                      </span>
                      {isUrgent && (
                        <span className="bg-red-50 text-red-700 border border-red-200 text-xs font-medium px-2 py-0.5 rounded-full flex-shrink-0 flex items-center gap-1">
                          Urgent
                        </span>
                      )}
                    </div>

                    <div className="text-xs text-gray-500 mb-1.5 flex items-center gap-1.5 truncate">
                      <span>{item.unitLabel}</span>
                      <span>·</span>
                      <span className="capitalize">{item.channel}</span>
                      {item.recipientRole === "contractor" && (
                        <>
                          <span>·</span>
                          <span className="text-gray-700 font-medium">Contractor</span>
                        </>
                      )}
                    </div>

                    {/* Proposed Action Preview */}
                    <div className="text-xs text-gray-700 font-medium flex items-center justify-between">
                      <span className="text-gray-900 truncate">
                        ✦ {item.recommendedAction}
                      </span>
                      <span className="text-gray-400 text-xs tabular-nums flex-shrink-0 ml-2">
                        {Math.round(item.confidenceScore * 100)}%
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Pane: Review & Approval Workspace */}
        {activeItem && (() => {
          const displayData = getTriageCardData(activeItem);
          if (!displayData) return null;

          return (
            <div className="lg:col-span-7 bg-white rounded-xl border border-gray-200 p-6 space-y-6">
              {/* Header: Channel, Time, Urgency, Recipient Badge */}
              <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-gray-100">
                <div className="flex items-center gap-2 text-xs font-medium text-gray-500">
                  <span className="inline-flex items-center gap-1.5 text-gray-700 font-medium bg-gray-100 px-2.5 py-1 rounded-full border border-gray-200">
                    {activeItem.channel === "whatsapp" ? (
                      <MessageSquare className="w-3.5 h-3.5 text-gray-600" />
                    ) : (
                      <Mail className="w-3.5 h-3.5 text-gray-600" />
                    )}
                    {displayData.channelBadge}
                  </span>
                  <span className="text-gray-300">·</span>
                  <span className="text-xs text-gray-500">
                    {activeItem.ticketNumber || activeItem.caseRef}
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  {/* Recipient Role Badge */}
                  <span className="text-xs px-2.5 py-1 rounded-full font-medium flex items-center gap-1.5 bg-gray-100 text-gray-700 border border-gray-200">
                    {activeItem.recipientRole === "contractor" ? (
                      <Wrench className="w-3.5 h-3.5 text-gray-500" />
                    ) : (
                      <User className="w-3.5 h-3.5 text-gray-500" />
                    )}
                    <span>{activeItem.recipientRoleDetail}</span>
                  </span>

                  {(activeItem.urgency === "emergency" || activeItem.urgency === "high") && (
                    <span className="bg-red-50 text-red-700 border border-red-200 text-xs font-medium px-2.5 py-1 rounded-full flex items-center gap-1">
                      Urgent
                    </span>
                  )}
                </div>
              </div>

              {/* Case Title & Property */}
              <div>
                <h1 className="text-2xl font-extrabold tracking-tight text-neutral-900">
                  {displayData.issueTitle}
                </h1>
                <p className="text-sm font-semibold text-neutral-500 mt-1">
                  {displayData.unitSubtitle}
                </p>
              </div>

              {/* Section 1: FROM THE MESSAGE */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-neutral-400">
                    FROM THE MESSAGE
                  </span>
                  <span className="text-xs font-mono text-neutral-500">
                    {displayData.sourceIdentifier}
                  </span>
                </div>

                <div className="bg-neutral-100/80 rounded-2xl p-5 border border-neutral-200/60 space-y-2.5">
                  <div className="text-xs font-mono text-neutral-500 flex items-center gap-2">
                    <span className="font-semibold text-neutral-700">{activeItem.senderName}</span>
                    <span>·</span>
                    <span>{activeItem.senderContact}</span>
                  </div>

                  <p className="text-sm text-neutral-900 leading-relaxed font-normal">
                    "
                    <span className="underline decoration-neutral-400 decoration-1 underline-offset-4 font-medium text-neutral-950">
                      {displayData.originalMessage}
                    </span>
                    "
                  </p>

                  {displayData.translatedLine && (
                    <div className="pt-2 border-t border-neutral-200/60 flex items-start gap-2 text-xs text-neutral-600 italic">
                      <Globe className="w-3.5 h-3.5 text-neutral-400 mt-0.5 flex-shrink-0" />
                      <span>{displayData.translatedLine}</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Section 2: WHAT I UNDERSTOOD (Dropdown / Collapsible) */}
              <div className="bg-white rounded-2xl border border-neutral-200/90 shadow-2xs overflow-hidden transition-all">
                <button
                  type="button"
                  onClick={() => setIsUnderstoodOpen((prev) => !prev)}
                  className="w-full p-4 flex items-center justify-between text-left hover:bg-neutral-50/80 transition-colors cursor-pointer"
                >
                  <div className="flex items-center gap-2.5 flex-wrap">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-neutral-500">
                      WHAT I UNDERSTOOD
                    </span>
                    <span className="text-xs font-semibold text-neutral-700 bg-neutral-100 px-2.5 py-0.5 rounded-full border border-neutral-200/70">
                      6 verified points
                    </span>
                    {!isUnderstoodOpen && (
                      <span className="text-xs text-neutral-400 hidden sm:inline truncate max-w-sm">
                        · {displayData.understanding.ticket}, {displayData.understanding.problem}
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-1.5 text-xs font-semibold text-neutral-500">
                    <span>{isUnderstoodOpen ? "Hide" : "Show breakdown"}</span>
                    <ChevronDown
                      className={cn(
                        "w-4 h-4 text-neutral-400 transition-transform duration-200",
                        isUnderstoodOpen && "rotate-180"
                      )}
                    />
                  </div>
                </button>

                {isUnderstoodOpen && (
                  <div className="p-4 pt-1 border-t border-neutral-100 bg-neutral-50/30">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
                      {/* Ticket */}
                      <div className="bg-white rounded-xl border border-neutral-200/90 p-3.5 flex items-start justify-between shadow-2xs">
                        <div>
                          <span className="text-[11px] font-semibold text-neutral-400 uppercase tracking-wider">
                            Ticket
                          </span>
                          <p className="text-sm font-bold text-neutral-900 mt-0.5">
                            {displayData.understanding.ticket}
                          </p>
                        </div>
                        <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-md border border-emerald-200">
                          <Check className="w-3 h-3 text-emerald-600" />
                          <span>Checked</span>
                        </span>
                      </div>

                      {/* Problem */}
                      <div className="bg-white rounded-xl border border-neutral-200/90 p-3.5 flex items-start justify-between shadow-2xs">
                        <div>
                          <span className="text-[11px] font-semibold text-neutral-400 uppercase tracking-wider">
                            Problem
                          </span>
                          <p className="text-sm font-bold text-neutral-900 mt-0.5">
                            {displayData.understanding.problem}
                          </p>
                        </div>
                        <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-md border border-emerald-200">
                          <Check className="w-3 h-3 text-emerald-600" />
                          <span>Checked</span>
                        </span>
                      </div>

                      {/* Unit */}
                      <div className="bg-white rounded-xl border border-neutral-200/90 p-3.5 flex items-start justify-between shadow-2xs">
                        <div>
                          <span className="text-[11px] font-semibold text-neutral-400 uppercase tracking-wider">
                            Unit
                          </span>
                          <p className="text-sm font-bold text-neutral-900 mt-0.5">
                            {displayData.understanding.unit}
                          </p>
                        </div>
                        <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-md border border-emerald-200">
                          <Check className="w-3 h-3 text-emerald-600" />
                          <span>Checked</span>
                        </span>
                      </div>

                      {displayData.understanding.tenantIsHome && (
<div className="bg-white rounded-xl border border-neutral-200/90 p-3.5 flex items-start justify-between shadow-2xs">
                        <div>
                          <span className="text-[11px] font-semibold text-neutral-400 uppercase tracking-wider">
                            Tenant is home
                          </span>
                          <p className="text-sm font-bold text-neutral-900 mt-0.5">
                            {displayData.understanding.tenantIsHome}
                          </p>
                        </div>
                        <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-md border border-emerald-200">
                          <Check className="w-3 h-3 text-emerald-600" />
                          <span>Checked</span>
                        </span>
                      </div>
)}

                      {/* Priority */}
                      <div className="bg-white rounded-xl border border-neutral-200/90 p-3.5 flex items-start justify-between shadow-2xs">
                        <div>
                          <span className="text-[11px] font-semibold text-neutral-400 uppercase tracking-wider">
                            Priority
                          </span>
                          <p className="text-sm font-bold text-neutral-900 mt-0.5">
                            {displayData.understanding.priority}
                          </p>
                        </div>
                        <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-md border border-emerald-200">
                          <Check className="w-3 h-3 text-emerald-600" />
                          <span>Checked</span>
                        </span>
                      </div>

                      {displayData.understanding.suggestedContractor && (
<div className="bg-white rounded-xl border border-neutral-200/90 p-3.5 flex items-start justify-between shadow-2xs">
                        <div>
                          <span className="text-[11px] font-semibold text-neutral-400 uppercase tracking-wider">
                            Suggested contractor
                          </span>
                          <p className="text-sm font-bold text-neutral-900 mt-0.5">
                            {displayData.understanding.suggestedContractor}
                          </p>
                        </div>
                        <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-md border border-emerald-200">
                          <Check className="w-3 h-3 text-emerald-600" />
                          <span>Checked</span>
                        </span>
                      </div>
)}
                    </div>
                  </div>
                )}
              </div>

              {/* Section 3: WHEN YOU APPROVE: only when the thread names real follow-up actions */}
{displayData.whenYouApprove.length > 0 && (

              <div className="bg-white rounded-2xl border border-neutral-200/90 shadow-2xs overflow-hidden transition-all">
                <button
                  type="button"
                  onClick={() => setIsApprovePlanOpen((prev) => !prev)}
                  className="w-full p-4 flex items-center justify-between text-left hover:bg-neutral-50/80 transition-colors cursor-pointer"
                >
                  <div className="flex items-center gap-2.5 flex-wrap">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-neutral-500">
                      WHEN YOU APPROVE
                    </span>
                    <span className="text-xs font-semibold text-emerald-700 bg-emerald-50 px-2.5 py-0.5 rounded-full border border-emerald-200">
                      {displayData.whenYouApprove.length} actions queued
                    </span>
                    {!isApprovePlanOpen && (
                      <span className="text-xs text-neutral-400 hidden sm:inline truncate max-w-sm">
                        · {displayData.whenYouApprove[0]}
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-1.5 text-xs font-semibold text-neutral-500">
                    <span>{isApprovePlanOpen ? "Hide" : "Show execution plan"}</span>
                    <ChevronDown
                      className={cn(
                        "w-4 h-4 text-neutral-400 transition-transform duration-200",
                        isApprovePlanOpen && "rotate-180"
                      )}
                    />
                  </div>
                </button>

                {isApprovePlanOpen && (
                  <div className="p-4 pt-1 border-t border-neutral-100 bg-neutral-50/30">
                    <div className="space-y-2.5 pt-2">
                      {displayData.whenYouApprove.map((action, idx) => (
                        <div key={idx} className="flex items-start gap-2.5 text-xs text-neutral-800">
                          <div className="w-5 h-5 rounded-full bg-neutral-200/80 flex items-center justify-center text-[11px] font-bold text-neutral-700 flex-shrink-0 mt-0.5">
                            {idx + 1}
                          </div>
                          <span className="leading-relaxed font-medium">{action}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
)}

{/* Section 4: REPLY TO TENANT / CONTRACTOR WORKSPACE */}
              <div className="bg-neutral-50/80 rounded-2xl border border-neutral-200/90 p-5 space-y-4">
                {/* Header: Language Detected Badge & Draft 1 vs Draft 2 Toggle */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-neutral-200/60">
                  <div className="flex items-center gap-2">
                    <span className="inline-flex items-center gap-1.5 text-xs font-bold text-neutral-800 bg-white px-3 py-1 rounded-full border border-neutral-200 shadow-2xs">
                      <Globe className="w-3.5 h-3.5 text-neutral-600" />
                      <span>{displayData.detectedLanguageBadge}</span>
                    </span>
                  </div>

                  {/* Clean Draft Version Selector (Draft 1 vs Draft 2) */}
                  <div className="flex items-center gap-2">
                    {currentDraftList.map((draft, idx) => (
                      <button
                        key={draft.id || idx}
                        onClick={() => {
                          setActiveDraftIndex(idx);
                          setIsEditing(false);
                        }}
                        className={cn(
                          "px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer flex items-center gap-1.5",
                          activeDraftIndex === idx
                            ? "bg-neutral-900 text-white shadow-2xs font-bold"
                            : "bg-white border border-neutral-200 text-neutral-700 hover:bg-neutral-100"
                        )}
                      >
                        <span>{draft.label || `Draft ${idx + 1}`}</span>
                        <span className="text-[10px] opacity-70 font-mono">[{idx + 1}]</span>
                      </button>
                    ))}

                    <button
                      onClick={() => setIsEditing((prev) => !prev)}
                      className={cn(
                        "text-xs px-3 py-1.5 rounded-lg border font-medium flex items-center gap-1.5 transition-colors cursor-pointer",
                        isEditing
                          ? "bg-neutral-900 text-white border-neutral-900 font-semibold"
                          : "bg-white border-neutral-200 text-neutral-700 hover:bg-neutral-100"
                      )}
                    >
                      <Edit3 className="w-3.5 h-3.5" />
                      <span>{isEditing ? "Done Editing" : "Edit [E]"}</span>
                    </button>
                  </div>
                </div>

                {/* Draft Content Box */}
                {isEditing ? (
                  <textarea
                    rows={4}
                    value={editedText}
                    onChange={(e) => setEditedText(e.target.value)}
                    className="w-full p-4 rounded-xl bg-white border-2 border-neutral-900 text-sm text-neutral-900 focus:outline-none focus:ring-0 leading-relaxed font-sans shadow-inner"
                    placeholder="Refine proposal message..."
                  />
                ) : (
                  <div className="p-4 rounded-xl bg-white border border-neutral-200/90 text-sm text-neutral-900 leading-relaxed shadow-2xs whitespace-pre-line font-normal">
                    {editedText || currentDraft?.text || displayData.replySnippet}
                  </div>
                )}

                {/* Optional translation note */}
                {displayData.replyTranslation && !isEditing && (
                  <div className="text-[11px] text-neutral-500 italic px-1 flex items-center gap-1.5">
                    <span>English meaning:</span>
                    <span className="text-neutral-600 truncate">"{displayData.replyTranslation}"</span>
                  </div>
                )}
              </div>

              {/* Bottom Action Footer with Dynamic Skip, Reject, and Approve */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pt-3 border-t border-neutral-100">
                <div className="flex items-center gap-2 text-xs text-neutral-500">
                  <span className="w-12 h-1.5 rounded-full bg-neutral-900 inline-block" />
                  <span className="font-semibold text-neutral-900">
                    {Math.round(activeItem.confidenceScore * 100)}% confident
                  </span>
                  <span>·</span>
                  <span className="truncate">
                    Matched address & ticket records
                  </span>
                </div>

                {/* Single set of dynamic actions: operates on the selected draft */}
                <div className="flex items-center gap-2 self-end sm:self-auto">
                  {/* Skip [S] */}
                  <button
                    onClick={() => onSkipItem(activeItem.id)}
                    className="px-4 py-2.5 rounded-xl border border-neutral-200 bg-white text-neutral-700 text-xs font-semibold hover:bg-neutral-50 transition-colors cursor-pointer flex items-center gap-1.5 shadow-2xs"
                    title="Move to end of queue [S]"
                  >
                    <span>Skip</span>
                    <span className="text-[10px] text-neutral-400 font-mono">[S]</span>
                  </button>

                  {/* Reject [R] */}
                  <button
                    onClick={() => onRejectItem(activeItem.id)}
                    className="px-4 py-2.5 rounded-xl border border-neutral-200 text-neutral-600 hover:text-red-700 hover:bg-red-50 hover:border-red-200 text-xs font-semibold transition-colors cursor-pointer flex items-center gap-1.5"
                    title={`Reject Draft [R]`}
                  >
                    <XCircle className="w-3.5 h-3.5 text-neutral-400" />
                    <span>Reject</span>
                    <span className="text-[10px] text-neutral-400 font-mono">[R]</span>
                  </button>

                  {/* Accept & Send [A] */}
                  <button
                    onClick={handleApprove}
                    className="px-5 py-2.5 rounded-xl bg-black hover:bg-neutral-800 text-white text-xs font-bold transition-all shadow-sm cursor-pointer flex items-center gap-2 active:scale-98"
                    title={`Approve & Send Draft via ${
                      nativeChannel === "whatsapp" ? "WhatsApp" : "Gmail"
                    } [A]`}
                  >
                    <span>Approve & Send</span>
                    <span className="text-[10px] bg-neutral-700 px-1.5 py-0.5 rounded font-mono text-white">
                      A
                    </span>
                  </button>
                </div>
              </div>
            </div>
          );
        })()}
      </div>
    </div>
  );
}
