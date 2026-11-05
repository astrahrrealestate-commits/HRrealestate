"use client";

import React from "react";
import { useRouter } from "next/navigation";
import { ArrowUpRight, UserPlus, Calendar, Mail, MessageSquare, CheckCircle2 } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Pill } from "@/components/ui/Pill";
import { ProspectiveInquiry } from "@/lib/api";

interface ProspectiveInquiriesCardProps {
  inquiries?: ProspectiveInquiry[];
  onReviewInquiries?: () => void;
}

const DEFAULT_LEADS: ProspectiveInquiry[] = [
  {
    id: "lead-1",
    name: "Sanne Meijer",
    contact: "sanne.meijer@uva.nl",
    channel: "gmail",
    unit: "Pieter Floriszstraat 1 C",
    moveIn: "1 Nov 2026",
    request: "Viewing request · Thursday 15:00 slot",
    qualification: "3.2x income verified (UvA lecturer)",
    status: "AI draft ready",
  },
  {
    id: "lead-2",
    name: "Lucas van Dijk",
    contact: "+31 6 81 29 44 10",
    channel: "whatsapp",
    unit: "Singel 412 Studio",
    moveIn: "1 Nov 2026",
    request: "Studio availability & viewing inquiry",
    qualification: "Preliminary criteria met",
    status: "AI draft ready",
  },
  {
    id: "lead-3",
    name: "Elena Rostova",
    contact: "elena.rostova@booking.com",
    channel: "gmail",
    unit: "Keizersgracht 42-B",
    moveIn: "15 Nov 2026",
    request: "Viewing & expat registration query",
    qualification: "Booking.com Senior Software Engineer",
    status: "AI draft ready",
  },
];

export function ProspectiveInquiriesCard({ inquiries, onReviewInquiries }: ProspectiveInquiriesCardProps) {
  const router = useRouter();

  const handleReview = () => {
    if (onReviewInquiries) {
      onReviewInquiries();
    } else {
      router.push("/inbox?audience=inquiries");
    }
  };

  const leads = inquiries && inquiries.length > 0 ? inquiries : DEFAULT_LEADS;

  return (
    <Card className="flex flex-col justify-between">
      <div>
        {/* Header */}
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-[#F0F0EE] flex items-center justify-center text-[#0A0A0A]">
              <UserPlus className="w-4 h-4 text-[#1a73e8]" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-[16px] font-semibold text-[#0A0A0A] leading-tight">
                  New tenant inquiries
                </h3>
                <Pill variant="needs_you">{leads.length} leads</Pill>
              </div>
              <span className="text-[12.5px] text-[#666666] mt-0.5 block">
                Prospective tenants awaiting viewing slots & qualification review
              </span>
            </div>
          </div>

          <Button
            variant="ghost"
            size="sm"
            onClick={handleReview}
            className="text-[#0A0A0A] hover:text-[#444444] font-semibold h-8 px-3"
          >
            <span>Review in Inbox</span>
            <ArrowUpRight className="w-3.5 h-3.5 ml-1" />
          </Button>
        </div>

        {/* Responsive Leads Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5 mt-3.5">
          {leads.map((lead) => (
            <div
              key={lead.id}
              onClick={handleReview}
              className="p-3.5 rounded-[12px] bg-[#F0F0EE]/60 hover:bg-[#F0F0EE] border border-[#E8E8E5] transition-colors cursor-pointer flex flex-col justify-between space-y-2.5"
            >
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center gap-2">
                    <span className="text-[13.5px] font-semibold text-[#0A0A0A]">
                      {lead.name}
                    </span>
                    <span className="text-[#D2D2CE]">·</span>
                    <span className="text-[12px] text-[#666666] flex items-center gap-1">
                      {lead.channel === "gmail" ? (
                        <Mail className="w-3 h-3 text-[#666666]" />
                      ) : (
                        <MessageSquare className="w-3 h-3 text-[#666666]" />
                      )}
                      <span className="truncate max-w-[140px]">{lead.unit}</span>
                    </span>
                  </div>

                  <span className="text-[11px] font-semibold text-[#444444] bg-[#FFFFFF] px-2 py-0.5 rounded-full border border-[#E8E8E5] flex-shrink-0">
                    {lead.status}
                  </span>
                </div>

                <p className="text-[12.5px] text-[#222222] font-medium leading-snug">
                  {lead.request}
                </p>
                <div className="text-[11.5px] text-[#666666] mt-1.5 flex items-center gap-1.5">
                  <CheckCircle2 className="w-3 h-3 text-[#0A0A0A] flex-shrink-0" />
                  <span className="truncate">{lead.qualification}</span>
                </div>
              </div>

              <div className="pt-2 border-t border-[#E8E8E5]/70 flex items-center justify-between text-[11.5px] text-[#666666]">
                <span>Move-in: {lead.moveIn}</span>
                <span className="text-[#0A0A0A] font-semibold flex items-center gap-0.5 hover:underline">
                  Review draft →
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Action Footer */}
      <div className="pt-3 mt-4 border-t border-[#E8E8E5] flex items-center justify-between text-xs">
        <span className="text-[#444444] text-[12.5px] flex items-center gap-1.5">
          <Calendar className="w-3.5 h-3.5 text-[#1a73e8]" />
          <span>Next viewing: Thursday 15:00 · Automated confirmations queued</span>
        </span>

        <Button
          variant="ghost"
          size="sm"
          onClick={handleReview}
          className="text-[#0A0A0A] hover:text-[#444444] font-semibold h-8 px-2"
        >
          <span>Open all inquiries</span>
          <ArrowUpRight className="w-3.5 h-3.5 ml-1" />
        </Button>
      </div>
    </Card>
  );
}
