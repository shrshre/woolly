import { useState } from "react";
import { useRotatingPlaceholder } from "../hooks/useRotatingPlaceholder";

interface RotatingSearchInputProps {
  value: string;
  onChange: (value: string) => void;
  onFocus?: () => void;
  onBlur?: () => void;
  disabled?: boolean;
  ariaLabel: string;
  samples?: readonly string[];
  /** Static text before the rotating sample (e.g. "Try "). */
  prefix?: string;
  /** Wrap each sample in curly quotes. */
  quoteSample?: boolean;
  /** When set, shown instead of rotating samples (e.g. a follow-up hint). */
  staticPlaceholder?: string;
  pauseRotation?: boolean;
}

/** Search-style input whose empty-state hint fades between samples. Uses a
 *  custom overlay because native placeholders can't be animated. */
export function RotatingSearchInput({
  value,
  onChange,
  onFocus,
  onBlur,
  disabled,
  ariaLabel,
  samples,
  prefix = "",
  quoteSample = false,
  staticPlaceholder,
  pauseRotation = false,
}: RotatingSearchInputProps) {
  const [focused, setFocused] = useState(false);
  const rotating = !staticPlaceholder && samples && samples.length > 0;
  const { text, visible } = useRotatingPlaceholder(
    samples ?? [],
    !rotating || pauseRotation || focused || value.length > 0,
  );

  const sampleText = quoteSample ? `“${text}”` : text;
  const showOverlay = value.length === 0 && !focused;

  return (
    <div className="search-input-wrap">
      <input
        type="text"
        className="search-input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => {
          setFocused(true);
          onFocus?.();
        }}
        onBlur={() => {
          setFocused(false);
          onBlur?.();
        }}
        placeholder=""
        aria-label={ariaLabel}
        disabled={disabled}
      />
      {showOverlay && (
        <span className="search-placeholder" aria-hidden="true">
          {staticPlaceholder ? (
            staticPlaceholder
          ) : (
            <>
              {prefix}
              <span
                className={
                  rotating && !visible
                    ? "search-placeholder-sample is-fading"
                    : "search-placeholder-sample"
                }
              >
                {sampleText}
              </span>
            </>
          )}
        </span>
      )}
    </div>
  );
}
