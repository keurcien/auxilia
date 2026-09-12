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
  {
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/lib/api/**"],
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
