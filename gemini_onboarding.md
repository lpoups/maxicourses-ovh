# Gemini Onboarding: Maxicourses Project Status (December 2025)

**This document serves as the "State of the Union" for the next Gemini agent picking up the project.**

---

## 1. Core Architecture Shift: OVH Centric
> [!IMPORTANT]
> **MAXICOURSES IS NOW 100% OVH-CENTRIC.**
> There is **no local development** logic anymore. The local machine (`/Users/laurentpoupet/Sites/maxicourses-ovh`) is strictly used as a **staging area** to edit files and push them to the OVH server via `deploy_ovh.sh`.

*   **Production Codebase**: Located on OVH server (`vps-222a760c.vps.ovh.net`).
*   **Local Codebase**: Mirror of production. **Do not run `run_pipeline.py` locally for actual collection.** It is only for code editing.
*   **Deployment**: The user runs a script (e.g., `./deploy_ovh.sh`) to sync local changes to remote. You should ask the user to deploy after making changes.

---

## 2. Remote Collection & SSH Tunnel Visualization
The user's favorite feature is "Real Time Visualization". This allows them to verify what the bot is doing on the remote server by seeing it inside their **local** Chrome browser.

**How it works (The Workflow):**
1.  **Remote Execution**: The Python scripts (`run_pipeline.py`, `fetch_auchan_price.py`) run on the OVH VPS.
2.  **SSH Tunnel**: The user establishes a Reverse SSH Tunnel: `Remote:9223 -> Local:9223`.
3.  **Local Browser**: The user launches Chrome locally with remote debugging enabled on port 9223.
    *   Command: `/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9223`
4.  **Connection**: The Remote Python script connects to `http://127.0.0.1:9223` (on Remote), which tunnels to `http://127.0.0.1:9223` (on Local).
5.  **Result**: The Python script controls the **User's Local Browser**, allowing them to watch the scraper working "live" from the server's perspective.

**Key Configuration:**
*   `run_pipeline.py` is patched to force `CDP_URL="http://127.0.0.1:9223"`.
*   Scripts use `USING_CDP=1`.

---

## 3. Session Summary (Dec 7, 2025)
This session focused on restoring stability and fixing data quality for Auchan and Carrefour.

### A. Auchan Fixes (Regression Resolved)
*   **Issue**: Failed to select "Drive" store despite button being visible.
*   **Root Cause**: Anti-bot detection (Playwright Stealth + unnatural mouse movement) and `localStorage` injection conflicts.
*   **Solution**:
    *   Removed `playwright-stealth` (Clean CDP connection).
    *   Implemented **Randomized Human Click** (non-centered clicks with jitter).
    *   Restored robust cookie handling patches.

### B. Carrefour Fixes (Data Quality & Speed)
*   **Issue**: Quantity extraction was flaky (regex on text returned "100 ML" instead of "6x33cL") and Unit Price was often missing.
*   **Solution**: Moved from DOM Scraping to **JSON State Parsing**.
    *   The script now reads `window.__INITIAL_STATE__` from the Search Results HTML.
    *   Extracts highly accurate data (Quantity, Price, Unit Price) directly from the internal JSON.
    *   **Optimization**: Bypasses the Product Detail Page (PDP) entirely if JSON data is found (Significant speedup).
*   **File Hierarchy**: `fetch_carrefour_price.py` is the **Core Script**. Scripts like `fetch_carrefour_price_city.py` are just wrappers. **Always edit the Core Script.**

---

## 4. File Inventory & Changes
These files were created or heavily modified during this session and are critical to the current stability.

| File Path | Purpose | Status |
| :--- | :--- | :--- |
| `www/maxicourses_test/fetch_carrefour_price.py` | **CORE**. Main Carrefour logic. Updated with JSON parsing. | **PROD READY** |
| `www/maxicourses_test/fetch_auchan_price.py` | **CORE**. Main Auchan logic. Robust "Human Click" implemented. | **PROD READY** |
| `www/maxicourses_test/pipeline/run_pipeline.py` | **PIPELINE**. Updates environment vars and CDP port for tunneling. | **PROD READY** |
| `www/docs/collecte_auchan.md` | **DOCS**. SOP for Auchan collection validation. | **NEW** |
| `www/docs/walkthrough.md` | **DOCS**. Detailed history of all fixes. | **UPDATED** |

---

## 5. Next Steps for Gemini
If you are picking up this project:
1.  **Respect the Tunnel**: Always ensure `CDP_URL` defaults to port 9223 (or adheres to the tunnel config) when debugging "Remote" issues.
2.  **Trust `fetch_carrefour_price.py`**: It handles all store types (City, Market, Super). Don't get confused by the wrapper files.
3.  **Deploy First**: If the user asks to "Run a test", remember valid tests happen on OVH. Push changes first!

*Good luck, future code companion.*
