# Pitch (plain language)

## One line
**ShelfSense listens to what customers ask for, tells the shop owner what to stock, and messages the customers when it arrives.**

## The problem
Think of your local shop. A customer asks for something. The shop doesn't have it. The customer leaves. **Nobody ever finds out.** The owner only sees what was sold, never what was wanted. So they keep missing the same sales, and customers keep leaving disappointed.

## What we built
1. **A shopping assistant** that talks to customers in English, Hindi and Telugu, by voice or text. It answers honestly: "we have it", "it's out of stock", "that's above your budget", or "we don't have that yet, here's the closest".
2. **An owner's dashboard** that turns every unanswered request into a clear to-do. It shows empty slots on a shelf: *"9 people asked for gluten-free pasta."* One click lists the product or approves a reorder.
3. **A follow-up that closes the loop.** When the product arrives, the customers who said "yes, tell me" get a message in their own language.

## Why it's different
Most tools learn from what *sold*. ShelfSense also learns from what was *wanted but couldn't be found*, and it acts on it end to end: ask → notice → stock → tell.

## Why it matters
- **Small shops** can't afford big analytics teams. This gives them a clear list of what to do, in plain words.
- **Customers** get honest answers in their own language, and a message when their item is back, only if they agreed.
- **Fewer lost sales and less waste**, because orders are based on real demand, including the demand that was turned away.

## What we are proud of
- It **doesn't trust empty shelves as "no demand"**. Days when an item was out of stock are corrected before forecasting.
- **Humans stay in charge.** The AI suggests; the owner approves. Every action is logged.
- **Consent first.** Nobody is messaged unless they said yes.
- **Always works.** If the AI model is unavailable, a built-in engine keeps the shop running.

## Built on Google
Gemini and the Agent Development Kit (the AI agents), Firestore and BigQuery (data), Cloud Run (hosting).

## Numbers to quote, and how
These come from our **synthetic demo store**, so say so: "In our demo store, about **1 in 3 shopper requests couldn't be served**, putting roughly **₹9,500 of weekly sales at risk** across 6 repeat needs. Our forecast made about **23% fewer errors** than simply repeating last week." Don't present these as results from a real shop.

## Questions judges may ask
- **"Is the data real?"** The store and sales are synthetic so the demo is repeatable. The system reads real sales from BigQuery and real catalogue data via configuration, and the pilot would calibrate our two stated assumptions.
- **"What if the AI gets it wrong?"** Prices, stock and numbers come from code, not the AI. The AI only talks and picks tools. The owner approves every action.
- **"Privacy?"** Phone numbers and emails are masked; messages need a yes; every write is audited. See `docs/RESPONSIBLE_AI.md`.
- **"What's next?"** WhatsApp delivery, embedding-based grouping of similar requests, real POS integration, and a pilot with a few kirana stores.
