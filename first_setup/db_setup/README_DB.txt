==============================
Setting up PostgreSQL + PostGIS
=========================================
Database      : postgres   (default PostgreSQL database)
Port          : 5432

1. In .cfg file, replace DATA_DIR and the ??? placeholder with your chosen admin password and internal reader password:
The script will refuse to run if the password is still set to ???

2. Run setup_postgres.sh. Later, the database starts automatically on boot.
    chmod +x first_setup/db_setup/setup_postgres.sh
    ./first_setup/db_setup/setup_postgres.sh


3. Verify the setup:
From the same machine: psql -U mom_admin -d postgres -h 127.0.0.1
From a remote machine: psql -U mom_admin -d postgres -h <server-ip>
As superuser (local only): sudo -u postgres psql
Inside psql:
    \dt        -- list all tables
    \q         -- quit

4. Utilities:
CHANGE A PASSWORD LATER: sudo -u postgres psql -c "ALTER ROLE mom_admin WITH PASSWORD 'newpassword';"
CREATE A READER ROLE: CREATE ROLE alice LOGIN PASSWORD 'temp1234' IN ROLE mom_reader;
ALTER A READER ROLE (by the user): ALTER ROLE alice PASSWORD 'her_own_secret';
Connection string format: postgresql://mom_admin:<password>@<host>:5432/postgres

==============================
Using DB
==============================

1. Sending data
Always insert into the staging tables, never directly into the _latest or history tables. 
The trigger chain handles everything automatically:
  - data is pushed to the _latest table
      → _latest triggers fire: old timestamp rows are cleared, data is
         copied to history with source-specific filtering

For GloFAS and Final Alert, omit matching_id_station / matching_id_watershed
from your INSERT. Those IDs are resolved automatically.

2. Quering data
The _latest tables hold one row per station/watershed representing the most recently loaded batch. 
History tables accumulate one row per (pfaf_id OR station, timestamp) per batch. Filter by timestamp to retrieve a specific batch.

GFMS and DFO filter out rows where all flood values are zero before writing
to history. A pfaf_id with no flood activity at a given timestamp is simply
absent from the history table for that timestamp. To get a valid row response 
(even for a timestamp with no flood activity), use the functions:

fn_get_gfms(timestamp, pfaf_id)  — single watershed lookup
fn_get_gfms_batch(timestamp)  — all watersheds for a timestamp

fn_get_dfo(timestamp, pfaf_id)  — single watershed lookup
fn_get_dfo_batch(timestamp)  — all watersheds for a timestamp

-----------------------------------------------------------------------
Python examples (psycopg2)
-----------------------------------------------------------------------
import psycopg2

conn = psycopg2.connect("postgresql://mom_admin:<password>@<host>:5432/postgres")
cur = conn.cursor()

# Single watershed
cur.execute("SELECT * FROM fn_get_gfms(%s, %s)", ('2024-01-15 06:00:00+00', 12345))
row = cur.fetchone()

