# Setting up PantryOS

A complete walkthrough, assuming you've never used a terminal. Expect about
30 minutes, most of it waiting for downloads.

**What you're building:** a small program on a computer in your home that
emails your family a proposed dinner menu every Friday, listens to what
everyone says about it, and on Saturday builds your grocery list and fills
your online cart for you to review and submit.

---

## What you need first

| Thing | Why | Notes |
|---|---|---|
| A computer that stays on | It wakes up on a schedule to send emails | A Mac, a Linux PC, or a Raspberry Pi. It can sleep at night — it just needs to be on in the mornings. |
| A Gmail account | PantryOS sends the emails from it | A free one is fine. **Consider making a new one** (e.g. `yourfamily.meals@gmail.com`) rather than using your personal inbox. |
| An AI account | It writes the meal plans | Three options — see Step 4. One is free if you already pay for Claude. |
| An online grocery account | Optional, for auto-filled carts | Whatever you already shop with. Without it you still get the list by email. |

---

## Step 1 — Open the terminal

The terminal is a window where you type commands instead of clicking.

- **Mac:** press `Cmd` + `Space`, type `terminal`, press `Enter`.
- **Ubuntu/Linux:** press `Ctrl` + `Alt` + `T`, or find "Terminal" in your apps.

A window opens with a blinking cursor. You'll type (or paste) lines here and
press `Enter` after each one. To paste: `Cmd`+`V` on Mac, `Ctrl`+`Shift`+`V`
on Linux.

**Check you have the two tools PantryOS needs.** Type this and press Enter:

```bash
git --version && python3 --version
```

- If you see two version numbers (Python must be **3.11 or higher**), continue.
- If it says "command not found":
  - **Mac:** type `xcode-select --install`, press Enter, and click through the
    installer. That provides git. For Python, download the latest from
    [python.org/downloads](https://www.python.org/downloads/).
  - **Ubuntu/Linux:** type
    `sudo apt update && sudo apt install git python3 python3-venv`
    and enter your computer password when asked (it won't show as you type).

---

## Step 2 — Download ("clone") PantryOS

"Cloning" just means downloading a copy of the code into a folder on your
computer. **You do not need a GitHub account** and nothing gets published —
this is a one-way download.

The folder lands wherever the terminal is currently pointed, which when you
first open it is your home folder (`/Users/yourname` on a Mac,
`/home/yourname` on Linux). That's a fine place. If you'd rather keep it
somewhere specific, go there first — for example your Documents folder:

```bash
cd ~/Documents
```

Now copy this line, paste it into the terminal, and press Enter:

```bash
git clone https://github.com/tjermann/PantryOS.git
```

You'll see a few lines about "Cloning into 'PantryOS'..." and counting
objects. When it finishes you have a new folder called **PantryOS**. Step into
it and run the installer:

```bash
cd PantryOS
./install.sh
```

`cd` means "change directory" — it moves the terminal into that folder, the
same as double-clicking it in Finder or Files. The installer takes a few
minutes (most of it downloading a browser it uses to fill grocery carts) and
sets everything up inside that one folder — it changes nothing else on your
computer. When it finishes it offers to start the setup questions; say yes and
continue to Step 3.

**Two things worth writing down:**

- **Getting back here later.** Every command in this guide is run from inside
  the PantryOS folder. To return to it in a new terminal window, type
  `cd ~/PantryOS` (or `cd ~/Documents/PantryOS` if you used Documents above).
  Not sure where you are? Type `pwd` to print your current folder.
- **Updating later.** To get improvements, run `git pull` from inside the
  PantryOS folder. Your household settings, recipes, ratings, and credentials
  live in files that updates never touch.

> **Prefer clicking to typing?** On the
> [GitHub page](https://github.com/tjermann/PantryOS) you can use the green
> **Code** button → **Download ZIP**, then unzip it and `cd` into the unzipped
> folder. Cloning is better (it makes `git pull` updates possible), but the ZIP
> works fine.

---

## Step 3 — Get a Gmail "app password"

PantryOS needs permission to send email from your Gmail account. Google doesn't
let programs use your normal password, so you create a special one just for
this. **No API, no billing, no Google Cloud project — just these clicks:**

1. Go to [myaccount.google.com/security](https://myaccount.google.com/security)
   and sign in with the Gmail account you want the emails to come from.
2. Turn on **2-Step Verification** if it isn't already. (Google requires this
   before app passwords exist. It's the usual phone-code setup.)
3. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
4. Type a name — `PantryOS` — and click **Create**.
5. Google shows a **16-letter code** like `abcd efgh ijkl mnop`. Copy it.
   You won't be able to see it again, but you can always make another.

The setup questions will ask for your Gmail address and this code. Paste it in
(spaces are fine). It gets saved in a file called `user_info.json` that lives
only on your computer and is never uploaded anywhere.

> **Prefer to type it into the file yourself?** In the `PantryOS/service`
> folder, copy `sample_user_info.json` to `user_info.json` and fill in the
> blanks with any text editor.

---

## Step 4 — Choose how the AI plans your meals

The setup asks which of these you want. Pick one:

| Option | Cost | Best if |
|---|---|---|
| **`claude-cli`** | Included in a Claude subscription | You already pay for Claude Pro/Max. Install [Claude Code](https://claude.com/claude-code) and sign in once; PantryOS uses that. Nothing extra to buy. |
| **`api`** | A few cents per week | You want the simplest path and don't mind a card on file. Get a key at [console.anthropic.com](https://console.anthropic.com) → API keys, and paste it when asked. |
| **`local`** | Free | You want everything to stay on your own machine. Install [Ollama](https://ollama.com), run `ollama pull llama3.1:8b`, and give PantryOS the address it prints (usually `http://localhost:11434/v1`). Plans are simpler than Claude's, but all the safety checks — allergies, seasonality, your rules — are plain code and work exactly the same. |

You can change your mind later by editing one line in your household's
`config.yaml`.

---

## Step 5 — Answer the setup questions

The questions are all plain English, and every answer can be changed later.
You'll be asked about:

- **Who eats** — names, and whether kids eat the planned dinners or have their
  own standing meals (nuggets night is a legitimate answer)
- **Allergies and restrictions** — *per person*, with severity. An allergy is a
  hard block enforced by code, not by the AI. Say what's still OK ("hard cheeses
  fine, coconut milk fine") and PantryOS works around it.
- **How many dinners** (and optional make-ahead lunches) per week
- **Which day** you want the plan to arrive
- **Your kitchen** — recipes needing gear you don't own are never suggested
- **Budget**, if you want one
- **Your stores**
- **Staples you always have** and things you buy every week
- **Who gets the emails**

---

## Step 6 — Fill your recipe library

PantryOS comes with a small starter set. To use recipes from sites you like,
open your household's config file (the setup prints its location, ending in
`config.yaml`) and add them under `recipe_sources`, then run:

```bash
service/.venv/bin/mealplanner discover-recipes --user YOURNAME --total 40
```

Replace `YOURNAME` with the household name you chose. This visits those sites,
finds real recipes, and files them with ingredients, steps, and timings. It
takes a while — that's normal. Run it again any time for more.

You can also add a single recipe you found:

```bash
service/.venv/bin/mealplanner add-recipe "https://example.com/some-recipe/" --user YOURNAME
```

---

## Step 7 — Sign in to your grocery store (optional)

```bash
service/.venv/bin/mealplanner login --user YOURNAME --store STORENAME
```

A browser window opens on the store's own website. **You** type your password
and any verification code, exactly as you would normally — PantryOS never sees
or stores your store password. Once you're signed in the window closes itself
and the session is remembered.

Skip this and everything still works; you'll just get the grocery list by email
instead of a pre-filled cart.

---

## Step 8 — Try it, then turn on autopilot

Preview a week without sending anything:

```bash
service/.venv/bin/mealplanner run-weekly --user YOURNAME --dry-run --force
```

Send a test email to check Gmail is working:

```bash
service/.venv/bin/mealplanner send-test-email --user YOURNAME
```

Happy? Turn on the schedule:

```bash
service/.venv/bin/mealplanner install-cron
```

That's it. From now on PantryOS runs itself: new recipes on Thursday, a
proposed menu Friday morning, revisions through Friday as your family reacts,
the real plan and filled cart Saturday, a "what's for dinner tonight" note each
afternoon, and a mid-week restock check.

---

## Step 9 — Let your family in

Start the family web page:

```bash
service/.venv/bin/mealplanner serve
```

Everyone gets a personal link in the emails. On any phone or laptop in the
house they can rate meals with one tap, leave notes, retire a dish forever,
tick off groceries you already have, and change preferences — no terminal, no
password. **They can also simply reply to any PantryOS email** with whatever
they think ("too spicy for the kids", "more soups") and it shapes next week.

---

## If something goes wrong

Run the checkup — it inspects everything and tells you the exact fix:

```bash
service/.venv/bin/mealplanner doctor
```

Common ones:

| Symptom | Fix |
|---|---|
| Family page won't load in Chrome (works in Safari) | Chrome forces `https://`. Click **Advanced → Continue**, or turn off Chrome → Settings → Privacy and security → Security → "Always use secure connections". |
| Family page won't load anywhere | `mealplanner restart-serve` |
| Cart says "session expired" | `mealplanner login --user YOURNAME --store STORENAME` again |
| No email arrived | `mealplanner doctor --check-email` |
| Emails stopped after a reboot | `mealplanner install-cron` (safe to re-run) |

Still stuck? Open an issue at
[github.com/tjermann/PantryOS/issues](https://github.com/tjermann/PantryOS/issues)
with what `doctor` printed.

---

## What PantryOS will never do

- **Place an order.** It fills the cart; a human always reviews and pays.
- **Learn your store password.** You sign in yourself, in a real browser.
- **Send your data anywhere.** Credentials, preferences, ratings, and browsing
  sessions stay in files on your computer. The only outside calls are to your
  chosen AI provider (none, if you use a local model), Gmail, and the recipe
  sites and store you picked.
- **Trust the AI on allergies.** Every plan is re-checked by ordinary code
  against your household's restrictions before anyone sees it.
