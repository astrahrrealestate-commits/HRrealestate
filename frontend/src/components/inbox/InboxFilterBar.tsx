"use client";

import React from "react";
import {
  Search,
  MessageSquare,
  Mail,
  Layers,
  Wrench,
  Coins,
  FileText,
  ArrowUpDown,
  User,
  AlertTriangle,
  Building2,
  Receipt,
  Hammer,
  UserPlus,
  RefreshCw,
} from "lucide-react";
import { ChannelType } from "@/types/dashboard";
import { MessageCategory, SortOption, AudienceFilter } from "@/types/inbox";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Pill } from "@/components/ui/Pill";
import { cn } from "@/lib/utils";

interface InboxFilterBarProps {
  searchQuery: string;
  onSearchChange: (q: string) => void;
  selectedAudience: AudienceFilter;
  onAudienceChange: (aud: AudienceFilter) => void;
  selectedChannel: "all" | ChannelType;
  onChannelChange: (channel: "all" | ChannelType) => void;
  selectedCategory: "all" | MessageCategory;
  onCategoryChange: (category: "all" | MessageCategory) => void;
  urgentOnly: boolean;
  onToggleUrgentOnly: () => void;
  sortOption: SortOption;
  onSortChange: (sort: SortOption) => void;
  onSyncMailbox?: () => void;
  isSyncing?: boolean;
  counts: {
    all: number;
    whatsapp: number;
    gmail: number;
    tenants: number;
    contractors: number;
    inquiries: number;
    totalAll?: number;
    urgent: number;
    maintenance: number;
    payment: number;
    lease: number;
    contractor_update: number;
    contractor_repairs: number;
    contractor_invoices: number;
    complaint: number;
    admin: number;
  };
}

export function InboxFilterBar({
  searchQuery,
  onSearchChange,
  selectedAudience,
  onAudienceChange,
  selectedChannel,
  onChannelChange,
  selectedCategory,
  onCategoryChange,
  urgentOnly,
  onToggleUrgentOnly,
  sortOption,
  onSortChange,
  onSyncMailbox,
  isSyncing,
  counts,
}: InboxFilterBarProps) {
  const categories = React.useMemo(() => {
    if (selectedAudience === "inquiries") {
      return [
        { id: "all", label: "All prospective inquiries", count: counts.inquiries, icon: Layers },
        { id: "lease", label: "Viewing requests & listings", count: counts.inquiries, icon: FileText },
        { id: "general", label: "Requirements & criteria", count: 0, icon: Building2 },
      ];
    }

    if (selectedAudience === "contractors") {
      return [
        { id: "all", label: "All contractor comms", count: counts.contractors, icon: Layers },
        { id: "contractor_repairs", label: "Direct route & repairs", count: counts.contractor_repairs, icon: Wrench },
        { id: "contractor_invoices", label: "Quotes & invoices (money)", count: counts.contractor_invoices, icon: Receipt },
      ];
    }

    if (selectedAudience === "tenants") {
      return [
        { id: "all", label: "All tenant inquiries", count: counts.tenants, icon: Layers },
        { id: "maintenance", label: "Maintenance & repairs", count: counts.maintenance, icon: Wrench },
        { id: "payment", label: "Rent & payments", count: counts.payment, icon: Coins },
        { id: "lease", label: "Leases & contract", count: counts.lease, icon: FileText },
        { id: "complaint", label: "Complaints", count: counts.complaint, icon: AlertTriangle },
        { id: "admin", label: "Admin & municipal", count: counts.admin, icon: Building2 },
      ];
    }

    return [
      { id: "all", label: "All messages", count: counts.totalAll ?? counts.all, icon: Layers },
      { id: "contractor_repairs", label: "Direct route & repairs", count: counts.contractor_repairs, icon: Wrench },
      { id: "contractor_invoices", label: "Quotes & invoices", count: counts.contractor_invoices, icon: Receipt },
      { id: "maintenance", label: "Tenant maintenance", count: counts.maintenance, icon: Hammer },
      { id: "payment", label: "Rent & payments", count: counts.payment, icon: Coins },
      { id: "lease", label: "Leases & inquiries", count: counts.lease, icon: FileText },
    ];
  }, [selectedAudience, counts]);

  return (
    <div className="bg-[#FFFFFF] border-b border-[#E8E8E5] p-4 space-y-3 select-none">
      {/* 1. Primary Section Tabs: Tenants vs Contractors vs Inquiries (Segmented Control) */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
        <SegmentedControl
          value={selectedAudience}
          onChange={onAudienceChange}
          options={[
            { id: "tenants", label: "Tenants", count: counts.tenants, icon: <User className="w-3.5 h-3.5 text-[#444444]" /> },
            { id: "contractors", label: "Contractors & trades", count: counts.contractors, icon: <Wrench className="w-3.5 h-3.5 text-[#444444]" /> },
            { id: "inquiries", label: "Inquiries (leads)", count: counts.inquiries, icon: <UserPlus className="w-3.5 h-3.5 text-[#444444]" /> },
            { id: "all", label: "All", count: counts.totalAll ?? counts.all },
          ]}
        />

        {/* Global Search Bar */}
        <div className="relative flex-1 max-w-sm sm:max-w-md">
          <Search
            className="w-4 h-4 text-[#666666] absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none"
            strokeWidth={1.75}
          />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search phone, email, ticket, or name..."
            className="w-full h-9 pl-9 pr-8 rounded-[8px] bg-[#F0F0EE] border border-[#E8E8E5] text-[13px] text-[#0A0A0A] placeholder:text-[#666666] focus:outline-none focus:bg-[#FFFFFF] focus:border-[#0A0A0A] transition-colors"
          />
          {searchQuery && (
            <button
              onClick={() => onSearchChange("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-[12px] text-[#666666] hover:text-[#0A0A0A] cursor-pointer"
            >
              Clear
            </button>
          )}
        </div>

        {/* Sync Mailbox Button */}
        {onSyncMailbox && (
          <button
            onClick={onSyncMailbox}
            disabled={isSyncing}
            className="flex items-center gap-1.5 h-9 px-3 rounded-[8px] bg-[#FFFFFF] border border-[#E8E8E5] hover:bg-[#F0F0EE] hover:border-[#0A0A0A] text-[13px] font-semibold text-[#0A0A0A] transition-colors cursor-pointer disabled:opacity-50 flex-shrink-0"
            title="Fetch new emails from Gmail"
          >
            <RefreshCw className={cn("w-3.5 h-3.5 text-[#0A0A0A]", isSyncing && "animate-spin")} />
            <span>{isSyncing ? "Syncing..." : "Sync Mailbox"}</span>
          </button>
        )}
      </div>

      {/* 2. Secondary Bar: Channels (Segmented Control) & Urgent / Sort */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2.5 pt-1 border-t border-[#E8E8E5]">
        {/* Channel Segmented Control */}
        <SegmentedControl
          value={selectedChannel}
          onChange={onChannelChange}
          options={[
            { id: "all", label: "All channels" },
            {
              id: "whatsapp",
              label: "WhatsApp",
              count: counts.whatsapp,
              icon: <MessageSquare className="w-3 h-3 text-[#444444]" />,
            },
            {
              id: "gmail",
              label: "Gmail",
              count: counts.gmail,
              icon: <Mail className="w-3 h-3 text-[#444444]" />,
            },
          ]}
        />

        {/* Quick Filter: Urgent Only & Sort Selector */}
        <div className="flex items-center gap-2 self-end sm:self-auto">
          {/* Urgent Toggle Button */}
          <button
            onClick={onToggleUrgentOnly}
            className={cn(
              "px-2.5 py-1 rounded-full text-[12px] font-semibold transition-all cursor-pointer flex items-center gap-1.5",
              urgentOnly
                ? "bg-[#F25C05] text-[#0A0A0A]"
                : "bg-[#F0F0EE] text-[#444444] hover:text-[#0A0A0A]"
            )}
          >
            <span
              className={cn(
                "w-1.5 h-1.5 rounded-full",
                urgentOnly ? "bg-[#0A0A0A]" : "bg-[#666666]"
              )}
            />
            <span>Urgent only</span>
            <span className="text-[11px] tabular-nums opacity-80">
              ({counts.urgent})
            </span>
          </button>

          {/* Sort Selector */}
          <div className="flex items-center gap-1">
            <ArrowUpDown className="w-3.5 h-3.5 text-[#666666]" />
            <select
              value={sortOption}
              onChange={(e) => onSortChange(e.target.value as SortOption)}
              className="text-[12px] font-semibold text-[#444444] bg-[#FFFFFF] border border-[#E8E8E5] rounded-[8px] px-2 py-1 focus:outline-none focus:border-[#0A0A0A] cursor-pointer"
            >
              <option value="urgency">Sort: Urgency</option>
              <option value="latest">Sort: Latest</option>
              <option value="oldest">Sort: Oldest</option>
            </select>
          </div>
        </div>
      </div>

      {/* 3. Category Pills */}
      <div className="flex items-center gap-1.5 overflow-x-auto pb-0.5">
        {categories.map((cat) => {
          const Icon = cat.icon;
          const isSelected = selectedCategory === cat.id;

          return (
            <button
              key={cat.id}
              onClick={() => onCategoryChange(cat.id as "all" | MessageCategory)}
              className={cn(
                "px-2.5 py-1 rounded-full text-[12px] font-semibold flex items-center gap-1.5 transition-all whitespace-nowrap cursor-pointer",
                isSelected
                  ? "bg-[#0A0A0A] text-[#FFFFFF]"
                  : "bg-[#F0F0EE] text-[#444444] hover:text-[#0A0A0A]"
              )}
            >
              <Icon className="w-3 h-3 opacity-70" />
              <span>{cat.label}</span>
              <span className="text-[11px] opacity-70 tabular-nums">({cat.count})</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
