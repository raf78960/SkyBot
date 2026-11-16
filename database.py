"""
Couche d'accès aux données (SQLite, via aiosqlite pour rester 100% async).
"""

import aiosqlite
from datetime import datetime, timezone
from config import DB_PATH


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id INTEGER PRIMARY KEY,
                formateur_role_id INTEGER,
                announcement_channel_id INTEGER,
                staff_role_id INTEGER,
                ticket_access_category_id INTEGER,
                ticket_support_category_id INTEGER,
                ticket_log_channel_id INTEGER,
                disponibilites_channel_id INTEGER,
                freq_category_id INTEGER,
                flightplan_channel_id INTEGER,
                flightplan_log_channel_id INTEGER
            )
        """)
        # Migrations colonnes (bases déjà créées)
        for col, typ in [
            ("staff_role_id", "INTEGER"),
            ("ticket_access_category_id", "INTEGER"),
            ("ticket_support_category_id", "INTEGER"),
            ("ticket_log_channel_id", "INTEGER"),
            ("disponibilites_channel_id", "INTEGER"),
            ("freq_category_id", "INTEGER"),
            ("flightplan_channel_id", "INTEGER"),
            ("flightplan_log_channel_id", "INTEGER"),
            ("freq_announce_channel_id", "INTEGER"),
            ("freq_ping_role_id", "INTEGER"),
            ("freq_log_channel_id", "INTEGER"),
            ("session_ping_avion_role_id", "INTEGER"),
            ("session_ping_pilote_role_id", "INTEGER"),
            ("session_ping_atc_role_id", "INTEGER"),
            ("session_ping_site_atc_role_id", "INTEGER"),
            ("session_ping_site_pilote_role_id", "INTEGER"),
            ("ticket_ping_role_id", "INTEGER"),
            ("ticket_access_log_channel_id", "INTEGER"),
            ("ticket_support_log_channel_id", "INTEGER"),
            ("ticket_support_ping_role_id", "INTEGER"),
            ("freq_lock_deny_role_ids", "TEXT"),
            ("atc_planning_mod_channel_id", "INTEGER"),
            ("absence_role_ids", "TEXT"),
            ("absence_temp_role_id", "INTEGER"),
            ("absence_log_channel_id", "INTEGER"),
            ("absence_panel_channel_id", "INTEGER"),
            ("absence_panel_message_id", "INTEGER"),
            ("absence_ping_role_ids", "TEXT"),
            ("callsign_manager_role_id", "INTEGER"),
            ("role_guide_channel_id", "INTEGER"),
            ("role_guide_message_ids", "TEXT"),
        ]:
            try:
                await db.execute(f"ALTER TABLE guild_config ADD COLUMN {col} {typ}")
            except aiosqlite.OperationalError:
                pass

        # Colonnes strips ATC (plans de vol)
        for col, typ in [
            ("sid_rwy", "TEXT"),
            ("star_rwy", "TEXT"),
            ("initial_climb", "TEXT"),
            ("strip_status", "TEXT"),
            ("strip_atc", "TEXT"),
            ("remark", "TEXT"),
            ("strip_atc_user_id", "INTEGER"),
            ("squawk", "TEXT"),
        ]:
            try:
                await db.execute(f"ALTER TABLE flight_plans ADD COLUMN {col} {typ}")
            except aiosqlite.OperationalError:
                pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                formateur_id INTEGER NOT NULL,
                date_time_utc TEXT NOT NULL,
                max_participants INTEGER DEFAULT 0,
                channel_id INTEGER,
                message_id INTEGER,
                created_by INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'planned',
                reminder_24h_sent INTEGER NOT NULL DEFAULT 0,
                reminder_1h_sent INTEGER NOT NULL DEFAULT 0,
                session_type TEXT
            )
        """)
        for col, typ in [
            ("session_type", "TEXT"),
            ("duration_minutes", "INTEGER"),
        ]:
            try:
                await db.execute(f"ALTER TABLE sessions ADD COLUMN {col} {typ}")
            except aiosqlite.OperationalError:
                pass
        # Durée par défaut 120 min pour les sessions existantes sans valeur
        try:
            await db.execute(
                "UPDATE sessions SET duration_minutes = 120 "
                "WHERE duration_minutes IS NULL OR duration_minutes = 0"
            )
        except aiosqlite.OperationalError:
            pass
        await db.execute("""
            CREATE TABLE IF NOT EXISTS inscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                inscribed_at TEXT NOT NULL,
                UNIQUE(session_id, user_id),
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS frequencies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                voice_channel_id INTEGER NOT NULL,
                text_channel_id INTEGER,
                message_id INTEGER,
                name TEXT NOT NULL,
                icao TEXT,
                locked INTEGER NOT NULL DEFAULT 0,
                atc_user_id INTEGER,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                UNIQUE(guild_id, voice_channel_id)
            )
        """)
        for col, typ in [
            ("icao", "TEXT"),
            ("position", "TEXT"),
            ("frequency_mhz", "TEXT"),
            ("languages", "TEXT"),
        ]:
            try:
                await db.execute(f"ALTER TABLE frequencies ADD COLUMN {col} {typ}")
            except aiosqlite.OperationalError:
                pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                ticket_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                claimed_by INTEGER,
                created_at TEXT NOT NULL,
                closed_at TEXT,
                motif TEXT,
                close_reason TEXT
            )
        """)
        for col, typ in [
            ("motif", "TEXT"),
            ("close_reason", "TEXT"),
        ]:
            try:
                await db.execute(f"ALTER TABLE tickets ADD COLUMN {col} {typ}")
            except aiosqlite.OperationalError:
                pass
        await db.execute("""
            CREATE TABLE IF NOT EXISTS flight_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                flight_type TEXT NOT NULL,
                callsign TEXT NOT NULL,
                departure TEXT NOT NULL,
                arrival TEXT NOT NULL,
                gate TEXT,
                simbrief_url TEXT,
                message_id INTEGER,
                created_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS disponibilites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                target_user_id INTEGER NOT NULL,
                requested_by INTEGER NOT NULL,
                dispos_text TEXT NOT NULL,
                commentaire TEXT,
                ticket_channel_id INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                taken_by INTEGER,
                channel_id INTEGER,
                message_id INTEGER,
                created_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS preopen_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                atc_user_id INTEGER NOT NULL,
                position TEXT NOT NULL,
                location TEXT NOT NULL,
                icao TEXT,
                frequency_mhz TEXT NOT NULL,
                languages TEXT,
                hour_str TEXT NOT NULL,
                scheduled_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            )
        """)

        # ---------- Concours photo ----------
        await db.execute("""
            CREATE TABLE IF NOT EXISTS contests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                channel_id INTEGER NOT NULL,
                start_at TEXT NOT NULL,
                end_at TEXT NOT NULL,
                max_photos INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'active',
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                ended_at TEXT,
                announce_message_id INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS contest_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contest_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                likes INTEGER NOT NULL DEFAULT 0,
                rank INTEGER,
                points_participation INTEGER NOT NULL DEFAULT 0,
                points_likes INTEGER NOT NULL DEFAULT 0,
                points_rank INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(contest_id) REFERENCES contests(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_points (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                total_points INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS points_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                reason TEXT NOT NULL,
                contest_id INTEGER,
                created_at TEXT NOT NULL
            )
        """)
        # Planning ATC hebdomadaire (créneaux proposés par les ATC)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS atc_planning_slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                atc_user_id INTEGER NOT NULL,
                week_start TEXT NOT NULL,
                slot_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                location TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS atc_planning_panels (
                guild_id INTEGER NOT NULL,
                week_offset INTEGER NOT NULL DEFAULT 0,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, week_offset)
            )
        """)
        for col, typ in [
            ("atc_planning_channel_id", "INTEGER"),
            ("company_status", "TEXT"),
            ("pilot_role_id", "INTEGER"),
            ("company_status_channel_id", "INTEGER"),
            ("company_status_message_id", "INTEGER"),
            ("pilot_list_channel_id", "INTEGER"),
            ("pilot_list_message_id", "INTEGER"),
            ("config_panel_channel_id", "INTEGER"),
            ("config_panel_message_id", "INTEGER"),
            ("company_recruit_status", "TEXT"),
            ("company_ceo_id", "INTEGER"),
            ("company_invite_url", "TEXT"),
            ("company_logo_url", "TEXT"),
            ("company_card_channel_id", "INTEGER"),
            ("company_card_message_id", "INTEGER"),
            ("company_recruit_channel_id", "INTEGER"),
            ("company_recruit_message_id", "INTEGER"),
            ("companies_forum_channel_id", "INTEGER"),
            ("gerant_atc_role_id", "INTEGER"),
            ("freq_admin_panel_channel_id", "INTEGER"),
            ("freq_admin_panel_message_id", "INTEGER"),
            ("freq_text_category_id", "INTEGER"),
            ("ticket_support_ping_role_id", "INTEGER"),
            ("freq_lock_deny_role_ids", "TEXT"),
            ("atc_planning_mod_channel_id", "INTEGER"),
            ("absence_role_ids", "TEXT"),
            ("absence_temp_role_id", "INTEGER"),
            ("absence_log_channel_id", "INTEGER"),
            ("absence_panel_channel_id", "INTEGER"),
            ("absence_panel_message_id", "INTEGER"),
            ("absence_ping_role_ids", "TEXT"),
            ("callsign_manager_role_id", "INTEGER"),
            ("role_guide_channel_id", "INTEGER"),
            ("role_guide_message_ids", "TEXT"),
        ]:
            try:
                await db.execute(f"ALTER TABLE guild_config ADD COLUMN {col} {typ}")
            except aiosqlite.OperationalError:
                pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS atc_planning_modifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slot_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                requested_by INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                old_slot_date TEXT,
                old_start_time TEXT,
                old_end_time TEXT,
                old_duration_minutes INTEGER,
                old_location TEXT,
                new_slot_date TEXT NOT NULL,
                new_start_time TEXT NOT NULL,
                new_end_time TEXT NOT NULL,
                new_duration_minutes INTEGER NOT NULL,
                new_location TEXT NOT NULL,
                staff_message_id INTEGER,
                staff_channel_id INTEGER,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                resolved_by INTEGER,
                FOREIGN KEY(slot_id) REFERENCES atc_planning_slots(id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS absences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                motif TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                cancelled_at TEXT,
                log_message_id INTEGER,
                log_channel_id INTEGER
            )
        """)


        await db.execute("""
            CREATE TABLE IF NOT EXISTS role_guide_assignments (
                guild_id INTEGER NOT NULL,
                slot_key TEXT NOT NULL,
                user_ids TEXT NOT NULL DEFAULT '',
                discord_role_id INTEGER,
                PRIMARY KEY (guild_id, slot_key)
            )
        """)
        try:
            await db.execute(
                "ALTER TABLE role_guide_assignments ADD COLUMN discord_role_id INTEGER"
            )
        except aiosqlite.OperationalError:
            pass

        # Registre multi-compagnies (cartes publiées sur le serveur principal)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                company_guild_id INTEGER,
                ceo_id INTEGER,
                status TEXT,
                recruit_status TEXT,
                invite_url TEXT,
                logo_url TEXT,
                card_channel_id INTEGER,
                card_message_id INTEGER,
                status_channel_id INTEGER,
                status_message_id INTEGER,
                recruit_channel_id INTEGER,
                recruit_message_id INTEGER,
                created_at TEXT NOT NULL
            )
        """)
        # Callsigns des employés / pilotes (par serveur compagnie)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pilot_callsigns (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                callsign TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        await db.commit()


# ---------- Config serveur ----------

async def _upsert_guild_field(guild_id: int, field: str, value):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"""
            INSERT INTO guild_config (guild_id, {field})
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET {field}=excluded.{field}
        """, (guild_id, value))
        await db.commit()


def _ids_to_storage(value) -> str | int | None:
    """Accepte un int, une liste d'ints, ou une str — stocke de façon SQLite-safe."""
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        ids = [str(int(v)) for v in value if v is not None]
        return ",".join(ids) if ids else None
    if isinstance(value, str):
        return value
    return int(value)


def parse_id_list(raw) -> list[int]:
    """Lit un champ config qui peut être int unique ou 'id1,id2,…'."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, int):
        return [raw]
    parts = str(raw).replace(";", ",").split(",")
    out = []
    for p in parts:
        p = p.strip()
        if p.isdigit():
            out.append(int(p))
    return out


async def set_formateur_role(guild_id: int, role_id):
    """role_id : int unique ou liste d'IDs (plusieurs rôles formateur)."""
    await _upsert_guild_field(guild_id, "formateur_role_id", _ids_to_storage(role_id))


async def set_announcement_channel(guild_id: int, channel_id):
    """channel_id : int unique ou liste (premier salon utilisé comme défaut)."""
    if isinstance(channel_id, (list, tuple, set)):
        ids = [int(v) for v in channel_id if v is not None]
        channel_id = ids[0] if ids else None
    if channel_id is None:
        return
    await _upsert_guild_field(guild_id, "announcement_channel_id", int(channel_id))


async def set_staff_role(guild_id: int, role_id: int):
    await _upsert_guild_field(guild_id, "staff_role_id", role_id)


async def set_ticket_access_category(guild_id: int, category_id: int):
    await _upsert_guild_field(guild_id, "ticket_access_category_id", category_id)


async def set_ticket_support_category(guild_id: int, category_id: int):
    await _upsert_guild_field(guild_id, "ticket_support_category_id", category_id)


async def set_ticket_log_channel(guild_id: int, channel_id: int):
    await _upsert_guild_field(guild_id, "ticket_log_channel_id", channel_id)


async def set_ticket_ping_role(guild_id: int, role_id: int):
    await _upsert_guild_field(guild_id, "ticket_ping_role_id", role_id)


async def set_ticket_support_ping_role(guild_id: int, role_id: int):
    """Rôle mentionné uniquement à l'ouverture des tickets Support."""
    await _upsert_guild_field(guild_id, "ticket_support_ping_role_id", role_id)


async def set_freq_lock_deny_roles(guild_id: int, role_id):
    """Rôles bloqués (view/connect) quand une fréquence est verrouillée."""
    await _upsert_guild_field(guild_id, "freq_lock_deny_role_ids", _ids_to_storage(role_id))


async def set_atc_planning_mod_channel(guild_id: int, channel_id: int):
    """Salon staff pour valider les modifications de créneaux planning ATC."""
    await _upsert_guild_field(guild_id, "atc_planning_mod_channel_id", channel_id)


async def set_absence_roles(guild_id: int, role_id):
    """Jusqu'à 8 rôles autorisés à déposer une absence."""
    await _upsert_guild_field(guild_id, "absence_role_ids", _ids_to_storage(role_id))


async def set_absence_temp_role(guild_id: int, role_id: int):
    """Rôle temporaire « Absent » appliqué pendant l'absence."""
    await _upsert_guild_field(guild_id, "absence_temp_role_id", role_id)


async def set_absence_log_channel(guild_id: int, channel_id: int):
    await _upsert_guild_field(guild_id, "absence_log_channel_id", channel_id)


async def set_absence_ping_roles(guild_id: int, role_id):
    """Rôles mentionnés à chaque nouvelle absence (multi)."""
    await _upsert_guild_field(guild_id, "absence_ping_role_ids", _ids_to_storage(role_id))


async def set_absence_panel(guild_id: int, channel_id: int, message_id: int):
    await _upsert_guild_field(guild_id, "absence_panel_channel_id", channel_id)
    await _upsert_guild_field(guild_id, "absence_panel_message_id", message_id)


async def set_ticket_access_log_channel(guild_id: int, channel_id: int):
    await _upsert_guild_field(guild_id, "ticket_access_log_channel_id", channel_id)


async def set_ticket_support_log_channel(guild_id: int, channel_id: int):
    await _upsert_guild_field(guild_id, "ticket_support_log_channel_id", channel_id)


async def set_disponibilites_channel(guild_id: int, channel_id: int):
    await _upsert_guild_field(guild_id, "disponibilites_channel_id", channel_id)


async def set_freq_category(guild_id: int, category_id: int):
    await _upsert_guild_field(guild_id, "freq_category_id", category_id)


async def set_freq_text_category(guild_id: int, category_id: int):
    await _upsert_guild_field(guild_id, "freq_text_category_id", category_id)


async def set_freq_announce_channel(guild_id: int, channel_id: int):
    await _upsert_guild_field(guild_id, "freq_announce_channel_id", channel_id)


async def set_freq_ping_role(guild_id: int, role_id: int):
    await _upsert_guild_field(guild_id, "freq_ping_role_id", role_id)


async def set_freq_log_channel(guild_id: int, channel_id: int):
    await _upsert_guild_field(guild_id, "freq_log_channel_id", channel_id)


async def set_session_ping_avion_role(guild_id: int, role_id: int):
    await _upsert_guild_field(guild_id, "session_ping_avion_role_id", role_id)


async def set_session_ping_pilote_role(guild_id: int, role_id: int):
    await _upsert_guild_field(guild_id, "session_ping_pilote_role_id", role_id)


async def set_session_ping_atc_role(guild_id: int, role_id: int):
    await _upsert_guild_field(guild_id, "session_ping_atc_role_id", role_id)


async def set_session_ping_site_atc_role(guild_id: int, role_id: int):
    await _upsert_guild_field(guild_id, "session_ping_site_atc_role_id", role_id)


async def set_session_ping_site_pilote_role(guild_id: int, role_id: int):
    await _upsert_guild_field(guild_id, "session_ping_site_pilote_role_id", role_id)


async def set_flightplan_channel(guild_id: int, channel_id: int):
    await _upsert_guild_field(guild_id, "flightplan_channel_id", channel_id)


async def set_flightplan_log_channel(guild_id: int, channel_id: int):
    await _upsert_guild_field(guild_id, "flightplan_log_channel_id", channel_id)


async def get_guild_config(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM guild_config WHERE guild_id = ?", (guild_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


# ---------- Sessions ----------

async def create_session(guild_id, title, description, formateur_id, date_time_utc,
                          max_participants, created_by, session_type=None,
                          duration_minutes=120):
    if not duration_minutes or duration_minutes <= 0:
        duration_minutes = 120
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            INSERT INTO sessions
            (guild_id, title, description, formateur_id, date_time_utc,
             max_participants, created_by, session_type, duration_minutes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (guild_id, title, description, formateur_id,
              date_time_utc.isoformat(), max_participants, created_by, session_type,
              int(duration_minutes)))
        await db.commit()
        return cur.lastrowid


async def set_session_message(session_id, channel_id, message_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE sessions SET channel_id = ?, message_id = ? WHERE id = ?",
            (channel_id, message_id, session_id)
        )
        await db.commit()


async def get_session(session_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_upcoming_sessions(guild_id: int, include_cancelled=False):
    now_iso = datetime.now(timezone.utc).isoformat()
    query = """
        SELECT * FROM sessions
        WHERE guild_id = ? AND date_time_utc >= ?
    """
    if not include_cancelled:
        query += " AND status != 'cancelled'"
    query += " ORDER BY date_time_utc ASC"

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(query, (guild_id, now_iso))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def list_all_active_sessions_all_guilds():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""
            SELECT * FROM sessions
            WHERE status = 'planned' AND message_id IS NOT NULL
        """)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def list_sessions_needing_reminder(hours_before: int, field: str):
    now = datetime.now(timezone.utc)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(f"""
            SELECT * FROM sessions
            WHERE status = 'planned' AND {field} = 0
        """)
        rows = await cur.fetchall()
        result = []
        for r in rows:
            session = dict(r)
            session_dt = datetime.fromisoformat(session["date_time_utc"])
            delta_hours = (session_dt - now).total_seconds() / 3600
            if 0 < delta_hours <= hours_before:
                result.append(session)
        return result


async def mark_reminder_sent(session_id: int, field: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE sessions SET {field} = 1 WHERE id = ?", (session_id,))
        await db.commit()


async def cancel_session(session_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE sessions SET status = 'cancelled' WHERE id = ?", (session_id,))
        await db.commit()


async def delete_session(session_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM inscriptions WHERE session_id = ?", (session_id,))
        await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await db.commit()


# ---------- Inscriptions ----------

async def register_user(session_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("""
                INSERT INTO inscriptions (session_id, user_id, inscribed_at)
                VALUES (?, ?, ?)
            """, (session_id, user_id, datetime.now(timezone.utc).isoformat()))
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def unregister_user(session_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM inscriptions WHERE session_id = ? AND user_id = ?",
            (session_id, user_id)
        )
        await db.commit()
        return cur.rowcount > 0


async def get_participants(session_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT user_id FROM inscriptions WHERE session_id = ? ORDER BY inscribed_at ASC",
            (session_id,)
        )
        rows = await cur.fetchall()
        return [r["user_id"] for r in rows]


async def count_participants(session_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM inscriptions WHERE session_id = ?", (session_id,)
        )
        row = await cur.fetchone()
        return row[0]


async def is_registered(session_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM inscriptions WHERE session_id = ? AND user_id = ?",
            (session_id, user_id)
        )
        row = await cur.fetchone()
        return row is not None


async def list_user_sessions(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""
            SELECT s.* FROM sessions s
            JOIN inscriptions i ON i.session_id = s.id
            WHERE s.guild_id = ? AND i.user_id = ? AND s.status = 'planned'
            ORDER BY s.date_time_utc ASC
        """, (guild_id, user_id))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


# ---------- Fréquences ----------

async def get_frequency_by_voice(guild_id: int, voice_channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM frequencies WHERE guild_id = ? AND voice_channel_id = ? AND status = 'active'",
            (guild_id, voice_channel_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_active_frequency_for_atc(guild_id: int, atc_user_id: int):
    """Retourne la fréquence active gérée par cet ATC (ou None)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM frequencies WHERE guild_id = ? AND atc_user_id = ? "
            "AND status = 'active' ORDER BY id DESC LIMIT 1",
            (guild_id, atc_user_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_frequency(freq_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM frequencies WHERE id = ?", (freq_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def create_frequency(
    guild_id,
    voice_channel_id,
    name,
    atc_user_id,
    text_channel_id=None,
    message_id=None,
    icao=None,
    position=None,
    frequency_mhz=None,
    languages=None,
):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT INTO frequencies
            (guild_id, voice_channel_id, text_channel_id, message_id, name,
             icao, atc_user_id, status, created_at, position, frequency_mhz, languages)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
            """,
            (
                guild_id,
                voice_channel_id,
                text_channel_id,
                message_id,
                name,
                icao,
                atc_user_id,
                datetime.now(timezone.utc).isoformat(),
                position,
                frequency_mhz,
                languages,
            ),
        )
        await db.commit()
        return cur.lastrowid


async def get_active_atc_for_icao(guild_id: int, icao: str):
    """Retourne la fréquence active liée à cet ICAO (si existante)."""
    icao = (icao or "").upper().strip()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM frequencies WHERE guild_id = ? AND status = 'active' "
            "AND UPPER(icao) = ?",
            (guild_id, icao),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_active_icaos(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT icao, atc_user_id, name FROM frequencies "
            "WHERE guild_id = ? AND status = 'active' AND icao IS NOT NULL AND icao != ''",
            (guild_id,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def create_flight_plan(guild_id, user_id, flight_type, callsign, departure,
                             arrival, gate=None, simbrief_url=None, message_id=None,
                             strip_status="STAND", strip_atc=None, sid_rwy=None,
                             star_rwy=None, initial_climb=None, remark=None,
                             strip_atc_user_id=None, squawk=None):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            INSERT INTO flight_plans
            (guild_id, user_id, flight_type, callsign, departure, arrival,
             gate, simbrief_url, message_id, created_at,
             sid_rwy, star_rwy, initial_climb, strip_status, strip_atc, remark,
             strip_atc_user_id, squawk)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            guild_id, user_id, flight_type, callsign, departure, arrival,
            gate, simbrief_url, message_id,
            datetime.now(timezone.utc).isoformat(),
            sid_rwy, star_rwy, initial_climb, strip_status or "STAND",
            strip_atc, remark, strip_atc_user_id, squawk,
        ))
        await db.commit()
        return cur.lastrowid


async def set_flight_plan_message(plan_id: int, message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE flight_plans SET message_id = ? WHERE id = ?",
            (message_id, plan_id),
        )
        await db.commit()


async def update_flight_plan(plan_id: int, **fields):
    allowed = {
        "gate", "sid_rwy", "star_rwy", "initial_climb", "strip_status",
        "strip_atc", "strip_atc_user_id", "remark", "message_id",
        "callsign", "departure", "arrival", "squawk",
    }
    data = {k: v for k, v in fields.items() if k in allowed}
    if not data:
        return
    cols = ", ".join(f"{k} = ?" for k in data)
    values = list(data.values()) + [plan_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE flight_plans SET {cols} WHERE id = ?", values
        )
        await db.commit()


async def list_flight_plans(
    guild_id: int,
    icao: str | None = None,
    hours: int = 6,
    limit: int = 25,
    atc_user_id: int | None = None,
):
    """
    Plans de vol récents.
    - icao : filtre départ OU arrivée
    - atc_user_id : strips assignées à cet ATC
    """
    from datetime import timedelta

    since = (datetime.now(timezone.utc) - timedelta(hours=max(1, hours))).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        clauses = ["guild_id = ?", "created_at >= ?"]
        params: list = [guild_id, since]
        if icao:
            icao = icao.upper().strip()
            clauses.append("(UPPER(departure) = ? OR UPPER(arrival) = ?)")
            params.extend([icao, icao])
        if atc_user_id is not None:
            clauses.append("strip_atc_user_id = ?")
            params.append(atc_user_id)
        params.append(limit)
        sql = (
            f"SELECT * FROM flight_plans WHERE {' AND '.join(clauses)} "
            f"ORDER BY created_at DESC LIMIT ?"
        )
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_flight_plan(plan_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM flight_plans WHERE id = ?", (plan_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_recent_flight_plan_ids(hours: int = 48, limit: int = 80):
    """IDs de plans récents (toutes guilds) pour ré-enregistrer les vues persistantes."""
    from datetime import timedelta

    since = (datetime.now(timezone.utc) - timedelta(hours=max(1, hours))).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT id FROM flight_plans
            WHERE created_at >= ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (since, limit),
        )
        rows = await cur.fetchall()
        return [r[0] for r in rows]


async def update_frequency(freq_id: int, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [freq_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE frequencies SET {cols} WHERE id = ?", values)
        await db.commit()


async def close_frequency(freq_id: int):
    await update_frequency(freq_id, status="closed", locked=0)


async def list_active_frequencies(guild_id: int = None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if guild_id:
            cur = await db.execute(
                "SELECT * FROM frequencies WHERE status = 'active' AND guild_id = ?",
                (guild_id,),
            )
        else:
            cur = await db.execute("SELECT * FROM frequencies WHERE status = 'active'")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


# ---------- Tickets ----------

async def create_ticket(guild_id, channel_id, user_id, ticket_type, motif: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            INSERT INTO tickets
            (guild_id, channel_id, user_id, ticket_type, status, created_at, motif)
            VALUES (?, ?, ?, ?, 'open', ?, ?)
        """, (guild_id, channel_id, user_id, ticket_type,
              datetime.now(timezone.utc).isoformat(), motif))
        await db.commit()
        return cur.lastrowid


async def get_ticket_by_channel(channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM tickets WHERE channel_id = ?", (channel_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_open_ticket_for_user(guild_id: int, user_id: int, ticket_type: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if ticket_type:
            cur = await db.execute(
                "SELECT * FROM tickets WHERE guild_id = ? AND user_id = ? "
                "AND ticket_type = ? AND status = 'open'",
                (guild_id, user_id, ticket_type),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM tickets WHERE guild_id = ? AND user_id = ? AND status = 'open'",
                (guild_id, user_id),
            )
        row = await cur.fetchone()
        return dict(row) if row else None


async def claim_ticket(ticket_id: int, staff_id: int | None):
    """Assigne un staff au ticket, ou retire l'assignation si staff_id is None."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tickets SET claimed_by = ? WHERE id = ?", (staff_id, ticket_id)
        )
        await db.commit()


async def close_ticket(ticket_id: int, close_reason: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tickets SET status = 'closed', closed_at = ?, close_reason = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), close_reason, ticket_id),
        )
        await db.commit()


async def list_disponibilites_by_ticket_channel(ticket_channel_id: int):
    """Dispos liées à un salon ticket (pour mise à jour couleur à la fermeture)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM disponibilites WHERE ticket_channel_id = ?",
            (ticket_channel_id,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def list_user_planned_sessions_by_type(guild_id: int, user_id: int, session_type: str):
    """Sessions planifiées du même type auxquelles l'utilisateur est inscrit."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT s.* FROM sessions s
            JOIN inscriptions i ON i.session_id = s.id
            WHERE s.guild_id = ? AND i.user_id = ?
              AND s.session_type = ? AND s.status = 'planned'
            ORDER BY s.date_time_utc ASC
            """,
            (guild_id, user_id, session_type),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def list_user_planned_sessions(guild_id: int, user_id: int):
    """Toutes les sessions planifiées (date future) auxquelles l'utilisateur est inscrit."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT s.* FROM sessions s
            JOIN inscriptions i ON i.session_id = s.id
            WHERE s.guild_id = ? AND i.user_id = ? AND s.status = 'planned'
            ORDER BY s.date_time_utc ASC
            """,
            (guild_id, user_id),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def list_past_planned_sessions():
    """Sessions encore 'planned' dont la date est passée."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        now = datetime.now(timezone.utc).isoformat()
        cur = await db.execute(
            """
            SELECT * FROM sessions
            WHERE status = 'planned' AND date_time_utc < ?
            """,
            (now,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def mark_session_done(session_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE sessions SET status = 'done' WHERE id = ?",
            (session_id,),
        )
        await db.commit()


# ---------- Disponibilités entretien ----------

async def create_disponibilite(
    guild_id: int,
    target_user_id: int,
    requested_by: int,
    dispos_text: str,
    commentaire: str = None,
    ticket_channel_id: int = None,
):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT INTO disponibilites
            (guild_id, target_user_id, requested_by, dispos_text, commentaire,
             ticket_channel_id, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                guild_id,
                target_user_id,
                requested_by,
                dispos_text,
                commentaire,
                ticket_channel_id,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()
        return cur.lastrowid


async def get_disponibilite(dispos_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM disponibilites WHERE id = ?", (dispos_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def update_disponibilite(dispos_id: int, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [dispos_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE disponibilites SET {cols} WHERE id = ?", values
        )
        await db.commit()


async def list_open_disponibilites():
    """Pour ré-enregistrer les vues au démarrage."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM disponibilites WHERE status IN ('pending', 'taken') "
            "AND message_id IS NOT NULL"
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


# ---------- Pré-ouvertures planifiées ----------

async def create_preopen_schedule(
    guild_id: int,
    atc_user_id: int,
    position: str,
    location: str,
    icao: str | None,
    frequency_mhz: str,
    languages: str | None,
    hour_str: str,
    scheduled_at: str,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT INTO preopen_schedules
            (guild_id, atc_user_id, position, location, icao, frequency_mhz,
             languages, hour_str, scheduled_at, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                guild_id,
                atc_user_id,
                position,
                location,
                icao,
                frequency_mhz,
                languages,
                hour_str,
                scheduled_at,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()
        return cur.lastrowid


async def list_due_preopen_schedules(now_iso: str):
    """Pré-ouvertures pending dont scheduled_at <= now."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT * FROM preopen_schedules
            WHERE status = 'pending' AND scheduled_at <= ?
            ORDER BY scheduled_at ASC
            """,
            (now_iso,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_pending_preopen_for_atc(guild_id: int, atc_user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT * FROM preopen_schedules
            WHERE guild_id = ? AND atc_user_id = ? AND status = 'pending'
            ORDER BY scheduled_at ASC LIMIT 1
            """,
            (guild_id, atc_user_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def update_preopen_schedule(schedule_id: int, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [schedule_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE preopen_schedules SET {cols} WHERE id = ?", values
        )
        await db.commit()


async def mark_preopen_done(schedule_id: int):
    await update_preopen_schedule(schedule_id, status="done")


async def cancel_preopen_schedule(schedule_id: int):
    await update_preopen_schedule(schedule_id, status="cancelled")



# ---------- Concours photo ----------

async def create_contest(
    guild_id: int,
    name: str,
    channel_id: int,
    start_at: str,
    end_at: str,
    max_photos: int,
    created_by: int,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT INTO contests
            (guild_id, name, channel_id, start_at, end_at, max_photos, status, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                guild_id,
                name,
                channel_id,
                start_at,
                end_at,
                max_photos,
                created_by,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()
        return cur.lastrowid


async def get_active_contest(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT * FROM contests
            WHERE guild_id = ? AND status = 'active'
            ORDER BY id DESC LIMIT 1
            """,
            (guild_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_contest(contest_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM contests WHERE id = ?", (contest_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_due_contests(now_iso: str):
    """Concours actifs dont end_at <= now."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT * FROM contests
            WHERE status = 'active' AND end_at <= ?
            ORDER BY end_at ASC
            """,
            (now_iso,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def end_contest(contest_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE contests
            SET status = 'ended', ended_at = ?
            WHERE id = ?
            """,
            (datetime.now(timezone.utc).isoformat(), contest_id),
        )
        await db.commit()


async def add_contest_entry(
    contest_id: int,
    user_id: int,
    message_id: int,
    channel_id: int,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT INTO contest_entries
            (contest_id, user_id, message_id, channel_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                contest_id,
                user_id,
                message_id,
                channel_id,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()
        return cur.lastrowid


async def count_user_entries(contest_id: int, user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM contest_entries WHERE contest_id = ? AND user_id = ?",
            (contest_id, user_id),
        )
        row = await cur.fetchone()
        return row[0] if row else 0


async def get_contest_entries(contest_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT * FROM contest_entries
            WHERE contest_id = ?
            ORDER BY likes DESC, id ASC
            """,
            (contest_id,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def update_entry_likes(entry_id: int, likes: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE contest_entries SET likes = ? WHERE id = ?",
            (likes, entry_id),
        )
        await db.commit()


async def update_entry_results(
    entry_id: int,
    rank: int,
    points_participation: int,
    points_likes: int,
    points_rank: int,
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE contest_entries
            SET rank = ?, points_participation = ?, points_likes = ?, points_rank = ?
            WHERE id = ?
            """,
            (rank, points_participation, points_likes, points_rank, entry_id),
        )
        await db.commit()


async def add_points(
    guild_id: int,
    user_id: int,
    amount: int,
    reason: str,
    contest_id: int | None = None,
):
    if amount == 0:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO user_points (guild_id, user_id, total_points)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                total_points = total_points + excluded.total_points
            """,
            (guild_id, user_id, amount),
        )
        await db.execute(
            """
            INSERT INTO points_history
            (guild_id, user_id, amount, reason, contest_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                user_id,
                amount,
                reason,
                contest_id,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()


async def remove_points(
    guild_id: int,
    user_id: int,
    amount: int,
    reason: str,
):
    """Retire des points (amount positif). Ne descend pas en dessous de 0."""
    if amount <= 0:
        return 0
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT total_points FROM user_points WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        current = row["total_points"] if row else 0
        to_remove = min(amount, current)
        if to_remove <= 0:
            return 0
        await db.execute(
            """
            INSERT INTO user_points (guild_id, user_id, total_points)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                total_points = total_points - ?
            """,
            (guild_id, user_id, -to_remove, to_remove),
        )
        await db.execute(
            """
            INSERT INTO points_history
            (guild_id, user_id, amount, reason, contest_id, created_at)
            VALUES (?, ?, ?, ?, NULL, ?)
            """,
            (
                guild_id,
                user_id,
                -to_remove,
                reason,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()
        return to_remove


async def get_user_points(guild_id: int, user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT total_points FROM user_points WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        return row[0] if row else 0


async def get_user_points_history(guild_id: int, user_id: int, limit: int = 25):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT * FROM points_history
            WHERE guild_id = ? AND user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (guild_id, user_id, limit),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_leaderboard(guild_id: int, limit: int = 100):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT user_id, total_points
            FROM user_points
            WHERE guild_id = ? AND total_points > 0
            ORDER BY total_points DESC, user_id ASC
            LIMIT ?
            """,
            (guild_id, limit),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


# ---------- Planning ATC hebdomadaire ----------

async def create_atc_planning_slot(
    guild_id: int,
    atc_user_id: int,
    week_start: str,
    slot_date: str,
    start_time: str,
    end_time: str,
    duration_minutes: int,
    location: str,
    created_by: int,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT INTO atc_planning_slots
            (guild_id, atc_user_id, week_start, slot_date, start_time, end_time,
             duration_minutes, location, status, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                guild_id,
                atc_user_id,
                week_start,
                slot_date,
                start_time,
                end_time,
                duration_minutes,
                location,
                created_by,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()
        return cur.lastrowid


async def get_atc_planning_slot(slot_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM atc_planning_slots WHERE id = ?", (slot_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_atc_planning_slots(guild_id: int, week_start: str):
    """Créneaux actifs d'une semaine (week_start = lundi YYYY-MM-DD)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT * FROM atc_planning_slots
            WHERE guild_id = ? AND week_start = ? AND status = 'active'
            ORDER BY slot_date ASC, start_time ASC
            """,
            (guild_id, week_start),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def list_atc_planning_slots_for_user(
    guild_id: int, user_id: int, week_start: str | None = None
):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if week_start:
            cur = await db.execute(
                """
                SELECT * FROM atc_planning_slots
                WHERE guild_id = ? AND atc_user_id = ? AND week_start = ?
                  AND status = 'active'
                ORDER BY slot_date ASC, start_time ASC
                """,
                (guild_id, user_id, week_start),
            )
        else:
            cur = await db.execute(
                """
                SELECT * FROM atc_planning_slots
                WHERE guild_id = ? AND atc_user_id = ? AND status = 'active'
                ORDER BY slot_date ASC, start_time ASC
                """,
                (guild_id, user_id),
            )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def cancel_atc_planning_slot(slot_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE atc_planning_slots SET status = 'cancelled' WHERE id = ?",
            (slot_id,),
        )
        await db.commit()


async def update_atc_planning_slot(slot_id: int, **fields):
    if not fields:
        return
    allowed = {
        "atc_user_id",
        "week_start",
        "slot_date",
        "start_time",
        "end_time",
        "duration_minutes",
        "location",
        "status",
    }
    cols = []
    values = []
    for k, v in fields.items():
        if k in allowed:
            cols.append(f"{k} = ?")
            values.append(v)
    if not cols:
        return
    values.append(slot_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE atc_planning_slots SET {', '.join(cols)} WHERE id = ?",
            values,
        )
        await db.commit()


async def set_atc_planning_panel(
    guild_id: int, week_offset: int, channel_id: int, message_id: int
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO atc_planning_panels (guild_id, week_offset, channel_id, message_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, week_offset) DO UPDATE SET
                channel_id = excluded.channel_id,
                message_id = excluded.message_id
            """,
            (guild_id, week_offset, channel_id, message_id),
        )
        await db.commit()


async def get_atc_planning_panel(guild_id: int, week_offset: int = 0):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT * FROM atc_planning_panels
            WHERE guild_id = ? AND week_offset = ?
            """,
            (guild_id, week_offset),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_atc_planning_panels(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM atc_planning_panels WHERE guild_id = ?",
            (guild_id,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def set_atc_planning_channel(guild_id: int, channel_id: int):
    await _upsert_guild_field(guild_id, "atc_planning_channel_id", channel_id)


async def set_pilot_role(guild_id: int, role_id: int):
    await _upsert_guild_field(guild_id, "pilot_role_id", role_id)


async def set_callsign_manager_role(guild_id: int, role_id: int):
    """Rôle autorisé à /callsign-set et /callsign-supprimer (serveur compagnie)."""
    await _upsert_guild_field(guild_id, "callsign_manager_role_id", role_id)


async def set_gerant_atc_role(guild_id: int, role_id):
    """Rôle(s) Gérant ATC — peuvent modifier le planning ATC.

    role_id : int unique ou liste d'IDs.
    """
    await _upsert_guild_field(guild_id, "gerant_atc_role_id", _ids_to_storage(role_id))


async def set_freq_admin_panel(guild_id: int, channel_id: int, message_id: int):
    """Panel admin fréquences (ouvertes / fermer / verrouiller)."""
    await _upsert_guild_field(guild_id, "freq_admin_panel_channel_id", channel_id)
    await _upsert_guild_field(guild_id, "freq_admin_panel_message_id", message_id)


async def set_companies_forum_channel(guild_id: int, channel_id: int | None):
    await _upsert_guild_field(guild_id, "companies_forum_channel_id", channel_id)


async def set_pilot_list_message(guild_id: int, channel_id: int, message_id: int):
    await _upsert_guild_field(guild_id, "pilot_list_channel_id", channel_id)
    await _upsert_guild_field(guild_id, "pilot_list_message_id", message_id)


async def set_pilot_callsign(guild_id: int, user_id: int, callsign: str):
    """Attribue ou met à jour le callsign d'un employé sur ce serveur."""
    now = datetime.now(timezone.utc).isoformat()
    cs = (callsign or "").strip().upper()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO pilot_callsigns (guild_id, user_id, callsign, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                callsign = excluded.callsign,
                updated_at = excluded.updated_at
            """,
            (guild_id, user_id, cs, now),
        )
        await db.commit()


async def remove_pilot_callsign(guild_id: int, user_id: int) -> bool:
    """Supprime le callsign d'un employé. Retourne True si une ligne a été supprimée."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM pilot_callsigns WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_pilot_callsign(guild_id: int, user_id: int) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT callsign FROM pilot_callsigns WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        return row["callsign"] if row else None


async def get_all_pilot_callsigns(guild_id: int) -> dict[int, str]:
    """Retourne {user_id: callsign} pour le serveur."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT user_id, callsign FROM pilot_callsigns WHERE guild_id = ?",
            (guild_id,),
        )
        rows = await cur.fetchall()
        return {int(r["user_id"]): r["callsign"] for r in rows}


async def set_config_panel_message(guild_id: int, channel_id: int, message_id: int):
    await _upsert_guild_field(guild_id, "config_panel_channel_id", channel_id)
    await _upsert_guild_field(guild_id, "config_panel_message_id", message_id)


# ---------- Compagnies (multi-cartes sur le serveur principal) ----------

async def create_company(
    name: str,
    *,
    company_guild_id: int | None = None,
    ceo_id: int | None = None,
    invite_url: str | None = None,
    logo_url: str | None = None,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT INTO companies
                (name, company_guild_id, ceo_id, status, recruit_status,
                 invite_url, logo_url, created_at)
            VALUES (?, ?, ?, NULL, NULL, ?, ?, ?)
            """,
            (name.strip(), company_guild_id, ceo_id, invite_url, logo_url, now),
        )
        await db.commit()
        return cur.lastrowid


async def get_company(company_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM companies WHERE id = ?", (company_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_company_by_guild(company_guild_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM companies WHERE company_guild_id = ?",
            (company_guild_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_companies() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM companies ORDER BY name COLLATE NOCASE")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def search_companies(query: str, limit: int = 25) -> list[dict]:
    q = f"%{(query or '').strip()}%"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT * FROM companies
            WHERE name LIKE ?
            ORDER BY name COLLATE NOCASE
            LIMIT ?
            """,
            (q, limit),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def update_company(company_id: int, **fields) -> None:
    if not fields:
        return
    allowed = {
        "name",
        "company_guild_id",
        "ceo_id",
        "status",
        "recruit_status",
        "invite_url",
        "logo_url",
        "card_channel_id",
        "card_message_id",
        "status_channel_id",
        "status_message_id",
        "recruit_channel_id",
        "recruit_message_id",
    }
    sets = []
    values = []
    for k, v in fields.items():
        if k not in allowed:
            continue
        sets.append(f"{k} = ?")
        values.append(v)
    if not sets:
        return
    values.append(company_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE companies SET {', '.join(sets)} WHERE id = ?",
            values,
        )
        await db.commit()


async def delete_company(company_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        await db.commit()
        return cur.rowcount > 0


async def set_company_status_by_id(company_id: int, status: str):
    await update_company(company_id, status=status)


async def set_company_recruit_by_id(company_id: int, status: str):
    await update_company(company_id, recruit_status=status)


async def set_company_card_message_by_id(
    company_id: int, channel_id: int, message_id: int
):
    await update_company(
        company_id, card_channel_id=channel_id, card_message_id=message_id
    )


async def set_company_status_message_by_id(
    company_id: int, channel_id: int, message_id: int
):
    await update_company(
        company_id, status_channel_id=channel_id, status_message_id=message_id
    )


async def set_company_recruit_message_by_id(
    company_id: int, channel_id: int, message_id: int
):
    await update_company(
        company_id, recruit_channel_id=channel_id, recruit_message_id=message_id
    )


# ---------- Modifications planning ATC (validation staff) ----------

async def create_atc_planning_modification(
    slot_id: int,
    guild_id: int,
    requested_by: int,
    old: dict,
    new: dict,
):
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT INTO atc_planning_modifications (
                slot_id, guild_id, requested_by, status,
                old_slot_date, old_start_time, old_end_time, old_duration_minutes, old_location,
                new_slot_date, new_start_time, new_end_time, new_duration_minutes, new_location,
                created_at
            ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slot_id,
                guild_id,
                requested_by,
                old.get("slot_date"),
                old.get("start_time"),
                old.get("end_time"),
                old.get("duration_minutes"),
                old.get("location"),
                new["slot_date"],
                new["start_time"],
                new["end_time"],
                new["duration_minutes"],
                new["location"],
                now,
            ),
        )
        await db.commit()
        return cur.lastrowid


async def get_atc_planning_modification(mod_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM atc_planning_modifications WHERE id = ?", (mod_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_pending_modification_for_slot(slot_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT * FROM atc_planning_modifications
            WHERE slot_id = ? AND status = 'pending'
            ORDER BY id DESC LIMIT 1
            """,
            (slot_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_pending_atc_planning_modifications(guild_id: int | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if guild_id is not None:
            cur = await db.execute(
                """
                SELECT * FROM atc_planning_modifications
                WHERE status = 'pending' AND guild_id = ?
                """,
                (guild_id,),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM atc_planning_modifications WHERE status = 'pending'"
            )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def resolve_atc_planning_modification(
    mod_id: int, status: str, resolved_by: int
):
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE atc_planning_modifications
            SET status = ?, resolved_at = ?, resolved_by = ?
            WHERE id = ?
            """,
            (status, now, resolved_by, mod_id),
        )
        await db.commit()


async def set_atc_planning_modification_message(
    mod_id: int, channel_id: int, message_id: int
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE atc_planning_modifications
            SET staff_channel_id = ?, staff_message_id = ?
            WHERE id = ?
            """,
            (channel_id, message_id, mod_id),
        )
        await db.commit()


# ---------- Absences ----------

async def create_absence(
    guild_id: int,
    user_id: int,
    motif: str,
    start_date: str,
    end_date: str,
):
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT INTO absences
            (guild_id, user_id, motif, start_date, end_date, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'active', ?)
            """,
            (guild_id, user_id, motif, start_date, end_date, now),
        )
        await db.commit()
        return cur.lastrowid


async def get_absence(absence_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM absences WHERE id = ?", (absence_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_active_absence_for_user(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT * FROM absences
            WHERE guild_id = ? AND user_id = ? AND status = 'active'
            ORDER BY id DESC LIMIT 1
            """,
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_active_absences(guild_id: int | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if guild_id is not None:
            cur = await db.execute(
                "SELECT * FROM absences WHERE guild_id = ? AND status = 'active'",
                (guild_id,),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM absences WHERE status = 'active'"
            )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def cancel_absence(absence_id: int):
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE absences SET status = 'cancelled', cancelled_at = ?
            WHERE id = ?
            """,
            (now, absence_id),
        )
        await db.commit()


async def expire_absence(absence_id: int):
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE absences SET status = 'expired', cancelled_at = ?
            WHERE id = ?
            """,
            (now, absence_id),
        )
        await db.commit()


async def set_absence_log_message(
    absence_id: int, channel_id: int, message_id: int
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE absences SET log_channel_id = ?, log_message_id = ?
            WHERE id = ?
            """,
            (channel_id, message_id, absence_id),
        )
        await db.commit()


# ---------- Guide des rôles ----------

async def get_role_guide_discord_role(guild_id: int, slot_key: str) -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT discord_role_id FROM role_guide_assignments WHERE guild_id = ? AND slot_key = ?",
            (guild_id, slot_key),
        )
        row = await cur.fetchone()
        if not row or row["discord_role_id"] is None:
            return None
        return int(row["discord_role_id"])


async def get_all_role_guide_discord_roles(guild_id: int) -> dict[str, int]:
    """slot_key → discord_role_id pour les postes configurés."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT slot_key, discord_role_id FROM role_guide_assignments
            WHERE guild_id = ? AND discord_role_id IS NOT NULL
            """,
            (guild_id,),
        )
        rows = await cur.fetchall()
        return {r["slot_key"]: int(r["discord_role_id"]) for r in rows}


async def set_role_guide_discord_role(guild_id: int, slot_key: str, discord_role_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO role_guide_assignments (guild_id, slot_key, user_ids, discord_role_id)
            VALUES (?, ?, '', ?)
            ON CONFLICT(guild_id, slot_key) DO UPDATE SET
                discord_role_id = excluded.discord_role_id
            """,
            (guild_id, slot_key, discord_role_id),
        )
        await db.commit()


async def clear_role_guide_assignment(guild_id: int, slot_key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM role_guide_assignments WHERE guild_id = ? AND slot_key = ?",
            (guild_id, slot_key),
        )
        await db.commit()


async def set_role_guide_panel(guild_id: int, channel_id: int, message_ids: list[int]):
    await _upsert_guild_field(guild_id, "role_guide_channel_id", channel_id)
    await _upsert_guild_field(
        guild_id, "role_guide_message_ids", ",".join(str(i) for i in message_ids)
    )