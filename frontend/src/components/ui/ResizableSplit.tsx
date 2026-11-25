"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { cn } from "@/lib/utils";

export interface ResizeHandleProps {
  orientation?: "horizontal" | "vertical";
  onDragDelta: (delta: number) => void;
  onDragEnd?: () => void;
  onDoubleClick?: () => void;
  className?: string;
  ariaLabel?: string;
}

/**
 * Antigravity-style hairline drag divider between resizable panes.
 * Uses Pointer Events with setPointerCapture for smooth 60fps dragging.
 */
export function ResizeHandle({
  orientation = "horizontal",
  onDragDelta,
  onDragEnd,
  onDoubleClick,
  className,
  ariaLabel = "Resize panel",
}: ResizeHandleProps) {
  const [isDragging, setIsDragging] = useState(false);
  const lastPosRef = useRef<number>(0);

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    lastPosRef.current = orientation === "horizontal" ? e.clientX : e.clientY;
    setIsDragging(true);
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!isDragging) return;
    const current = orientation === "horizontal" ? e.clientX : e.clientY;
    const delta = current - lastPosRef.current;
    if (delta !== 0) {
      lastPosRef.current = current;
      onDragDelta(delta);
    }
  };

  const handlePointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!isDragging) return;
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {}
    setIsDragging(false);
    onDragEnd?.();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 40 : 16;
    if (orientation === "horizontal") {
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        onDragDelta(-step);
        onDragEnd?.();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        onDragDelta(step);
        onDragEnd?.();
      }
    } else {
      if (e.key === "ArrowUp") {
        e.preventDefault();
        onDragDelta(-step);
        onDragEnd?.();
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        onDragDelta(step);
        onDragEnd?.();
      }
    }
  };

  const isHorizontal = orientation === "horizontal";

  return (
    <div
      role="separator"
      aria-orientation={isHorizontal ? "vertical" : "horizontal"}
      aria-label={ariaLabel}
      tabIndex={0}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
      onDoubleClick={onDoubleClick}
      onKeyDown={handleKeyDown}
      title="Drag to resize · Double-click to reset"
      className={cn(
        "group relative shrink-0 select-none touch-none z-20 focus:outline-none",
        isHorizontal
          ? "w-[5px] -mx-[2px] h-full cursor-col-resize"
          : "h-[5px] -my-[2px] w-full cursor-row-resize",
        className
      )}
    >
      <div
        className={cn(
          "absolute transition-colors duration-150",
          isHorizontal
            ? "inset-y-0 left-[2px] w-[1px]"
            : "inset-x-0 top-[2px] h-[1px]",
          isDragging
            ? "bg-[var(--accent)] shadow-[0_0_0_1px_var(--accent)]"
            : "bg-transparent group-hover:bg-[var(--accent)]/70 group-focus-visible:bg-[var(--accent)]"
        )}
      />
    </div>
  );
}

export function usePersistedPaneSize(
  storageKey: string,
  defaultSize: number,
  minSize: number,
  maxSize: number
) {
  const [size, setSize] = useState<number>(defaultSize);
  const sizeRef = useRef<number>(defaultSize);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw !== null) {
        const parsed = Number(raw);
        if (!Number.isNaN(parsed) && parsed >= minSize && parsed <= maxSize) {
          setSize(parsed);
          sizeRef.current = parsed;
        }
      }
    } catch {}
  }, [storageKey, minSize, maxSize]);

  const applyDelta = useCallback(
    (delta: number) => {
      setSize((prev) => {
        const next = Math.min(maxSize, Math.max(minSize, prev + delta));
        sizeRef.current = next;
        return next;
      });
    },
    [minSize, maxSize]
  );

  const commitSize = useCallback(() => {
    try {
      localStorage.setItem(storageKey, String(Math.round(sizeRef.current)));
    } catch {}
  }, [storageKey]);

  const resetSize = useCallback(() => {
    setSize(defaultSize);
    sizeRef.current = defaultSize;
    try {
      localStorage.setItem(storageKey, String(defaultSize));
    } catch {}
  }, [storageKey, defaultSize]);

  return { size, setSize, applyDelta, commitSize, resetSize };
}
