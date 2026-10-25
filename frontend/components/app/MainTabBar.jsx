"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useConfig } from "@/hooks/ConfigContext";
import { useFeatures } from "@/hooks/FeaturesContext";
import { JOURNAL_VIEW_STATE_CHANGED } from "@/utils/journalUiEvents";

export default function MainTabBar() {
  const pathname = usePathname();

  const {
    userConfig,
    userLoading,
    adminConfig,
    adminLoading,
    museProfile,
    museProfileLoading,
  } = useConfig();

  const { adminConfig: featureAdminConfig, adminLoading: featureAdminLoading } =
    useFeatures();

  const [unviewedJournalCount, setUnviewedJournalCount] = useState(0);

  const refreshJournalBadge = useCallback(async () => {
    try {
      const res = await fetch("/api/journals/unviewed-count");

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const data = await res.json();
      setUnviewedJournalCount(Number(data.count) || 0);
    } catch (error) {
      // A missing badge is preferable to making navigation noisy or broken.
      console.warn("Failed to refresh Journal unread count:", error);
    }
  }, []);

  useEffect(() => {
    refreshJournalBadge();

    const intervalId = window.setInterval(refreshJournalBadge, 60_000);

    const handleJournalViewStateChanged = () => {
      refreshJournalBadge();
    };

    const handleWindowFocus = () => {
      refreshJournalBadge();
    };

    window.addEventListener(
      JOURNAL_VIEW_STATE_CHANGED,
      handleJournalViewStateChanged
    );
    window.addEventListener("focus", handleWindowFocus);

    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener(
        JOURNAL_VIEW_STATE_CHANGED,
        handleJournalViewStateChanged
      );
      window.removeEventListener("focus", handleWindowFocus);
    };
  }, [refreshJournalBadge]);

  const instanceFlags = {};
  const mm = featureAdminConfig?.mm_features || {};

  for (const key in mm) {
    const val = mm[key];
    if (typeof val === "boolean") {
      instanceFlags[key] = val;
    }
  }

  const museFlags = {};
  const muse = userConfig?.muse_features || {};

  for (const key in muse) {
    const val = muse[key];
    if (typeof val === "boolean") {
      museFlags[key] = val;
    }
  }

  const museName =
    museProfile?.name?.[0]?.content ||
    museProfile?.name ||
    museProfile?.profile?.name ||
    userConfig?.muse_name ||
    "Muse";

  if (
    userLoading ||
    adminLoading ||
    featureAdminLoading ||
    museProfileLoading
  ) {
    return null;
  }

  const allTabs = [
    { name: "Chat", path: "/chat" },
    { name: "Projects", path: "/projects" },
    { name: "Files", path: "/files" },
    {
      name: `${museName}'s Journal`,
      path: "/journal",
      muse_feature: "ENABLE_JOURNAL",
      badgeCount: unviewedJournalCount,
    },
    { name: "Memory", path: "/memory" },
    { name: "Games", path: "/games", feature: "ENABLE_GAMES" },
    { name: "Sync", path: "/sync", feature: "ENABLE_SYNC" },
    { name: "AdminConfig", path: "/admin_config", feature: "ENABLE_ADMIN" },
  ];

  const visibleTabs = allTabs.filter((tab) => {
    if (!tab.feature && !tab.muse_feature) return true;

    if (tab.feature && !instanceFlags[tab.feature]) return false;
    if (tab.muse_feature && !museFlags[tab.muse_feature]) return false;

    return true;
  });

  return (
    <div className="sticky top-0 z-10 flex items-center justify-between border-b border-neutral-800 bg-neutral-950 p-4">
      <div className="flex items-center">
        <img
          src="/memorymuse-logo.png"
          alt="MemoryMuse Logo"
          className="mr-3 h-15 w-20"
        />
        <span className="text-2xl font-black tracking-wide text-purple-200 drop-shadow">
          Memory<span className="text-purple-400">Muse</span>
        </span>
      </div>

      <div className="space-x-3 text-sm">
        {visibleTabs.map((tab) => (
          <Link href={tab.path} key={tab.name}>
            <button
              className={`inline-flex items-center gap-2 rounded px-3 py-1 ${
                pathname.startsWith(tab.path)
                  ? "bg-purple-700"
                  : "hover:bg-neutral-800"
              }`}
            >
              <span>{tab.name}</span>

              {tab.badgeCount > 0 && (
                <span
                  className="inline-flex min-w-5 items-center justify-center rounded-full bg-violet-200 px-1.5 py-0.5 text-[11px] font-bold text-violet-950"
                  title={`${tab.badgeCount} unviewed journal entr${
                    tab.badgeCount === 1 ? "y" : "ies"
                  }`}
                >
                  {tab.badgeCount > 99 ? "99+" : tab.badgeCount}
                </span>
              )}
            </button>
          </Link>
        ))}
      </div>
    </div>
  );
}