# Bakalari Timetable to Notion

Automatically fetches the timetable from Bakalari and synchronizes it with a Notion database.

Skript:

- imports the current week starting on Monday and the following two weeks,
- creates new lessons in Notion,
- updates changes to the subject, room, teacher, time, or status,
- skips lessons that have not changed,
- archives duplicate pages with the same lesson start time,
- runs automatically through GitHub Actions after a push to `main` and every 30 minutes.

export BAKALARI_URL="https://your-school.bakalari.cz/"
export BAKALARI_USERNAME="your_username"
export BAKALARI_PASSWORD="your_password"

export NOTION_DATABASE_ID="your_database_id"
| --- | --- |
| `Název` | Title |
| `Místnost` | Select |
| `Učitel` | Text |
| `Status` | Text |
| `Datum` | Date |

A Notion token and database ID are required for API access.

## Local Setup

Create a virtual environment and install the dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```
Open **Settings > Secrets and variables > Actions** in the repository and add these repository secrets:
Set the environment variables:
export NOTION_TOKEN="ntn_xxx"
The workflow is located at `.github/workflows/sync-timetable.yml`. After it is pushed to the `main` branch, it runs automatically and then continues according to the 30-minute schedule. GitHub may slightly delay scheduled runs during periods of high load.
```

Run the synchronization:

```bash
.venv/bin/python main.py
```

Optional variables:

```bash
export WEEKS_AHEAD="3"
export TIMEZONE="Europe/Prague"
```

## GitHub Actions

Open **Settings > Secrets and variables > Actions** in the repository and add these repository secrets:

- `BAKALARI_URL`
- `BAKALARI_USERNAME`
- `BAKALARI_PASSWORD`
- `NOTION_TOKEN`
- `NOTION_DATABASE_ID`

The workflow is located at `.github/workflows/sync-timetable.yml`. After it is pushed to the `main` branch, it runs automatically and then continues according to the 30-minute schedule. GitHub may slightly delay scheduled runs during periods of high load.

## Security

Do not store credentials or tokens in the source code. Use local environment variables or GitHub Secrets. The `.env` file is ignored by Git.

## License

No license has been defined yet.
