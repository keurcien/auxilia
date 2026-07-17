import { expect, test } from "@playwright/test";
import path from "node:path";

const logoPath = path.join(process.cwd(), "public", "logo.svg");

test("auth page matches the sign-in visual baseline", async ({ page }) => {
	await page.emulateMedia({ colorScheme: "light" });

	await page.route("**/api/backend/auth/providers", async (route) => {
		await route.fulfill({
			status: 200,
			contentType: "application/json",
			body: JSON.stringify({
				password: true,
				google: false,
				setup_required: false,
			}),
		});
	});

	await page.route("**/_next/image**", async (route) => {
		await route.fulfill({
			status: 200,
			contentType: "image/svg+xml",
			path: logoPath,
		});
	});

	await page.route(
		"https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons/**",
		async (route) => {
			await route.fulfill({
				status: 200,
				contentType: "image/svg+xml",
				path: logoPath,
			});
		},
	);

	await page.goto("/auth");

	await expect(page.getByText("auxilia", { exact: true })).toBeVisible();
	await expect(page.getByLabel("Email")).toBeVisible();
	await expect(page.getByLabel("Password")).toBeVisible();
	await expect(page.getByRole("button", { name: "Sign In" })).toBeVisible();

	await expect(page).toHaveScreenshot("auth-page.png");
});
