# Suite Workspace Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first shippable suite workspace: suite-aware sidebar navigation, a new light `/suite/[id]` home page, and separate pages for the current dashboard, connections, create/content, analytics, market, and profile.

**Architecture:** Extract the large suite dashboard file into reusable client components, then compose those components from focused route pages. Keep existing backend APIs unchanged. Preserve current dashboard behavior by moving it to `/suite/[id]/dashboard` before improving individual pages.

**Tech Stack:** Next.js App Router, React client components, TypeScript, Tailwind CSS, existing `api` client in `web/src/lib/api.ts`, lucide-react, recharts.

---

## File Map

- Create `web/src/app/(dashboard)/suite/[id]/layout.tsx`: suite-specific nested layout wrapper. Keeps child pages inside the existing account layout.
- Modify `web/src/app/(dashboard)/layout.tsx`: add suite section to the existing sidebar when route matches `/suite/[id]`.
- Create `web/src/components/suite/SuiteNav.tsx`: suite menu links and connection status dots.
- Create `web/src/components/suite/SuitePageShell.tsx`: common width/padding/page title wrapper.
- Create `web/src/components/suite/SuiteHeader.tsx`: current suite header extracted from old page.
- Create `web/src/components/suite/ConnectionsPanel.tsx`: extracted current connections panel.
- Create `web/src/components/suite/CreateCommandCenter.tsx`: extracted and adjusted create UI.
- Create `web/src/components/suite/RecentContent.tsx`: extracted content listing/generation workflow.
- Create `web/src/components/suite/PostCard.tsx`: extracted post card and media preview.
- Create `web/src/components/suite/AnalyticsPanel.tsx`: extracted analytics panel.
- Create `web/src/components/suite/CompetitorsSection.tsx`: extracted market research panel.
- Create `web/src/components/suite/CampaignsHub.tsx`: extracted campaigns section.
- Create `web/src/components/suite/StrategyPanel.tsx`: extracted strategy/profile display.
- Modify `web/src/app/(dashboard)/suite/[id]/page.tsx`: replace old mega dashboard with new lightweight home.
- Create `web/src/app/(dashboard)/suite/[id]/dashboard/page.tsx`: old dashboard composition.
- Create `web/src/app/(dashboard)/suite/[id]/connections/page.tsx`: standalone connections page.
- Create `web/src/app/(dashboard)/suite/[id]/create/page.tsx`: standalone create and recent content preview page.
- Create `web/src/app/(dashboard)/suite/[id]/content/page.tsx`: standalone recent content page.
- Create `web/src/app/(dashboard)/suite/[id]/analytics/page.tsx`: standalone analytics/campaign metrics page.
- Create `web/src/app/(dashboard)/suite/[id]/market/page.tsx`: standalone competitors and market page.
- Modify `web/src/app/(dashboard)/suite/[id]/profile/page.tsx`: keep current profile route, later expand in a separate plan.

## Task 1: Build Suite Navigation Foundation

**Files:**
- Modify: `web/src/app/(dashboard)/layout.tsx`
- Create: `web/src/components/suite/SuiteNav.tsx`
- Create: `web/src/components/suite/SuitePageShell.tsx`

- [ ] **Step 1: Add a suite route parser**

In `web/src/app/(dashboard)/layout.tsx`, derive the active suite id from the current pathname:

```tsx
const suiteMatch = pathname.match(/^\/suite\/([^/]+)/);
const activeSuiteId = suiteMatch?.[1] && suiteMatch[1] !== "new" ? suiteMatch[1] : null;
```

- [ ] **Step 2: Create `SuiteNav`**

Create `web/src/components/suite/SuiteNav.tsx` with a client component that:

```tsx
"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  CalendarDays,
  CircleGauge,
  GalleryHorizontalEnd,
  Globe2,
  LayoutDashboard,
  Link2,
  Megaphone,
  PackageOpen,
  PenTool,
  Sparkles,
  UserSquare2,
} from "lucide-react";
import { api, Connections, StorageStatus, Suite } from "@/lib/api";

type Props = {
  suiteId: string;
};

export function SuiteNav({ suiteId }: Props) {
  const pathname = usePathname();
  const [suite, setSuite] = useState<Suite | null>(null);
  const [connections, setConnections] = useState<Connections>({});
  const [storage, setStorage] = useState<StorageStatus | null>(null);

  useEffect(() => {
    api.suites.get(suiteId).then(setSuite).catch(() => setSuite(null));
    api.connections.get(suiteId).then(setConnections).catch(() => setConnections({}));
    api.suites.storageStatus(suiteId).then(setStorage).catch(() => setStorage(null));
  }, [suiteId]);

  const base = `/suite/${suiteId}`;
  const links = useMemo(() => [
    { href: base, label: "الرئيسية", icon: CircleGauge },
    { href: `${base}/dashboard`, label: "لوحة السوت", icon: LayoutDashboard },
    { href: `${base}/connections`, label: "Connections", icon: Link2, status: "connections" },
    { href: `${base}/create`, label: "Create & Generate", icon: Sparkles },
    { href: `${base}/content`, label: "المحتوى", icon: GalleryHorizontalEnd },
    { href: `${base}/analytics`, label: "معطيات وتحليل", icon: BarChart3 },
    { href: `${base}/profile`, label: "العلامة والبروفايل", icon: UserSquare2 },
    { href: `${base}/market`, label: "المنافسين والسوق", icon: Globe2 },
    { href: `${base}/calendar`, label: "Social Calendar", icon: CalendarDays },
    { href: `${base}/campaigns`, label: "Campaign Builder", icon: Megaphone },
    { href: `${base}/product-bulk`, label: "Product Bulk", icon: PackageOpen },
  ], [base]);

  const dots = {
    meta: Boolean(connections.facebook?.connected || connections.instagram?.connected),
    google: Boolean(connections.google_ads?.connected),
    storage: Boolean(storage?.configured),
  };

  return (
    <div className="mt-6 border-t border-border pt-4">
      <div className="px-3 pb-2">
        <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Current suite</p>
        <p className="mt-1 truncate text-sm font-semibold text-foreground" dir="auto">
          {suite?.name || "Suite"}
        </p>
      </div>
      <nav className="space-y-1">
        {links.map((item) => {
          const Icon = item.icon;
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors ${
                active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent hover:text-foreground"
              }`}
            >
              <Icon size={15} />
              <span className="min-w-0 flex-1 truncate">{item.label}</span>
              {item.status === "connections" && (
                <span className="flex items-center gap-1">
                  <span className={`h-1.5 w-1.5 rounded-full ${dots.meta ? "bg-emerald-400" : "bg-muted"}`} />
                  <span className={`h-1.5 w-1.5 rounded-full ${dots.google ? "bg-emerald-400" : "bg-muted"}`} />
                  <span className={`h-1.5 w-1.5 rounded-full ${dots.storage ? "bg-emerald-400" : "bg-muted"}`} />
                </span>
              )}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
```

- [ ] **Step 3: Render `SuiteNav` in desktop sidebar**

Import `SuiteNav` into `web/src/app/(dashboard)/layout.tsx` and render it after the account links:

```tsx
{activeSuiteId && <SuiteNav suiteId={activeSuiteId} />}
```

- [ ] **Step 4: Create `SuitePageShell`**

Create `web/src/components/suite/SuitePageShell.tsx`:

```tsx
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

export function SuitePageShell({
  title,
  description,
  backHref,
  children,
}: {
  title: string;
  description?: string;
  backHref?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-5 md:p-8">
      <header className="flex flex-col gap-2">
        {backHref && (
          <Link href={backHref} className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
            <ArrowLeft size={14} />
            Back
          </Link>
        )}
        <h1 className="text-2xl font-bold text-foreground">{title}</h1>
        {description && <p className="max-w-3xl text-sm text-muted-foreground">{description}</p>}
      </header>
      {children}
    </div>
  );
}
```

- [ ] **Step 5: Run build**

Run: `npm run build` from `web`.

Expected: build passes or fails only because route pages are not yet created. If route pages are not yet created, continue to Task 2 before fixing build.

## Task 2: Extract Existing Suite Sections

**Files:**
- Modify: `web/src/app/(dashboard)/suite/[id]/page.tsx`
- Create files under `web/src/components/suite/`

- [ ] **Step 1: Move shared media helper**

Create or keep these helpers inside the components that need them:

```tsx
const API_MEDIA = process.env.NEXT_PUBLIC_API_URL?.replace("/api/v1", "") || "http://localhost:8000";

function mediaUrl(url: string): string {
  if (/^https?:\/\//i.test(url)) return url;
  return `${API_MEDIA}${url}`;
}
```

- [ ] **Step 2: Extract components without behavior changes**

Move these functions from `web/src/app/(dashboard)/suite/[id]/page.tsx` into files with matching names:

```txt
ConnectionsPanel -> web/src/components/suite/ConnectionsPanel.tsx
CreateCommandCenter -> web/src/components/suite/CreateCommandCenter.tsx
ContentTab logic -> web/src/components/suite/RecentContent.tsx
PostCard -> web/src/components/suite/PostCard.tsx
AnalyticsTab -> web/src/components/suite/AnalyticsPanel.tsx
CompetitorsSection -> web/src/components/suite/CompetitorsSection.tsx
CampaignsHub -> web/src/components/suite/CampaignsHub.tsx
StrategyPanel -> web/src/components/suite/StrategyPanel.tsx
```

Each extracted component must start with `"use client";` if it uses hooks.

- [ ] **Step 3: Export stable component APIs**

Use these public props:

```tsx
export function ConnectionsPanel({ suiteId }: { suiteId: string }) {}
export function RecentContent({ suiteId, compact = false }: { suiteId: string; compact?: boolean }) {}
export function CreateCommandCenter({ suiteId, onGenerate, generating }: Props) {}
export function AnalyticsPanel({ suiteId }: { suiteId: string }) {}
export function CompetitorsSection({ suiteId, strategy }: { suiteId: string; strategy: MarketingStrategy | null }) {}
export function CampaignsHub({ suiteId }: { suiteId: string }) {}
export function StrategyPanel(props: StrategyPanelProps) {}
```

- [ ] **Step 4: Preserve old dashboard composition**

Create a temporary exported component:

```tsx
export function SuiteLegacyDashboard({ suiteId }: { suiteId: string }) {
  // load suite, then render header + all existing extracted sections in the same order as before
}
```

Place it in `web/src/components/suite/SuiteLegacyDashboard.tsx`.

- [ ] **Step 5: Run build**

Run: `npm run build` from `web`.

Expected: TypeScript catches missing imports. Fix imports until build passes.

## Task 3: Create New Route Pages

**Files:**
- Modify: `web/src/app/(dashboard)/suite/[id]/page.tsx`
- Create: `web/src/app/(dashboard)/suite/[id]/dashboard/page.tsx`
- Create: `web/src/app/(dashboard)/suite/[id]/connections/page.tsx`
- Create: `web/src/app/(dashboard)/suite/[id]/create/page.tsx`
- Create: `web/src/app/(dashboard)/suite/[id]/content/page.tsx`
- Create: `web/src/app/(dashboard)/suite/[id]/analytics/page.tsx`
- Create: `web/src/app/(dashboard)/suite/[id]/market/page.tsx`

- [ ] **Step 1: Replace `/suite/[id]` with new home**

`web/src/app/(dashboard)/suite/[id]/page.tsx` should load the suite and render:

```tsx
"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { api, Suite } from "@/lib/api";
import { SuitePageShell } from "@/components/suite/SuitePageShell";
import { RecentContent } from "@/components/suite/RecentContent";
import { ConnectionsPanel } from "@/components/suite/ConnectionsPanel";

export default function SuiteHomePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [suite, setSuite] = useState<Suite | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.suites.get(id).then(setSuite).finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div className="p-8 text-muted-foreground">Loading...</div>;
  if (!suite) return <div className="p-8 text-red-400">Suite not found</div>;

  return (
    <SuitePageShell
      title={suite.name}
      description="Your suite command center. Start with creation, check health, then jump into deeper tools only when needed."
    >
      <div className="grid gap-4 md:grid-cols-3">
        <Link href={`/suite/${id}/create`} className="rounded-xl border border-border bg-card p-4 hover:bg-accent">
          <p className="text-sm font-semibold text-foreground">Create & Generate</p>
          <p className="mt-1 text-xs text-muted-foreground">Create posts, ads, sets, images, videos, and carousels.</p>
        </Link>
        <Link href={`/suite/${id}/analytics`} className="rounded-xl border border-border bg-card p-4 hover:bg-accent">
          <p className="text-sm font-semibold text-foreground">Analytics</p>
          <p className="mt-1 text-xs text-muted-foreground">Review page and campaign performance.</p>
        </Link>
        <Link href={`/suite/${id}/profile`} className="rounded-xl border border-border bg-card p-4 hover:bg-accent">
          <p className="text-sm font-semibold text-foreground">Brand/Profile</p>
          <p className="mt-1 text-xs text-muted-foreground">Edit the business memory that powers generation.</p>
        </Link>
      </div>
      <ConnectionsPanel suiteId={id} />
      <RecentContent suiteId={id} compact />
    </SuitePageShell>
  );
}
```

- [ ] **Step 2: Add legacy dashboard page**

Create `web/src/app/(dashboard)/suite/[id]/dashboard/page.tsx`:

```tsx
"use client";

import { use } from "react";
import { SuiteLegacyDashboard } from "@/components/suite/SuiteLegacyDashboard";

export default function SuiteDashboardRoute({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <SuiteLegacyDashboard suiteId={id} />;
}
```

- [ ] **Step 3: Add connections page**

Create `web/src/app/(dashboard)/suite/[id]/connections/page.tsx`:

```tsx
"use client";

import { use } from "react";
import { ConnectionsPanel } from "@/components/suite/ConnectionsPanel";
import { SuitePageShell } from "@/components/suite/SuitePageShell";

export default function ConnectionsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <SuitePageShell title="Connections" description="Connect publishing, analytics, campaign, and media storage providers.">
      <ConnectionsPanel suiteId={id} />
    </SuitePageShell>
  );
}
```

- [ ] **Step 4: Add create page**

Create `web/src/app/(dashboard)/suite/[id]/create/page.tsx` using `CreateCommandCenter` and `RecentContent`. If `CreateCommandCenter` depends on generation callbacks from `RecentContent`, expose a wrapper component `CreateWorkspace` from `RecentContent.tsx` that owns generation state.

- [ ] **Step 5: Add content page**

Create `web/src/app/(dashboard)/suite/[id]/content/page.tsx`:

```tsx
"use client";

import { use } from "react";
import { RecentContent } from "@/components/suite/RecentContent";
import { SuitePageShell } from "@/components/suite/SuitePageShell";

export default function ContentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <SuitePageShell title="Content" description="Review generated content from newest to oldest.">
      <RecentContent suiteId={id} />
    </SuitePageShell>
  );
}
```

- [ ] **Step 6: Add analytics page**

Create `web/src/app/(dashboard)/suite/[id]/analytics/page.tsx` with `AnalyticsPanel` and `CampaignsHub`.

- [ ] **Step 7: Add market page**

Create `web/src/app/(dashboard)/suite/[id]/market/page.tsx` loading `suite.strategy` and rendering `CompetitorsSection`.

- [ ] **Step 8: Run build**

Run: `npm run build` from `web`.

Expected: all route pages compile.

## Task 4: Improve Create and Content Filters

**Files:**
- Modify: `web/src/components/suite/CreateCommandCenter.tsx`
- Modify: `web/src/components/suite/RecentContent.tsx`

- [ ] **Step 1: Update create modes**

Change create modes to:

```tsx
type CreateMode =
  | "quick"
  | "anything"
  | "campaign"
  | "product_bulk"
  | "set"
  | "image"
  | "video"
  | "carousel";
```

Display titles:

```tsx
[
  ["quick", "Quick Post/Ad"],
  ["anything", "Create anything"],
  ["campaign", "Campaign Builder"],
  ["product_bulk", "Product Bulk Studio"],
  ["set", "Content Set"],
  ["image", "Create Image"],
  ["video", "Create Video"],
  ["carousel", "Carousel"],
]
```

- [ ] **Step 2: Make prompt larger**

Set textarea to:

```tsx
rows={6}
className="min-h-40 ..."
```

- [ ] **Step 3: Use default quick mode**

Initialize mode:

```tsx
const [mode, setMode] = useState<CreateMode>("quick");
```

- [ ] **Step 4: Route product bulk**

When mode is `product_bulk`, navigate to:

```tsx
window.location.href = `/suite/${suiteId}/product-bulk`;
```

- [ ] **Step 5: Add content type filter**

In `RecentContent`, add:

```tsx
const [typeFilter, setTypeFilter] = useState<"all" | "post" | "image" | "video" | "carousel" | "set" | "bulk" | "campaign">("all");
```

Filter client-side:

```tsx
const typeMatches = (post: Post) => {
  if (typeFilter === "all") return true;
  if (typeFilter === "set") return post.generation_mode === "set";
  if (typeFilter === "bulk") return post.generation_mode === "product_bulk";
  if (typeFilter === "campaign") return post.generation_mode === "campaign";
  return post.format === typeFilter || post.content_type === typeFilter;
};
```

- [ ] **Step 6: Keep newest-first order**

Sort before rendering:

```tsx
const visibleSource = [...posts]
  .filter((p) => p.status === filter)
  .filter(typeMatches)
  .sort((a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime());
```

- [ ] **Step 7: Run build**

Run: `npm run build` from `web`.

Expected: build passes. If `Post` lacks `generation_mode`, `format`, `content_type`, or `created_at`, add optional fields to the `Post` interface in `web/src/lib/api.ts`.

## Task 5: Verify Navigation and Existing Flows

**Files:**
- No new files unless fixing build or runtime regressions.

- [ ] **Step 1: Run production build**

Run: `npm run build` from `web`.

Expected: `Compiled successfully`.

- [ ] **Step 2: Start local web if needed**

Run: `npm run dev -- --port 3001` from `web` if no dev server is active.

Expected: app serves on `http://localhost:3001`.

- [ ] **Step 3: Browser QA**

Open the app and verify:

```txt
/suites
/suite/<id>
/suite/<id>/dashboard
/suite/<id>/connections
/suite/<id>/create
/suite/<id>/content
/suite/<id>/analytics
/suite/<id>/market
/suite/<id>/product-bulk
```

Expected:

- Sidebar shows account links and suite links only inside a suite.
- Connection dots render.
- Old dashboard still appears on `/dashboard`.
- Create page can trigger generation.
- Content page can approve/reject/regenerate existing posts.
- Product bulk route still opens.

- [ ] **Step 4: Commit**

Commit only files touched by this plan:

```bash
git add web/src/app web/src/components/suite web/src/lib/api.ts
git commit -m "feat: add suite workspace navigation"
```

## Scope Gaps Intentionally Deferred

These are part of the approved product direction, but should be separate implementation plans after the workspace split is stable:

- Full editable profile/strategy sections with AI regenerate per block.
- Deep Social Calendar Builder flow.
- Deep Sponsored Campaign Builder flow.
- Meta Ads interest/behavior/demographic matching UI.
- Google Ads keyword/audience suggestion UI.
