"""
Synchronizace rozvrhu z Bakalářů (přes bakapi-v2) do Notion databáze.

Očekávané proměnné prostředí (nastav je jako GitHub Actions secrets):
    BAKALARI_URL       - URL přihlašovací stránky Bakalářů, např. https://skola.bakalari.cz/
    BAKALARI_USERNAME  - přihlašovací jméno
    BAKALARI_PASSWORD  - heslo
    NOTION_TOKEN       - Internal Integration Secret Notion integrace
    NOTION_DATABASE_ID - ID cílové databáze v Notionu

Volitelné:
    WEEKS_AHEAD        - kolik týdnů (včetně aktuálního) stahovat, default 3
    TIMEZONE           - IANA timezone, default "Europe/Prague"
"""

import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bakapiv2 import BakapiUser, BakaAPIException

NOTION_VERSION = "2022-06-28"
NOTION_API = "https://api.notion.com/v1"


def env(name, default=None, required=False):
    val = os.environ.get(name, default)
    if required and not val:
        print(f"Chybí povinná proměnná prostředí: {name}", file=sys.stderr)
        sys.exit(1)
    return val


def get_config():
    return {
        "bakalari_url": env("BAKALARI_URL", required=True),
        "bakalari_username": env("BAKALARI_USERNAME", required=True),
        "bakalari_password": env("BAKALARI_PASSWORD", required=True),
        "notion_token": env("NOTION_TOKEN", required=True),
        "notion_database_id": env("NOTION_DATABASE_ID", required=True),
        "weeks_ahead": int(env("WEEKS_AHEAD", "3")),
        "timezone": env("TIMEZONE", "Europe/Prague"),
    }


def fetch_timetable_weeks(user: BakapiUser, weeks_ahead: int):
    """Stáhne rozvrh pro aktuální týden + `weeks_ahead - 1` týdnů dopředu.
    Vrací seznam (dict) odpovědí z API, jednu na týden."""
    today = datetime.now().date()
    week_start = today - timedelta(days=today.weekday())
    responses = []
    for i in range(weeks_ahead):
        target_date = week_start + timedelta(weeks=i)
        resp = user.get_timetable_actual(date=target_date)
        responses.append(resp)
    return responses


def index_by_id(items):
    return {item["Id"]: item for item in items} if items else {}


def parse_hhmm(value, date_obj, tz):
    """'8:00' + datum -> timezone-aware datetime"""
    hour, minute = [int(x) for x in value.split(":")]
    naive = datetime(date_obj.year, date_obj.month, date_obj.day, hour, minute)
    return naive.replace(tzinfo=tz)


def build_events(timetable_responses, tz):
    """Převede odpovědi z Bakalářů na plochý seznam událostí."""
    events = []
    for resp in timetable_responses:
        hours_by_id = index_by_id(resp.get("Hours"))
        subjects_by_id = index_by_id(resp.get("Subjects"))
        teachers_by_id = index_by_id(resp.get("Teachers"))
        rooms_by_id = index_by_id(resp.get("Rooms"))

        for day in resp.get("Days", []):
            date_str = day["Date"][:10]  # "YYYY-MM-DD"
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()

            for atom in day.get("Atoms", []):
                subject_id = atom.get("SubjectId")
                if not subject_id:
                    # hodina bez předmětu (volno, prázdný atom) - přeskočit
                    continue

                hour = hours_by_id.get(atom.get("HourId"))
                if not hour:
                    continue

                start_dt = parse_hhmm(hour["BeginTime"], date_obj, tz)
                end_dt = parse_hhmm(hour["EndTime"], date_obj, tz)

                subject = subjects_by_id.get(subject_id, {})
                subject_name = subject.get("Name") or subject.get("Abbrev") or subject_id

                teacher_id = atom.get("TeacherId")
                teacher = teachers_by_id.get(teacher_id, {}) if teacher_id else {}
                teacher_name = teacher.get("Name") or teacher.get("Abbrev") or ""

                room_id = atom.get("RoomId")
                room = rooms_by_id.get(room_id, {}) if room_id else {}
                room_name = room.get("Name") or room.get("Abbrev") or ""

                change = atom.get("Change")
                if change:
                    change_type = (change.get("ChangeType") or change.get("TypeAbbrev") or "").lower()
                    if "removed" in change_type or "zrušen" in change_type or "cancel" in change_type:
                        status = "Zrušeno"
                    else:
                        status = "Změna"
                else:
                    status = "Normální"

                unique_key = f"{date_str}_{atom.get('HourId')}_{subject_id}"

                events.append(
                    {
                        "unique_key": unique_key,
                        "name": subject_name,
                        "start": start_dt.isoformat(),
                        "end": end_dt.isoformat(),
                        "room": room_name,
                        "teacher": teacher_name,
                        "status": status,
                    }
                )
    return events


class NotionClient:
    def __init__(self, token, database_id):
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }
        self.database_id = database_id

    @staticmethod
    def build_properties(event):
        return {
            "Název": {"title": [{"text": {"content": event["name"]}}]},
            "Místnost": {"select": {"name": event["room"]}},
            "Učitel": {"rich_text": [{"text": {"content": event["teacher"]}}]},
            "Status": {"rich_text": [{"text": {"content": event["status"]}}]},
            "Datum": {"date": {"start": event["start"], "end": event["end"]}},
        }

    def create_event(self, event):
        response = requests.post(
            f"{NOTION_API}/pages",
            headers=self.headers,
            json={
                "parent": {"database_id": self.database_id},
                "properties": self.build_properties(event),
            },
        )
        response.raise_for_status()

    def get_existing_events(self):
        pages = []
        next_cursor = None
        while True:
            payload = {"page_size": 100}
            if next_cursor:
                payload["start_cursor"] = next_cursor

            response = requests.post(
                f"{NOTION_API}/databases/{self.database_id}/query",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            pages.extend(data.get("results", []))

            if not data.get("has_more"):
                return pages
            next_cursor = data.get("next_cursor")

    @staticmethod
    def event_key(event):
        return event["start"]

    @staticmethod
    def page_event_key(page):
        properties = page.get("properties", {})
        date = properties.get("Datum", {}).get("date") or {}
        return date.get("start", "")

    @staticmethod
    def page_values(page):
        properties = page.get("properties", {})
        room = properties.get("Místnost", {}).get("select") or {}
        teacher = properties.get("Učitel", {}).get("rich_text", [])
        status = properties.get("Status", {}).get("rich_text", [])
        date = properties.get("Datum", {}).get("date") or {}
        return {
            "name": "".join(
                item.get("plain_text", "")
                for item in properties.get("Název", {}).get("title", [])
            ),
            "room": room.get("name", ""),
            "teacher": "".join(item.get("plain_text", "") for item in teacher),
            "status": "".join(item.get("plain_text", "") for item in status),
            "start": date.get("start", ""),
            "end": date.get("end", ""),
        }

    def sync_event(self, event, existing_by_key):
        page = existing_by_key.get(self.event_key(event))
        if not page:
            self.create_event(event)
            return "created"

        current = self.page_values(page)
        desired = {
            "name": event["name"],
            "room": event["room"],
            "teacher": event["teacher"],
            "status": event["status"],
            "start": event["start"],
            "end": event["end"],
        }
        if current == desired:
            return "unchanged"

        response = requests.patch(
            f"{NOTION_API}/pages/{page['id']}",
            headers=self.headers,
            json={"properties": self.build_properties(event)},
        )
        response.raise_for_status()
        return "updated"


def main():
    config = get_config()
    tz = ZoneInfo(config["timezone"])

    print("Přihlašuji se k Bakalářům...")
    try:
        user = BakapiUser(
            url=config["bakalari_url"],
            username=config["bakalari_username"],
            password=config["bakalari_password"],
        )
    except BakaAPIException as e:
        print(f"Chyba přihlášení k Bakalářům: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Stahuji rozvrh na {config['weeks_ahead']} týden/týdny dopředu...")
    timetable_responses = fetch_timetable_weeks(user, config["weeks_ahead"])

    events = build_events(timetable_responses, tz)
    print(f"Nalezeno {len(events)} hodin k synchronizaci.")

    notion = NotionClient(config["notion_token"], config["notion_database_id"])
    existing_pages = notion.get_existing_events()
    existing_by_key = {
        notion.page_event_key(page): page
        for page in existing_pages
        if notion.page_event_key(page)
    }

    created, updated, unchanged, failed = 0, 0, 0, 0
    for event in events:
        try:
            result = notion.sync_event(event, existing_by_key)
            if result == "created":
                created += 1
            elif result == "updated":
                updated += 1
            else:
                unchanged += 1
        except requests.HTTPError as error:
            failed += 1
            response_text = error.response.text if error.response is not None else str(error)
            print(
                f"Chyba u události {event['unique_key']}: {response_text}",
                file=sys.stderr,
            )

    print(
        f"Notion: vytvořeno {created}, aktualizováno {updated}, "
        f"beze změny {unchanged}, chyby {failed}"
    )
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()