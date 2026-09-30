# LAN Observer 0.2.0 visual audit

Audited 2026-09-22 against the current local working tree. The populated app was served from `scripts/demo.py` with synthetic documentation-range data; a separate empty app-data folder supplied the first-run view. No actual LAN inventory was displayed or scanned.

**Resolution, 2026-09-22:** V01–V08 were addressed in the working tree. The findings below remain as the original visual evidence; the verification after the changes is recorded under **Fix verification**.

I inspected Inventory, History, Settings, scan detail, and device detail in the Codex in-app browser at 320, 390, 768, and 1280 CSS pixels. All 20 page/width combinations had `documentElement.scrollWidth <= clientWidth`; no page-wide horizontal overflow appeared. The long synthetic hostname wrapped in the inventory. Browser warnings/errors were empty. Keyboard Tab exposed a visible Skip to content link. The restrained dark palette, consistent cards, and evidence badges provide a clear visual foundation. The current desktop inventory image is [here](screenshots/inventory-v0.2.png).

## Findings

| ID | Priority | Confirmed observation | Recommended change |
| --- | --- | --- | --- |
| V01 | P2 | On first run at 320×800, the only useful action, **Set up a network**, begins at y=798. The disabled scan form occupies 130 px above it, so the primary action is below the initial viewport. | Hide the scan form until a network exists; place setup/import actions first. Defer zero-value metrics, archive, and filters until an inventory exists. |
| V02 | P2 | Inventory filter selections are visibly clipped at 320 and 390 px; examples include “All saved netw…”, “Active invento…”, and “All manufactur…”. Network selection also clips at 768 px. The underlying options remain accessible when opened, but the current selection cannot be read at a glance. | Stack selects at narrow widths, or give each field enough width for its chosen value. Retest common long network/manufacturer names. |
| V03 | P2 | The scan detail **Changes in this scan** list shows three visually identical “First observed · A new identity was recorded … Device details” entries in the demo. The user must open each link to learn which device changed. | Put the device name or address and the change itself in each row; retain the detail link as a secondary action. |
| V04 | P2 | Clicking **Copy** on a MAC updates only the screen-reader announcement. The visible button remains “Copy”, with no visible toast or status. The target is 47×32 px at 320 px width. | Show “Copied” or an inline visible status while keeping the live announcement; increase the target to roughly the size of other controls. |
| V05 | P2 | **Recent responses** is 2 in the demo, but one item is **This computer**, not an ICMP response. The metric's label and the “Recent responses” filter therefore overstate what was measured. | Label the combined count “Recently confirmed” or count only actual responses and show local presence separately. |
| V06 | P2 | A saved demo network and populated inventory are present, yet **Network to scan** remains “Choose a network”. Pressing Scan requires another selection despite there being only one configured scope. | Preselect the sole configured network; with multiple networks, preserve an explicit last-used choice or require deliberate selection. |
| V07 | P3 | Some detail/history copy exposes implementation terms: `local`, `cache`, `response` in scan evidence and `nickname`, `known`, `reviewed` in the device edit timeline. “Make it recognizable” also remains the heading for a recognized device. | Use the same plain-language evidence labels throughout; translate edit events into user-facing field names and use a neutral form heading. |
| V08 | P3 | At 768 px the four summary cards remain in one row with explanatory text wrapping into multiple short lines. Secondary type is very small in places: the LOCAL tag is 9 px, eyebrow text about 11 px, and the MAC Copy button about 12 px. | Switch summary cards to two columns around tablet width and raise the smallest nonessential text sizes where space allows. |

## Fix verification

- **V01:** First-run screens now hide the disabled scan form, zero metrics, and empty inventory controls. At 320×800, the setup button begins at y=658 and is visible without scrolling.
- **V02:** Filters stack into one column on narrow screens, use two readable columns at tablet widths, and use allocated grid widths on desktop. The full selected labels were visible at 320, 390, 768, and 1280 px; the scan chooser also shows the complete selected network and range below the control.
- **V03:** Scan changes show the device name/hostname/address next to the kind and detail. The three demo first-observed entries are now distinguishable.
- **V04:** Copy shows a visible “Copied” status that is also announced via `role=status`; the button is 44 px high. A failed copy shows a visible fallback instruction.
- **V05–V06:** The combined response/local metric and filter now say “Recently confirmed.” The sole configured network is preselected, while multiple networks still require an explicit choice unless a selected inventory network matches. The complete network name and CIDR are displayed beside the action.
- **V07–V08:** Evidence labels are consistent across inventory, scan, and device views. New and historical edit events render friendly field names; the editor heading is neutral. Tablet metrics use two columns, and the smallest metadata text and Copy target have been enlarged.
- **Regression:** 52 automated tests pass. Browser checks of the same five screens at 320, 390, 768, and 1280 px found no page-wide horizontal overflow. The refreshed [desktop inventory](screenshots/inventory-v0.2.png) and [320 px inventory](screenshots/inventory-mobile-v0.2.png) screenshots contain synthetic data only.

## Verification boundaries

This was a synthetic browser audit. The 200% browser zoom shortcut did not change this in-app browser's viewport or device pixel ratio, so zoom remains unverified. NVDA/screen-reader behavior and touch on a physical device were not tested. The mobile CSS hides table headers and inserts cell labels with `::before`; that deserves a screen-reader check, but this audit does not claim a confirmed accessibility failure. Contrast looked readable in the inspected screens, but no complete WCAG color/interaction audit was performed.

The remaining visual release checks are a real 200% browser zoom and screen-reader pass, plus touch verification on a physical device.
