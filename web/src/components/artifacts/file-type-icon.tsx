import { cn } from "@/lib/utils";

// Label colour per file kind, on a document glyph with the extension on it.
export function tone(mime: string): string {
  if (mime.includes("presentation")) return "#c2502f";
  if (mime === "text/csv" || mime.includes("spreadsheet")) return "#1e7a56";
  if (mime === "application/pdf") return "#b42318";
  if (mime === "text/html") return "#2a5c8a";
  if (mime.startsWith("image/")) return "#5b4bb0";
  if (mime.startsWith("text/")) return "#56646a";
  return "#8a9aa0";
}

export function extension(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot > 0 ? filename.slice(dot + 1).toUpperCase() : "FILE";
}

export function FileTypeIcon({
  label: text,
  color,
  large,
  className,
}: {
  label: string;
  color: string;
  large?: boolean;
  className?: string;
}) {
  const label = text.slice(0, 4);
  return (
    <svg
      aria-hidden
      viewBox="0 0 32 40"
      className={cn(
        "flex-none font-mono",
        large ? "h-11 w-9" : "h-9 w-[29px]",
        className,
      )}
    >
      <path
        d="M4 1.5h16.5L30.5 11.5V36a2.5 2.5 0 0 1-2.5 2.5H4A2.5 2.5 0 0 1 1.5 36V4A2.5 2.5 0 0 1 4 1.5z"
        fill="#fff"
        stroke="#dce4e4"
        strokeWidth="1.5"
      />
      <path
        d="M20.5 1.5v7.5a2.5 2.5 0 0 0 2.5 2.5h7.5"
        fill="#f1f5f5"
        stroke="#dce4e4"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <rect
        x="0"
        y="21"
        width={label.length > 3 ? 27 : 23}
        height="11"
        rx="2"
        fill={color}
      />
      {label && (
      <text
        x={label.length > 3 ? 13.5 : 11.5}
        y="29.2"
        textAnchor="middle"
        fontSize="7.2"
        fontWeight="600"
        fill="#fff"
      >
        {label}
      </text>
      )}
    </svg>
  );
}

/**
 * The artifact panel's file glyph at chip size (~20px), for any file by its
 * type: the colour band without the extension, which would be unreadable here
 * and is in the filename beside it anyway.
 */
export function FileIcon({
  mimeType,
  className,
}: {
  mimeType: string;
  className?: string;
}) {
  return (
    <FileTypeIcon
      label=""
      color={tone(mimeType)}
      className={className}
    />
  );
}
