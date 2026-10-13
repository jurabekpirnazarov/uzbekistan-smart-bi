import { expect, test } from "@playwright/test";

const SHOTS = "../docs/screenshots";

test("home loads with KPIs and the map preview", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Where should your next business open?" })).toBeVisible();
  await expect(page.locator(".kpi").first()).toContainText("Population");
  await expect(page.locator(".hero-map canvas")).toBeVisible();
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${SHOTS}/home.png` });
});

test("recommend form returns ranked results with a breakdown", async ({ page }) => {
  await page.goto("/recommend?business_type=bakery&region=1730");
  await expect(page.locator(".reco-card")).toHaveCount(15);
  await expect(page.locator(".reco-card").first()).toContainText("Fergana city");
  await expect(page.locator(".breakdown table")).toBeVisible();
  await expect(page.getByText("decision support, not a guarantee").first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/recommend.png`, fullPage: true });
});

test("map renders regions and the legend", async ({ page }) => {
  await page.goto("/map");
  await expect(page.locator(".map canvas")).toBeVisible();
  await expect(page.locator(".legend")).toContainText("colour/height = rank");
  await expect(page.locator(".side-panel")).toContainText("14 territories");
  await page.waitForTimeout(3000);
  await page.screenshot({ path: `${SHOTS}/map.png` });
});

test("forecast and monitoring pages render", async ({ page }) => {
  await page.goto("/forecast?indicator=population_total&level=region&soato=1718");
  await expect(page.getByText("Selected model")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/forecast.png` });
  await page.goto("/monitoring");
  await expect(page.getByRole("heading", { name: "Data health" })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/monitoring.png`, fullPage: true });
});

test("chat streams a verified reply and focuses the map", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Ask the AI analyst").fill("Where should I open a pharmacy in Samarkand region?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.locator(".tool-chip").first()).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".msg-foot")).toBeVisible({ timeout: 90_000 });
  await expect(page.locator(".verify")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/chat.png` });
  await page.getByRole("button", { name: "Show on map" }).click();
  await expect(page).toHaveURL(/\/map\?level=district&focus=/);
});
