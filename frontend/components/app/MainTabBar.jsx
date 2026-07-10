"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useConfig } from '@/hooks/ConfigContext';
import { useFeatures } from '@/hooks/FeaturesContext';

export default function MainTabBar() {
  const pathname = usePathname();

const { config, loading, userConfig, userLoading } = useConfig();
const { adminConfig, adminLoading } = useFeatures();

const instanceFlags = {};
const mm = adminConfig?.mm_features || {};
for (const key in mm) {
  const val = mm[key];           // already the boolean
  if (typeof val === "boolean") {
    instanceFlags[key] = val;
  }
}

// muse/user flags (from userConfig)
const museFlags = {};
const muse = userConfig?.muse_features || {};
for (const key in muse) {
  const val = muse[key];
  if (typeof val === "boolean") {
    museFlags[key] = val;
  }
}


if (loading || adminLoading || userLoading ) return null; // or a spinner, or a skeleton bar

const allTabs = [
  { name: "Chat", path: "/chat" },
  { name: "Projects", path: "/projects", },
  { name: "Files", path: "/files" },
  { name: "Journal", path: "/journal", muse_feature: "ENABLE_JOURNAL"  },
  { name: "Memory", path: "/memory" },
  //{ name: "Muse", path: "/muse" },
  { name: "Games", path: "/games", feature: "ENABLE_GAMES" },
  { name: "Sync", path: "/sync", feature: "ENABLE_SYNC"  },
  { name: "AdminConfig", path: "/admin_config", feature: "ENABLE_ADMIN" },
];

// Now filter tabs using the flat object:
const visibleTabs = allTabs.filter(tab => {
  // no flags at all → always visible
  if (!tab.feature && !tab.muse_feature) return true;

  // instance-level feature, if present
  if (tab.feature && !instanceFlags[tab.feature]) return false;

  // muse/user-level feature, if present
  if (tab.muse_feature && !museFlags[tab.muse_feature]) return false;

  return true;
});

  return (
    <div className="border-b border-neutral-800 p-4 flex justify-between items-center sticky top-0 z-10 bg-neutral-950">
      <div className="flex items-center">
        <img src="/memorymuse-logo.png" alt="MemoryMuse Logo" className="h-15 w-20 mr-3" />
        <span className="text-2xl font-black tracking-wide text-purple-200 drop-shadow">
          Memory<span className="text-purple-400">Muse</span>
        </span>
      </div>
        <div className="space-x-3 text-sm">
          {visibleTabs.map((tab) => (
            <Link href={tab.path} key={tab.name}>
              <button
                className={`px-3 py-1 rounded ${
                  pathname.startsWith(tab.path) ? "bg-purple-700" : "hover:bg-neutral-800"
                }`}
              >
                {tab.name}
              </button>
            </Link>
          ))}
        </div>
    </div>
  );
}
