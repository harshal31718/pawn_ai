#!/bin/bash
# Sets the pawn_anon role's password from the postgrest_anon_password Docker
# secret and grants it LOGIN. Runs after schema.sql (which creates the role
# NOLOGIN, since a plain .sql init file can't read a secret file) via
# docker-entrypoint-initdb.d's lexical run order — see docker-compose.yml.
set -euo pipefail

ANON_PW_FILE="/run/secrets/postgrest_anon_password"
if [ ! -f "$ANON_PW_FILE" ]; then
  echo "init_pawn_anon.sh: $ANON_PW_FILE not found, skipping (pawn_anon stays NOLOGIN)" >&2
  exit 0
fi
ANON_PW="$(cat "$ANON_PW_FILE")"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v anon_pw="$ANON_PW" <<-'EOSQL'
	alter role pawn_anon with login password :'anon_pw';
EOSQL
