### Vertex Outreach

Outreach email dedup and partner blocking for Vertex International Recruitment

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch main
bench install-app vertex_outreach
```

### Signed partners

Partners are tracked per email, in the **Signed Partner** list (System Manager and Outreach
Manager can edit it; Outreach User can read it). Saving a partner marks the matching Outreach
Contact as Signed Partner (creating it if needed); deleting one sets the contact back to Contacted.
Partner status everywhere (uploads, Check Emails, manual entry) comes from
`Outreach Contact.status == "Signed Partner"`.

A **Signed Partners** Email Upload creates or updates a Signed Partner per email. In CSV/XLSX
files, a header row with an `email` column and an `organization` / `organisation` / `company`
column is read as pairs; otherwise every email is extracted with no organization.

### Checking emails

- **Outreach Contact list → Check Emails**, or the **Check Emails** shortcut in the Outreach workspace:
  paste emails in any format, then **Check**, or **Check & Claim Fresh** to record the fresh ones as
  Contacted by you.
- API: `POST /api/method/vertex_outreach.api.check_emails` with `emails` (text) and `claim` (0/1).
  Available to Outreach User and System Manager.

### Bulk import a folder

Every .csv / .xlsx / .xlsm / .pdf / .txt file under the folder (recursively) becomes its own
Email Upload, processed one at a time with a progress line per file:

```bash
bench --site <site> execute vertex_outreach.bulk.import_folder \
  --kwargs "{'path': '/path/to/folder', 'upload_type': 'Already Contacted'}"
```

`upload_type` is `Already Contacted` (default), `Scraped Leads` or `Signed Partners`;
`source` defaults to each file's name.

### Demo data

```bash
bench --site <site> execute vertex_outreach.demo.load   # replaces any previous demo data
bench --site <site> execute vertex_outreach.demo.clear  # removes only the demo data
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
