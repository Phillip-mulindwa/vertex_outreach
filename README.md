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
and is left out of the clean file of a "New leads to check" upload.

Phone numbers may use spaces, dashes, brackets, a leading `+` or `00`, or be `wa.me` /
`api.whatsapp.com` links. Numbers without a country code need a default country; without one
they are INVALID ("needs country code").

### Checking leads

**Check Leads** (Outreach workspace, or the button on the Outreach Lead list) has two tabs:

- **Check one lead** (the default): Company name, Email, WhatsApp country (remembered per user)
  and WhatsApp number as separate fields, checked as you type. **Check** shows one result card,
  e.g. "ALREADY CONTACTED: matched on WhatsApp +256772123456, by Grace Achieng on 12 Oct 2026,
  company Acme Travel". **Check & Claim** claims a fresh lead as ONE lead with all three, then
  clears the fields.
- **Check many**: paste emails and numbers mixed in any format, choose a default country, then
  **Check**, or **Check & Claim Fresh**. A line with a company, an email and a number becomes one
  lead. **Copy fresh** copies the fresh inputs.

API (Outreach User, Outreach Manager and System Manager):

- `POST /api/method/vertex_outreach.api.check_one` with `company`, `email`, `whatsapp`,
  `whatsapp_country` and `claim` (0/1).
- `POST /api/method/vertex_outreach.api.check_leads` with `text`, `claim` (0/1) and optional
  `default_country`. `vertex_outreach.api.check_emails` (`emails`, `claim`) still works.

### Upload a list

**Upload a list** (DocType `Email Upload`). **Download template** gives an XLSX with the columns
Company, Email, WhatsApp, Country. In CSV/XLSX files with a header row naming an email or WhatsApp
column (common variants such as `E-mail`, `Phone`, `Mobile`, `Organisation`, `Company Name` are
accepted), each row is read as one lead. Other files and sheets are read line by line like Check
Leads. **Default Country** applies to numbers without a country code when the row has no Country.

- **New leads to check** claims the fresh leads and attaches a clean CSV of them.
- **Past contacts (history)** records leads not yet in the system as Contacted, and moves matching
  Claimed leads to Contacted.
- **Signed partners** marks the matching leads Signed Partner (creating them when missing) and
  creates or updates a Signed Partner record per row, including WhatsApp-only rows.

Conflicts are counted and attached as a CSV for a manager to review.

### Signed partners

Partners are kept in the **Signed Partner** list (`SP-#####`; System Manager and Outreach Manager
can edit it, Outreach User can read it), each with an email, a WhatsApp number or both, each
unique. Saving a partner upserts the Outreach Lead matched by email or WhatsApp: it becomes Signed
Partner and gets the organization and any identifier it lacks (an identifier it already holds a
different value for goes on a new Signed Partner lead, so every partner identifier is blocked).
If the email and the number are on two different leads, the save is blocked as a conflict.
Deleting a partner sets its leads back to Contacted.

### Weekly summary

The **Outreach Summary** report shows leads claimed, contacted, replied and signed per user
(credited to the user who claimed or uploaded the lead). The Auto Email Report
**Weekly outreach summary** sends the last 7 days every Monday; it is disabled until you set its
recipients and enable it.

### Bulk import a folder

Every .csv / .xlsx / .xlsm / .pdf / .txt file under the folder (recursively) becomes its own
upload, processed one at a time with a progress line per file:

```bash
bench --site <site> execute vertex_outreach.bulk.import_folder \
  --kwargs "{'path': '/path/to/folder', 'upload_type': 'Past contacts (history)', 'default_country': 'Kenya'}"
```

`upload_type` is `Past contacts (history)` (default), `New leads to check` or `Signed partners`
(the old names still work);
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

The desk helpers (`public/js/check_leads.js`) ship as `vertex_outreach.bundle.js`, so after changing
them run `bench build --app vertex_outreach`. The built file has a content hash in its name, so
browsers pick up the new version instead of a cached copy.


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
