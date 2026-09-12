import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // The API client is an implementation detail of `src/lib/api/**`. Pages,
  // components, hooks and stores talk to a resource module
  // (`@/lib/api/resources/<name>`) that owns the routes and response types, and
  // catch `ApiError` (`@/lib/api/errors`) rather than axios internals.
  //
  // `ignores` below is the migration allowlist — files that still import the
  // client directly. Each resource-module PR deletes its files from it; when
  // the list is empty, delete the `ignores` key.
  {
    files: ["src/**/*.{ts,tsx}"],
    ignores: [
      "src/lib/api/**",
      // --- allowlist: not yet migrated to a resource module ---
      "src/app/(protected)/agents/[[]id]/chat/components/connect-servers-dialog.tsx",
      "src/app/(protected)/agents/[[]id]/chat/components/mcp-app-widget.tsx",
      "src/app/(protected)/agents/[[]id]/chat/page.tsx",
      "src/app/(protected)/agents/[[]id]/components/add-agent-tool-dialog.test.tsx",
      "src/app/(protected)/agents/[[]id]/components/add-agent-tool-dialog.tsx",
      "src/app/(protected)/agents/[[]id]/components/agent-mcp-server.tsx",
      "src/app/(protected)/agents/[[]id]/components/agent-tool-list.test.tsx",
      "src/app/(protected)/agents/[[]id]/components/agent-tool-list.tsx",
      "src/app/(protected)/agents/[[]id]/page.tsx",
      "src/app/(protected)/agents/[[]id]/threads/page.tsx",
      "src/app/(protected)/agents/components/agent-editor.tsx",
      "src/app/(protected)/agents/components/agent-list.tsx",
      "src/app/(protected)/agents/components/agent-permissions-panel.tsx",
      "src/app/(protected)/agents/components/agent-tags-panel.tsx",
      "src/app/(protected)/agents/components/archived-agent-dialog.tsx",
      "src/app/(protected)/agents/components/new-tag-dialog.tsx",
      "src/app/(protected)/mcp-servers/[[]id]/page.tsx",
      "src/app/(protected)/mcp-servers/add/custom/page.test.tsx",
      "src/app/(protected)/mcp-servers/add/custom/page.tsx",
      "src/app/(protected)/mcp-servers/add/page.tsx",
      "src/app/(protected)/mcp-servers/components/connected-users-panel.tsx",
      "src/app/(protected)/mcp-servers/components/mcp-server-detail.tsx",
      "src/app/(protected)/mcp-servers/lib/use-connection-test.ts",
      "src/app/(protected)/mcp-servers/page.tsx",
      "src/app/(protected)/settings/create-token-dialog.tsx",
      "src/app/(protected)/settings/page.tsx",
      "src/app/(protected)/settings/sandbox-dialog.tsx",
      "src/app/(protected)/settings/workspace-models.tsx",
      "src/app/(protected)/settings/workspace-sandboxes.tsx",
      "src/app/(protected)/triggers/[[]id]/page.tsx",
      "src/app/(protected)/triggers/components/next-runs-card.tsx",
      "src/app/(protected)/users/invite-dialog.tsx",
      "src/app/(protected)/users/new-team-dialog.tsx",
      "src/app/(protected)/users/page.tsx",
      "src/app/auth/page.tsx",
      "src/app/invite/[[]token]/page.tsx",
      "src/app/setup/page.tsx",
      "src/hooks/use-agent-connection-status.ts",
      "src/hooks/use-delete-mcp-server.ts",
      "src/stores/agents-store.ts",
      "src/stores/mcp-servers-store.ts",
      "src/stores/models-store.ts",
      "src/stores/trigger-runs-store.ts",
      "src/stores/triggers-store.ts",
      "src/stores/user-store.ts",
    ],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "@/lib/api/client",
              message:
                "Use a resource module from @/lib/api/resources instead of the raw API client.",
            },
            {
              name: "axios",
              message:
                "Catch ApiError from @/lib/api/errors; components never see axios.",
            },
          ],
        },
      ],
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
