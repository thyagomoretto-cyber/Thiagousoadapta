import { useState } from "react";
import { Archive, Pin, PinOff, Trash2 } from "lucide-react";

import { useAgentChatStore } from "@/store/agentChat";
import { useT, useUiLanguage } from "@/i18n";
import { cn } from "@/lib/utils";
import { AllChatsDialog } from "@/components/home/AllChatsDialog";
import { ChatKindMark } from "@/components/home/ChatKindMark";
import { chatRowLabel, formatChatDay, groupChatRowsByDay, useChatRows, type ChatRow } from "@/components/home/chatRows";
import { useHistoryPolling } from "@/hooks/useHistoryPolling";


/** Sidebar history: pinned conversations first, then the chats under one heading per day. */
const PINNED_KEY = "jarvis.sidebar.pinned-chats.v1";
const VISIBLE_CHAT_ROWS = 4;
function readPins(): string[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(PINNED_KEY) ?? "[]");
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
  } catch {
    // Unavailable or invalid storage leaves the history usable without pins.
    return [];
  }
}
const rowKey = (row: ChatRow) => `${row.kind}:${row.id}`;
export function RecentChats() {
  const t = useT();
  const lang = useUiLanguage();
  const { rows, isActive, open: openRow, remove } = useChatRows({ poll: true });
  const loadSessions = useAgentChatStore((s) => s.loadSessions);
  const [pins, setPins] = useState(readPins);
  const [archiveOpen, setArchiveOpen] = useState(false);

  const togglePin = (row: ChatRow) => {
    const key = rowKey(row);
    const next = pins.includes(key)
      ? pins.filter((id) => id !== key)
      : [...pins, key];

    setPins(next);

    try {
      localStorage.setItem(PINNED_KEY, JSON.stringify(next));
    } catch {}
  };

  useHistoryPolling(loadSessions);

  const unpinnedRows = rows.filter((row) => !pins.includes(rowKey(row)));
  const days = groupChatRowsByDay(unpinnedRows);

  const today = days.find((day) => day.relative === "today");
  const visibleToday = (today?.rows ?? []).slice(0, VISIBLE_CHAT_ROWS);

  return (
    <>
      <div data-testid="recent-chats" className="pb-1 pt-0.5">
        <section className="mb-1">
          <h2 className="px-3 pb-1.5 text-sm text-muted-foreground">
            {today
              ? today.relative
                ? t(`all_chats.group_${today.relative}`)
                : formatChatDay(today.dayMs, lang)
              : "Hoje"}
          </h2>

          {visibleToday.length > 0 ? (
            <ul className="space-y-0.5">
              {visibleToday.map((row) => (
                <ChatRowItem
                  key={`${row.kind}-${row.id}`}
                  row={row}
                  active={isActive(row)}
                  pinned={pins.includes(rowKey(row))}
                  onPin={() => togglePin(row)}
                  onOpen={() => openRow(row)}
                  onDelete={
                    row.kind === "agent" ? () => remove(row) : undefined
                  }
                />
              ))}
            </ul>
          ) : (
            <p className="px-3 py-1 text-sm text-foreground-faint">
              {t("sidebar.no_chats")}
            </p>
          )}
        </section>

        {rows.length > 0 && (
          <button
            type="button"
            onClick={() => setArchiveOpen(true)}
            data-testid="see-all-chats"
            className={TAIL_ROW}
          >
            <Archive aria-hidden className="h-3.5 w-3.5 shrink-0" />
            <span className="min-w-0 flex-1 truncate text-sm">
              Conversas antigas
            </span>
          </button>
        )}
      </div>

      <AllChatsDialog
        open={archiveOpen}
        onOpenChange={setArchiveOpen}
      />
    </>
  );
}


/** "See all chats": the quiet row that closes the list. */
const TAIL_ROW = cn(
  "flex h-8 w-full items-center gap-3 rounded-lg px-3 text-left transition-colors",
  "text-muted-foreground hover:bg-secondary hover:text-foreground",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
);

/** One line of the title. The row truncates it to the sidebar's real width. */
export function compactChatTitle(title: string): string {
  return title.trim().replace(/\s+/g, " ");
}

function ChatRowItem({
  row,
  active,
  onOpen,
  onDelete,
  pinned = false,
  onPin,
}: {
  row: ChatRow;
  active: boolean;
  onOpen: () => void;
  onDelete?: () => void;
  pinned?: boolean;
  onPin: () => void;
}) {
  const t = useT();
  const label = chatRowLabel(row, t);
  const title = label.text;
  return (
    <li className="group relative">
      <button
        type="button"
        onClick={onOpen}
        title={title}
        aria-label={row.kind === "voice" && !label.untitled ? `${t("all_chats.filter_voice")}: ${title}` : title}
        data-testid="recent-chat-row"
        data-kind={row.kind}
        className={cn(
          "flex h-8 w-full items-center gap-2.5 rounded-lg px-3 text-left transition-colors group-hover:pr-16 group-focus-within:pr-16",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          // The open one wears the same accent edge as the active nav row, so
          // "where am I" is said in one voice all the way down the column.
          active ? "jarvis-nav-active bg-secondary text-foreground-strong" : "text-foreground hover:bg-secondary",
        )}
      >
        {/* One small mark says which kind of chat this is — a ring for typed,
            sound bars for voice — in one box and one muted tone, the way the
            Claude app tells its chat and code sessions apart. A chat with no
            topic says what it was ("Voice chat · 09:42"), in a quieter tone. */}
        <ChatKindMark kind={row.kind} active={active} />
        <span
          className={cn(
            "min-w-0 flex-1 truncate text-base leading-5",
            label.untitled && !active && "text-muted-foreground",
          )}
        >
          {compactChatTitle(title)}
        </span>

      </button>
      <button type="button" onClick={onPin} title={t(pinned ? "sidebar.unpin_chat" : "sidebar.pin_chat")}
        aria-label={`${t(pinned ? "sidebar.unpin_chat" : "sidebar.pin_chat")}: ${title}`}
        className="absolute right-7 top-1/2 -translate-y-1/2 rounded-md bg-card p-1.5 text-muted-foreground opacity-0 hover:text-foreground focus:opacity-100 group-hover:opacity-100 group-focus-within:opacity-100">
        {pinned ? <PinOff className="h-3.5 w-3.5" /> : <Pin className="h-3.5 w-3.5" />}
      </button>
      {onDelete && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          title={t("chats_view.delete")}
          aria-label={t("chats_view.delete")}
          className="absolute right-1 top-1/2 -translate-y-1/2 opacity-0 rounded-md bg-card p-1 text-muted-foreground transition-colors hover:bg-destructive/15 hover:text-destructive focus:opacity-100 group-hover:opacity-100 group-focus-within:opacity-100"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      )}
    </li>
  );
}
