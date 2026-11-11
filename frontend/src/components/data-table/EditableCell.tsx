"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export type EditableCellVariant = "input" | "textarea" | "singleLineScroll";

export interface EditableCellProps {
  /** 当前显示/提交的值 */
  value: string | null | undefined;
  /** 失去焦点且内容有变化时调用，用于 PATCH（可返回任意 Promise） */
  onSave: (value: string) => Promise<unknown>;
  /** 展示形态：单行输入、多行文本、单行可滚动（不撑高） */
  variant?: EditableCellVariant;
  /** 非编辑态单行截断并通过 Tooltip 显示全文（项目内需列建议 false） */
  truncate?: boolean;
  placeholder?: string;
  className?: string;
  /** 只读时仅展示文字 */
  readOnly?: boolean;
}

function normalizeValue(v: string | null | undefined): string {
  return v == null ? "" : String(v).trim();
}

/** 单行可滚动区域的细滚动条样式（不遮挡文字） */
const scrollbarThinClass =
  "[&::-webkit-scrollbar]:h-1.5 [&::-webkit-scrollbar-track]:bg-transparent [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-muted [&::-webkit-scrollbar-thumb]:min-h-[20px]";

/** 可编辑单元格：流式布局，Input 严格限制在单元格内，不遮挡相邻单元格 */
export function EditableCell({
  value,
  onSave,
  variant = "input",
  truncate = true,
  placeholder = "",
  className,
  readOnly = false,
}: EditableCellProps) {
  const [editing, setEditing] = React.useState(false);
  const [local, setLocal] = React.useState(() => normalizeValue(value));
  const inputRef = React.useRef<HTMLInputElement | HTMLTextAreaElement>(null);

  const displayValue = normalizeValue(value);
  const isSingleLineScroll = variant === "singleLineScroll";
  const shouldTruncate = truncate && !isSingleLineScroll;
  const isEmpty = !displayValue;

  React.useEffect(() => {
    setLocal(normalizeValue(value));
  }, [value]);

  React.useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select?.();
    }
  }, [editing]);

  const handleBlur = React.useCallback(async () => {
    setEditing(false);
    const trimmed = local.trim();
    if (trimmed !== displayValue) {
      try {
        await onSave(trimmed);
      } catch (e) {
        setLocal(displayValue);
      }
    } else {
      setLocal(displayValue);
    }
  }, [local, displayValue, onSave]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    if (e.key === "Enter" && variant === "input") {
      e.currentTarget.blur();
    }
    if (e.key === "Escape") {
      setLocal(displayValue);
      setEditing(false);
      inputRef.current?.blur();
    }
  };

  const displayContent = displayValue || placeholder || "—";

  if (readOnly) {
    const span = (
      <span
        className={cn(
          "block truncate",
          isEmpty && "text-muted-foreground text-center",
          className
        )}
      >
        {displayContent}
      </span>
    );
    if (shouldTruncate && displayValue) {
      return (
        <Tooltip>
          <TooltipTrigger asChild>{span}</TooltipTrigger>
          <TooltipContent side="top" className="max-w-[320px] break-words">
            {displayValue}
          </TooltipContent>
        </Tooltip>
      );
    }
    return span;
  }

  if (!editing) {
    const trigger = (
      <div
        role="button"
        tabIndex={0}
        className={cn(
          "min-h-[2rem] w-full max-w-full cursor-text rounded border border-transparent px-0 py-0 text-left text-sm hover:border-input focus:outline-none focus:ring-1 focus:ring-ring focus:ring-inset",
          "box-border overflow-hidden",
          shouldTruncate && "truncate",
          isSingleLineScroll && "overflow-x-auto overflow-y-hidden whitespace-nowrap",
          isSingleLineScroll && scrollbarThinClass,
          isEmpty && "text-muted-foreground text-center",
          className
        )}
        onClick={() => setEditing(true)}
        onFocus={() => setEditing(true)}
      >
        {displayContent}
      </div>
    );
    if (shouldTruncate && displayValue) {
      return (
        <Tooltip>
          <TooltipTrigger asChild>{trigger}</TooltipTrigger>
          <TooltipContent side="top" className="max-w-[320px] break-words">
            {displayValue}
          </TooltipContent>
        </Tooltip>
      );
    }
    return trigger;
  }

  const commonProps = {
    ref: inputRef as React.RefObject<HTMLInputElement & HTMLTextAreaElement>,
    value: local,
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setLocal(e.target.value),
    onBlur: handleBlur,
    onKeyDown: handleKeyDown,
    placeholder: placeholder || undefined,
  };

  const inputClassName = cn(
    "w-full max-w-full box-border rounded border-2 border-primary bg-white px-2 py-1.5 text-sm",
    "focus:outline-none focus:ring-2 focus:ring-primary/20 focus:ring-inset",
    "dark:bg-white dark:text-gray-900",
    isSingleLineScroll && "overflow-x-auto overflow-y-hidden whitespace-nowrap",
    isSingleLineScroll && scrollbarThinClass
  );

  const editWrapperClassName =
    "w-full max-w-full box-border overflow-hidden p-1";

  if (variant === "textarea") {
    return (
      <div className={editWrapperClassName}>
        <textarea
          {...commonProps}
          rows={2}
          className={cn(inputClassName, "resize-none block")}
        />
      </div>
    );
  }

  return (
    <div className={editWrapperClassName}>
      <input
        {...commonProps}
        type="text"
        className={cn(inputClassName, "block")}
      />
    </div>
  );
}
