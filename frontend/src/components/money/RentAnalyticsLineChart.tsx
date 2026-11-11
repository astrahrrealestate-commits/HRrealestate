"use client";

import React, { useMemo } from "react";
import dynamic from "next/dynamic";
import type { ApexOptions } from "apexcharts";
import { HistoricalTrendPoint } from "@/lib/api";

// Dynamic import with SSR disabled to ensure window object is ready
const Chart = dynamic(() => import("react-apexcharts"), {
  ssr: false,
  loading: () => (
    <div className="h-64 w-full flex items-center justify-center text-xs text-[var(--ink-3)] font-mono">
      Loading chart...
    </div>
  ),
});

interface RentAnalyticsLineChartProps {
  trendPoints: HistoricalTrendPoint[];
  selectedMonth: string;
  onSelectMonth: (month: string) => void;
  chartView: "revenue" | "occupancy";
}

export function RentAnalyticsLineChart({
  trendPoints,
  selectedMonth,
  onSelectMonth,
  chartView,
}: RentAnalyticsLineChartProps) {
  const categories = useMemo(() => {
    return trendPoints.map((p) => p.month);
  }, [trendPoints]);

  const series = useMemo(() => {
    if (chartView === "revenue") {
      return [
        {
          name: "Scheduled Rent",
          data: trendPoints.map((p) => p.scheduled),
        },
        {
          name: "Collected Rent",
          data: trendPoints.map((p) => p.collected),
        },
      ];
    } else {
      return [
        {
          name: "Occupancy Rate (%)",
          data: trendPoints.map((p) => p.occupancyRate ?? 100),
        },
      ];
    }
  }, [trendPoints, chartView]);

  const options: ApexOptions = useMemo(() => {
    const isRevenue = chartView === "revenue";

    return {
      chart: {
        type: "line",
        height: 250,
        toolbar: { show: false },
        zoom: { enabled: false },
        fontFamily: "inherit",
        parentHeightOffset: 0,
        events: {
          markerClick: (_event: any, _chartContext: any, opts: any) => {
            const dataPointIndex = opts?.dataPointIndex;
            if (typeof dataPointIndex === "number" && dataPointIndex >= 0 && dataPointIndex < trendPoints.length) {
              onSelectMonth(trendPoints[dataPointIndex].billingMonth);
            }
          },
        },
      },
      // Anti-slop monochrome colors: Dark slate #0A1B2F and muted slate #94A3B8
      colors: isRevenue ? ["#94A3B8", "#0A1B2F"] : ["#0A1B2F"],
      stroke: {
        curve: "smooth",
        width: isRevenue ? [2, 2.5] : [2.5],
        dashArray: isRevenue ? [4, 0] : [0], // Dashed for scheduled, solid for collected
      },
      markers: {
        size: 4,
        strokeColors: "#FFFFFF",
        strokeWidth: 2,
        hover: { size: 6 },
      },
      grid: {
        borderColor: "var(--line, #E2E8F0)",
        strokeDashArray: 3,
        xaxis: { lines: { show: false } },
        yaxis: { lines: { show: true } },
        padding: { top: 0, right: 10, bottom: 0, left: 10 },
      },
      xaxis: {
        categories,
        axisBorder: { show: false },
        axisTicks: { show: false },
        labels: {
          style: {
            colors: "#64748B",
            fontSize: "12px",
            fontFamily: "var(--font-mono, monospace)",
          },
        },
      },
      yaxis: {
        labels: {
          style: {
            colors: "#64748B",
            fontSize: "11px",
            fontFamily: "var(--font-mono, monospace)",
          },
          formatter: (val: number) => {
            if (isRevenue) {
              return `€${Math.round(val / 1000)}k`;
            }
            return `${val.toFixed(1)}%`;
          },
        },
        min: isRevenue ? 155000 : 90,
        max: isRevenue ? 170000 : 102,
        tickAmount: 4,
      },
      legend: {
        show: false, // We render our own clean external legend
      },
      tooltip: {
        theme: "light",
        shared: true,
        intersect: false,
        style: { fontSize: "12px", fontFamily: "inherit" },
        y: {
          formatter: (val: number) => {
            if (isRevenue) {
              return `€ ${val.toLocaleString("nl-NL", { minimumFractionDigits: 2 })}`;
            }
            return `${val.toFixed(1)}% occupied`;
          },
        },
      },
      annotations: {
        xaxis: [
          {
            x: trendPoints.find((p) => p.billingMonth === selectedMonth)?.month,
            strokeDashArray: 2,
            borderColor: "#0A1B2F",
            label: {
              borderColor: "#0A1B2F",
              style: {
                color: "#FFFFFF",
                background: "#0A1B2F",
                fontSize: "10px",
                fontFamily: "var(--font-mono, monospace)",
              },
              text: "Selected",
            },
          },
        ],
      },
    };
  }, [categories, chartView, onSelectMonth, selectedMonth, trendPoints]);

  return (
    <div className="w-full">
      <Chart options={options} series={series} type="line" height={250} />
    </div>
  );
}
