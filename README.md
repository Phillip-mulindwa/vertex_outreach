### Vertex Outreach

Outreach lead dedup (email and WhatsApp) and partner blocking for Vertex International Recruitment

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch main
bench install-app vertex_outreach
```

### Leads

An **Outreach Lead** (DocType `Outreach Contact`) is one organisation or person to reach, identified
by its **email**, its **WhatsApp** number (stored as E.164, e.g. `+256772123456`), or both. Each is
unique; at least one is required. Company names are not unique and are never used for matching.
New leads are named `LEAD-#####`; leads created before this keep their email as their name, but
nothing relies on that.

A row is **ALREADY CONTACTED** when its email *or* WhatsApp matches a lead (the result says which).
Other verdicts: **SIGNED PARTNER**, **DO NOT CONTACT** (Unsubscribed / Bounced), **CONFLICT** (the
email is on one lead and the number on another: a manager should review), **EXCLUDED COUNTRY**,
**INVALID** and **FRESH**. A fresh row whose company name matches other leads (case-insensitive)
gets a note such as "2 other leads named Acme".

Statuses: Claimed, Contacted, Replied, In Discussion, Signed Partner, Not Interested,
Unsubscribed, Bounced. Claiming makes a lead **Claimed**; use **Mark as Contacted** on the form or
as a bulk action in the list once you have reached out. A daily job deletes leads still Claimed
and never contacted after 14 days so others can claim them.

**Outreach Settings** holds the release period (0 turns it off) and the excluded countries
(Uganda and South Africa by default). A number from an excluded country, an email on its ccTLD
(`.ug`, `.za`) or a row whose Country column names it is EXCLUDED COUNTRY: it cannot be claimed
and is left out of Scraped Leads clean files.

Phone numbers may use spaces, dashes, brackets, a leading `+` or `00`, or be `wa.me` /
`api.whatsapp.com` links. Numbers without a country code need a default country; without one
they are INVALID ("needs country code").

### Checking leads

- **Check Leads** (Outreach workspace, or the button on the Outreach Lead list): paste emails and
  numbers mixed in any format, choose a default country (remembered per user), then **Check**, or
  **Check & Claim Fresh** to claim the fresh ones. A line with a company, an email and a number
  becomes one lead. **Copy fresh** copies the fresh inputs.
- API: `POST /api/method/vertex_outreach.api.check_leads` with `text`, `claim` (0/1) and optional
  `default_country`. `vertex_outreach.api.check_emails` (`emails`, `claim`) still works.
  Available to Outreach User, Outreach Manager and System Manager.

### Email Upload

**Download template** gives an XLSX with the columns Company, Email, WhatsApp, Country. In
CSV/XLSX files with a header row naming an email or WhatsApp column (common variants such as
`E-mail`, `Phone`, `Mobile`, `Organisation`, `Company Name` are accepted), each row is read as one
lead. Other files and sheets are read line by line like Check Leads. **Default Country** applies
to numbers without a country code when the row has no Country.

- **Scraped Leads** claims the fresh leads and attaches a clean CSV of them.
- **Already Contacted** records leads not yet in the system as Contacted, and moves matching
  Claimed leads to Contacted.
- **Signed Partners** marks the matching leads Signed Partner (creating them when missing) and
  creates a Signed Partner record per email.

Conflicts are counted and attached as a CSV for a manager to review.

### Signed partners

Partners are tracked per email, in the **Signed Partner** list (System Manager and Outreach
Manager can edit it; Outreach User can read it). Saving a partner marks the lead with that email
as Signed Partner (creating it if needed); deleting one sets the lead back to Contacted.

### Weekly summary

The **Outreach Summary** report shows leads claimed, contacted, replied and signed per user
(credited to the user who claimed or uploaded the lead). The Auto Email Report
**Weekly outreach summary** sends the last 7 days every Monday; it is disabled until you set its
recipients and enable it.

### Bulk import a folder

Every .csv / .xlsx / .xlsm / .pdf / .txt file under the folder (recursively) becomes its own
Email Upload, processed one at a time with a progress line per file:

```bash
bench --site <site> execute vertex_outreach.bulk.import_folder \
  --kwargs "{'path': '/path/to/folder', 'upload_type': 'Already Contacted', 'default_country': 'Kenya'}"
```

`upload_type` is `Already Contacted` (default), `Scraped Leads` or `Signed Partners`;
`source` defaults to each file's name.

### Demo data

```bash
bench --site <site> execute vertex_outreach.demo.load   # replaces any previous demo data
bench --site <site> execute vertex_outreach.demo.clear  # removes only the demo data
```

`load` prints a `try_in_check_leads` text to paste into Check Leads: it shows every verdict,
including a CONFLICT, a match on WhatsApp with a different email and a shared company name.

### Tests

```bash
bench --site <site> run-tests --module vertex_outreach.tests.test_leads
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/vertex_outreach
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
