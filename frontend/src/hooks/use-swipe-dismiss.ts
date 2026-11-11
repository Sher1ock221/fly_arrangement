"use client";

import { useRef } from "react";
import type { TouchEventHandler } from "react";

interface SwipeDismissOptions {
  threshold?: number;
  onDismiss: () => void;
}

export function useSwipeDismiss({ onDismiss, threshold = 64 }: SwipeDismissOptions) {
  const startXRef = useRef<number | null>(null);
  const startYRef = useRef<number | null>(null);

  const onTouchStart: TouchEventHandler<HTMLElement> = (e) => {
    const t = e.touches[0];
    startXRef.current = t.clientX;
    startYRef.current = t.clientY;
  };

  const onTouchEnd: TouchEventHandler<HTMLElement> = (e) => {
    if (startXRef.current == null || startYRef.current == null) return;
    const t = e.changedTouches[0];
    const dx = t.clientX - startXRef.current;
    const dy = Math.abs(t.clientY - startYRef.current);
    // 左侧抽屉常见手势：向左滑动关闭
    if (dx < -threshold && dy < 40) {
      onDismiss();
    }
    startXRef.current = null;
    startYRef.current = null;
  };

  return { onTouchStart, onTouchEnd };
}
