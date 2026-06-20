import { CaretLeft, CaretRight } from "@phosphor-icons/react";

interface CollapseButtonProps {
  collapsed: boolean;
  side: "left" | "right";
  onToggle: () => void;
  ariaLabel: string;
}

export function CollapseButton({ collapsed, side, onToggle, ariaLabel }: CollapseButtonProps) {
  const Icon = collapsed
    ? (side === "left" ? CaretRight : CaretLeft)
    : (side === "left" ? CaretLeft : CaretRight);

  const positionClass = side === "left"
    ? "right-0 translate-x-1/2"
    : "left-0 -translate-x-1/2";

  return (
    <button
      aria-label={ariaLabel}
      className={
        "absolute top-1/2 -translate-y-1/2 z-10 " + positionClass + " " +
        "inline-flex items-center justify-center w-5 h-10 border border-slate-300 dark:border-slate-600 " +
        "rounded-full bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 " +
        "hover:bg-slate-100 dark:hover:bg-slate-700 hover:text-slate-700 dark:hover:text-slate-200 " +
        "cursor-pointer transition-colors duration-150 shadow-sm"
      }
      onClick={onToggle}
      type="button"
    >
      <Icon size={12} weight="bold" />
    </button>
  );
}