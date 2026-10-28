# 3-minute demo script

Start the app (`make api` + `make web`, or the deployed `--demo` URL). Choose **Side by side**. Shopper on the left, owner console on the right.

**0:00 · The problem (one line).** "A store only learns from what sold. It never learns what customers wanted and couldn't get."

**0:20 · The shelf.** Point at the right side. "These dashed slots are things shoppers asked for that this store can't serve. 9 asked for gluten-free pasta. 6 wanted wireless earbuds under ₹1,000. 5 asked for basmati rice that is out of stock." Point at the ledger: "35% of requests couldn't be served this week, about ₹9,500 of sales at risk."

**0:50 · A shopper asks.** In the chat, type `gluten free pasta under 300`. The assistant answers honestly ("we don't have exactly that"), shows the closest items, and asks whether to message them. Click **Yes, notify me**. Open *How the agents handled this* to show the tool calls.

**1:20 · Other languages.** Click the suggestion `मुझे चीनी चाहिए` (Hindi) or `నాకు నూనె కావాలి` (Telugu). Mention the mic button for voice.

**1:40 · Make it spike (optional).** In **Send test shoppers**, ask for `vegan protein bar` × 8 and send. A new slot appears on the shelf.

**1:55 · The owner acts.** Click the **gluten free pasta** slot. It shows 9 shoppers, the assumptions behind the demand estimate, and an editable suggestion (name, price, opening stock). Click **List it and message … waiting shoppers**.

**2:20 · Loop closed.** The drawer shows the messages sent, each in the shopper's language. On the left, the chat receives the "Good news" message: "The shopper who said yes is told automatically, and only because they said yes."

**2:40 · Not just a chatbot.** Scroll to **Reorder now**: basmati rice is critical. Open *Why this quantity*, then click the row to see the forecast chart. "The pink bands are days the shelf was empty. Most systems read those as 'no demand'. We correct for it. Shoppers turned away are added to the forecast."

**2:55 · Close.** "Every action is human-approved and logged. It runs on Gemini with Google's Agent Development Kit, Firestore, BigQuery and Cloud Run. And if the model is down, it falls back to a built-in engine, so a shopper always gets an answer."

### If something goes wrong
- *No Gemini key:* the header pill says **Built-in engine**. Everything above still works.
- *Shelf empty after resets:* **Reset demo data** (bottom right), then reload.
- *Notifications slow:* the shopper inbox polls every ~3.5 s; sending any chat message triggers an immediate refresh.
